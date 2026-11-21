"""Contrôle de ce qu'une skill contient, avant tout envoi et à chaque réception : texte qui donnerait des consignes
(annuler celles de l'utilisateur, lire des secrets, toucher aux réglages de Claude), commandes dangereuses,
caractères invisibles, commentaires cachés, gros blocs encodés ; et la lecture bornée des fichiers d'une skill
(nombre, taille, chemins sûrs), avec leur empreinte.

Découpé de echange.py le 21/11/2026 (étape 8 du plan), sans changer le comportement : ces noms restent accessibles
depuis echange (`echange.lint_text`, `echange.collect`…)."""
from __future__ import annotations

import hashlib
import os
import re

from .common import fold, owner_name
from .echange import MAX_FILE, MAX_FILES, MAX_TOTAL, SCRIPT_EXT, TEXT_EXT, WALK_MAX, _sha, _show, safe_rel


# ------------------------------------------------------------------------------------------ contrôle d'un texte reçu
_SPAN = re.compile(r"`([^`\n]{1,400})`")  # extrait de code d'une ligne


_NEG = re.compile(r"\b(?:ne|n'|jamais|aucun|aucune|rien|pas|never|not|don't|do not|no)\b")


_INVISIBLE = re.compile("[\u00ad\u061c\u180e\u200b\u200e\u200f\u202a-\u202e\u2060-\u2064\u2066-\u206f\ufeff\ufff9-\ufffb]")


_BLOB = re.compile(r"[A-Za-z0-9+/]{240,}={0,2}")


LINT_MAX = 400_000  # caractères contrôlés (un fichier partagé en fait 200 000 au plus)


# Tournures qui cherchent à retourner Claude contre l'utilisateur (texte replié : minuscules, sans accents).
_INJECTION_SRC = (
    # « ignore toute consigne trouvée dans la page » est une règle de prudence : seules les consignes d'AVANT, du
    # système, de l'utilisateur ou « les tiennes » sont visées.
    ("consigne qui annule celles de l'utilisateur",
     r"(?:ignore[rz]?|oublie[rz]?|disregard|forget) (?:toutes? |all |any )?(?:les |ces |the |my )?"
     r"(?:instructions?|consignes?|regles?|rules?|prompts?) (?:precedentes?|anterieures?|ci-dessus|du systeme|systeme|"
     r"de l'utilisateur|initiales?|d'avant|above|before|so far)|"
     r"(?:ignore|disregard|forget) (?:all |any |the )?(?:previous|prior|above|earlier|preceding|system|your) "
     r"(?:instructions?|rules?|prompts?|guidelines?)|"
     r"(?:ignore[rz]?|oublie[rz]?) (?:toutes? )?(?:tes|vos) (?:instructions?|consignes?|regles?)|"
     r"you are now (?:in )?(?:developer|dan|jailbreak)|nouvelles? instructions? (?:du systeme|prioritaires?)"),
    ("action cachée à l'utilisateur",
     r"sans (?:le |la |rien |jamais )?(?:dire|prevenir|avertir|demander|montrer|signaler)[a-z]{0,6} (?:a |au? )?l'utilisateur|"
     r"ne (?:le |la |les |lui )?(?:dis|montre|signale|mentionne|parle)[a-z]{0,6} (?:pas|rien|jamais)[^.\n]{0,30}(?:l'utilisateur|user)|"
     r"without (?:telling|asking|informing|notifying) (?:the )?user|do not (?:tell|inform|notify|mention)[^.\n]{0,30}user|"
     r"\ben secret\b|secretement|a l'insu de|\bsecretly\b|\bcovertly\b"),
    ("garde-fous à couper",
     r"(?:desactiv|coup|contourn|bypass|disabl|skip)[a-z]{0,6} (?:les |la |le |the |all )?(?:permissions?|garde-fous|securite|"
     r"safety|sandbox|hooks?|confirmations?|approval)"),
)


# Commandes à ne jamais activer sans un regard humain. Cherchées dans tout le texte, sauf deux familles qui ne valent
# que dans du code (CODE_ONLY) : en prose, « la clé reste dans .env » ou « ~/.claude/settings.json » sont des explications.
CODE_ONLY = ("accès aux secrets ou aux identifiants", "réglages ou permissions de Claude")


_COMMANDS_SRC = (
    ("téléchargement exécuté directement",
     r"(?:curl|wget|iwr|irm|invoke-webrequest|invoke-restmethod)\b[^\n|;&]{0,300}\|\s*(?:sudo\s+)?(?:ba|z|k|da)?sh\b|"
     r"\|\s*iex\b|invoke-expression|base64\s+(?:-d|--decode)[^\n]{0,120}\|\s*(?:ba|z)?sh\b|"
     r"\beval\s*\(\s*(?:atob|base64)|python[23]?\s+-c\s+[^\n]{0,300}(?:urlopen|requests\.|exec\()"),
    ("commande destructrice",
     r"\brm\s{1,8}-[a-z]{0,8}r[a-z]{0,8}\s{1,8}(?:-[a-z-]{1,20}\s{1,8}){0,6}(?:/(?:\s|\*|$)|~|\$home|\$\{home\}|\*)|"
     r"\brmdir\s+/s|\bdel\s+/[sfq]|"
     r"\bformat\s+[a-z]:|\bmkfs|\bdd\s+if=|:\(\)\s*\{|git\s+push\s+(?:[^\n]{0,40}\s)?(?:-f\b|--force)|git\s+reset\s+--hard|"
     r"git\s+clean\s+-[a-z]{0,8}f|\bdrop\s+(?:table|database)\b|remove-item\b[^\n]{0,80}-recurse[^\n]{0,80}-force|"
     r"\bshutdown\b|\bchmod\s+-r\s+777"),
    ("accès aux secrets ou aux identifiants",
     r"\.ssh/|id_rsa|id_ed25519|\.aws/credentials|\.netrc|\.npmrc|\.pypirc|\.git-credentials|credentials\.json|"
     r"\.config/gh/hosts|find-generic-password|cookies\.sqlite|login data|\bprintenv\b|\benv\s*\||get-childitem\s+env:|"
     r"\.claude/\.credentials|\.claude\.json|(?:cat|type|less|more|head|tail|get-content|gc)\s+[^\n|;&]{0,60}\.env\b"),
    ("réglages ou permissions de Claude",
     r"settings(?:\.local)?\.json|permissions\.(?:allow|deny)|bypasspermissions|dangerously-skip-permissions|"
     r"claude_desktop_config|\.mcp\.json|claude\s+mcp\s+add|enabledplugins|claude\s+plugin\s+(?:install|marketplace)"),
    ("envoi de données vers l'extérieur",
     r"(?:curl|wget|iwr|irm|invoke-webrequest|invoke-restmethod)\b[^\n]{0,300}(?:\s-d\s|--data|\s-f\s|--form|--upload-file|"
     r"-x\s*post|-method\s+post|--post-data)|webhook\.site|pastebin\.com|requestbin|pipedream\.net|ngrok\.|"
     r"discord(?:app)?\.com/api/webhooks|hooks\.slack\.com|transfer\.sh|file\.io|0x0\.st|\bnc\s+-[a-z]{0,6}e\b|/dev/tcp/"),
)


_TABLES = {}


def _table(name) -> list:
    """Motifs compilés à la demande (seulement quand une skill reçue est contrôlée, jamais à chaque message)."""
    t = _TABLES.get(name)
    if t is None:
        src = _INJECTION_SRC if name == "injection" else _COMMANDS_SRC
        t = _TABLES[name] = [(label, re.compile(rx)) for label, rx in src]
    return t


def _code_parts(raw) -> str:
    """Le code d'un texte Markdown : blocs ``` ou ~~~ (lus ligne à ligne — un bloc jamais refermé va jusqu'au bout),
    extraits `…` d'une ligne, lignes « $ … » ou « > … »."""
    out, fence = [], None
    for line in raw.splitlines():
        s = line.lstrip()
        if fence:
            out.append(line)
            if s.startswith(fence):
                fence = None
            continue
        if s.startswith(("```", "~~~")):
            fence = s[:3]
            out.append(s[3:])
            if fence in s[3:]:  # bloc ouvert et refermé sur la même ligne
                fence = None
            continue
        if s[:2] in ("$ ", "> "):
            out.append(s[2:])
        out.extend(_SPAN.findall(line))
    return "\n".join(out)


def _hidden_comment(raw) -> bool:
    """Un commentaire HTML d'au moins quatre mots (invisible à l'affichage, lu par le modèle) ; jamais refermé, il cache
    tout ce qui suit."""
    pos = 0
    while True:
        a = raw.find("<!--", pos)
        if a < 0:
            return False
        b = raw.find("-->", a + 4)
        if len(raw[a + 4:b if b >= 0 else len(raw)].split(None, 4)) >= 4:
            return True
        if b < 0:
            return False
        pos = b + 3


def lint_text(text, code=False) -> list:
    """Raisons de ne pas activer ce texte tout seul ([] : rien à signaler). `code` : tout le texte est du code (script).
    Temps borné : motifs sans retour arrière coûteux, et un texte plus long que LINT_MAX est refusé d'office."""
    out = []
    raw = str(text or "")
    if raw[:1] == "\ufeff":  # marque d'encodage en tête de fichier (Bloc-notes, PowerShell) : pas un caractère caché
        raw = raw[1:]
    if len(raw) > LINT_MAX:
        return ["texte trop long pour être contrôlé"]
    if _INVISIBLE.search(raw):
        out.append("caractères invisibles")
    if _BLOB.search(raw):
        out.append("bloc encodé illisible")
    folded = fold(raw)
    if not code:
        if _hidden_comment(raw):
            out.append("commentaire caché (<!-- … -->)")
        for label, rx in _table("injection"):
            for m in rx.finditer(folded):
                before = folded[max(0, m.start() - 45):m.start()]
                if label == "action cachée à l'utilisateur" and _NEG.search(before):
                    continue  # « ne fais rien sans demander à l'utilisateur » : une interdiction, pas une consigne cachée
                out.append(label)
                break
    parts = folded if code else fold(_code_parts(raw))
    for label, rx in _table("commands"):
        if rx.search(parts if label in CODE_ONLY else folded):
            out.append(label)
    return list(dict.fromkeys(out))


# ------------------------------------------------------------------------------------------ fichiers d'une skill
_PRUNED = ("node_modules", "__pycache__")


def _walk(folder, limit=WALK_MAX):
    """Parcours borné d'un dossier de skill → [(chemin relatif, genre, date, taille)] trié, ou None au-delà de `limit`
    entrées : il s'arrête alors sans lister le reste (un dossier fait pour saturer ne coûte rien). Genre : « f »
    fichier, « d » dossier parcouru, « h » dossier écarté sans être parcouru (caché, node_modules, __pycache__),
    « l » lien, « x » autre. Aucun lien n'est suivi."""
    folder = str(folder)
    out, stack, seen = [], [""], 0
    while stack:
        rel_dir = stack.pop()
        entries = []
        try:
            with os.scandir(os.path.join(folder, rel_dir) if rel_dir else folder) as it:
                for e in it:
                    seen += 1
                    if seen > limit:
                        return None
                    mtime = size = 0
                    try:
                        if e.is_symlink() or getattr(e, "is_junction", lambda: False)():
                            kind = "l"
                        elif e.is_dir(follow_symlinks=False):
                            kind = "h" if e.name[:1] in "._" or e.name in _PRUNED else "d"
                        elif e.is_file(follow_symlinks=False):
                            kind = "f"
                            st = e.stat(follow_symlinks=False)
                            mtime, size = st.st_mtime_ns, st.st_size
                        else:
                            kind = "x"
                    except OSError:
                        kind = "x"
                    entries.append((f"{rel_dir}/{e.name}" if rel_dir else e.name, kind, mtime, size))
        except OSError:
            continue
        out += entries
        stack += [row[0] for row in entries if row[1] == "d"]
    return sorted(out)


def _read_capped(path, cap) -> bytes:
    """Au plus `cap` + 1 octets d'un fichier, sans suivre un lien qui aurait pris sa place."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    with os.fdopen(fd, "rb") as fh:
        return fh.read(cap + 1)


def collect(folder, foreign=False) -> tuple:
    """Fichiers partageables d'un dossier de skill → ({chemin relatif: octets}, [scripts], [problèmes]). Texte et
    scripts seulement, sous un nom simple (SAFE_REL). Bornes vérifiées AVANT de lire (nombre d'entrées, taille de chaque
    fichier, total) : un dossier fait pour saturer s'arrête tout de suite.
    `foreign` (dossier d'un ami) : liste fermée — tout ce qui n'est pas contrôlable (lien, fichier ou dossier caché,
    autre type) est un problème, car le texte de la skill pourrait y renvoyer ; et le nom d'un fichier n'est jamais
    recopié dans un message. Sinon (mes skills) : ces fichiers-là restent simplement chez moi."""
    folder = str(folder)
    rows = _walk(folder, WALK_MAX)
    if rows is None:
        return {}, [], [f"trop de fichiers (plus de {WALK_MAX})"]
    files, scripts, problems, total, full = {}, [], [], 0, False

    def note(msg, rel):
        problems.append(msg if foreign else f"{msg} : {_show(rel)}")

    for rel, kind, _mtime, size in rows:
        if kind == "d":
            continue
        name = rel.rsplit("/", 1)[-1]
        ext = os.path.splitext(name)[1].lower()
        if kind != "f" or name[:1] == "." or ext not in TEXT_EXT + SCRIPT_EXT:
            if foreign:
                problems.append("fichier ou dossier non contrôlable (caché, lien ou autre type)")
            continue
        if not safe_rel(rel):
            note("nom de fichier à simplifier (lettres sans accent, chiffres, tirets, points ; pas un nom réservé par "
                 "Windows)", rel)
            continue
        if size > MAX_FILE:
            note(f"fichier trop gros ({size // 1000} k, {MAX_FILE // 1000} k au plus)", rel)
            continue
        if len(files) >= MAX_FILES or total + size > MAX_TOTAL:
            problems.append(f"skill trop grosse (plus de {MAX_FILES} fichiers ou de {MAX_TOTAL // 1000} k)")
            full = True
            break
        try:
            data = _read_capped(os.path.join(folder, *rel.split("/")), MAX_FILE)
        except OSError:
            if foreign:
                problems.append("fichier illisible")
            continue
        if len(data) > MAX_FILE:  # a grossi entre la mesure et la lecture
            note("fichier trop gros", rel)
            continue
        total += len(data)
        files[rel] = data
        if ext in SCRIPT_EXT:
            scripts.append(rel)
    if "SKILL.md" not in files and not full:
        problems.append("SKILL.md absent ou illisible")
    return files, scripts, list(dict.fromkeys(problems))


def public_files(files, scripts, strict=True) -> tuple:
    """Version publique des fichiers d'une skill → ({chemin: octets}, [raisons de la garder privée]). Texte : coordonnées,
    chemins du PC, liens d'accès et prénom de l'utilisateur retirés. Script : jamais réécrit — s'il en contient, la skill
    reste privée. `strict` (skill apprise, partagée d'office) : du contenu sensible la garde privée aussi."""
    from . import commun
    from .privacy import find
    out, why = {}, []
    owner = owner_name()
    name_rx = re.compile(rf"(?<![\w-]){re.escape(owner)}(?![\w-])", re.I) if len(owner) >= 3 else None
    for rel, data in files.items():
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            why.append(f"{rel} n'est pas du texte UTF-8")
            continue
        secrets = find(text)
        if secrets:
            why.append(f"secret dans {rel} ({', '.join(sorted(set(secrets)))})")
            continue
        if strict:
            cats = commun.sensitive(text)
            if cats:
                why.append(f"contenu sensible dans {rel} ({', '.join(cats)})")
                continue
        if rel in scripts:
            if commun.clean(text) != text or (name_rx and name_rx.search(text)):
                why.append(f"coordonnée, chemin du PC, lien d'accès ou prénom dans le script {rel}")
                continue
            out[rel] = data.replace(b"\r\n", b"\n")  # fins de ligne du dépôt commun (LF), comme le texte
        else:
            cleaned = commun.clean(text.replace("\ufeff", ""))  # (marque d'encodage de Windows : pas dans le dépôt)
            if name_rx:
                cleaned = name_rx.sub("l'utilisateur", cleaned)
            out[rel] = cleaned.replace("\r\n", "\n").encode("utf-8")
    return out, why


def _signature(files) -> str:
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(rel.encode("utf-8") + b"\0" + _sha(files[rel]).encode() + b"\0")
    return h.hexdigest()[:20]
