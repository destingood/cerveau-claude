"""Audit d'une skill tierce avant de l'installer (étape 18 du plan) : analyse statique de son dossier, sans rien
lancer ni suivre aucun lien → verdict « sûre », « à vérifier » ou « refusée », avec ses raisons.

Contrôles, d'après skill-security-auditor d'Alireza Rezvani (MIT,
https://github.com/alirezarezvani/claude-skills/tree/main/engineering/skills/skill-security-auditor), réécrits ici :
- texte (SKILL.md, références) : le contrôle de l'échange de skills (`echange_controle.lint_text` : consigne qui
  annule celles de l'utilisateur, action cachée, garde-fous à couper, caractères invisibles, commentaire caché, bloc
  encodé, et dans le code cité curl|bash, accès aux secrets, envoi vers l'extérieur), plus rôle détourné et
  permissions démesurées ;
- scripts : le même contrôle sur tout le fichier, puis, pour Python, une lecture de l'arbre syntaxique (eval, exec,
  shell=True, os.system, réseau, décodage base64 suivi d'une exécution, chaîne base64 qui cache du code, toutes les
  variables d'environnement lues, désérialisation non sûre, persistance) ; pour les autres langages, des motifs ;
- dossier : liens symboliques (jamais suivis), exécutables binaires (aussi sous un faux nom), archives, fichiers
  compilés, dossiers cachés, gros fichiers, scripts d'installation npm, dépendances hors des dépôts officiels.

Lancement : `skills/securite/audit-skills/scripts/auditer.py <dossier>` (skill cerveau:securite) ; aussi appelé par
`brain echange voir` sur une skill reçue d'un ami. « sûre » veut dire « aucun signal trouvé », jamais une garantie."""
from __future__ import annotations

import ast
import base64
import binascii
import json
import os
import re

from .common import fold
from .echange_controle import _read_capped, lint_text
from .skills import frontmatter

VERDICTS = ("sûre", "à vérifier", "refusée")
REFUS, VERIF, INFO = "refus", "verif", "info"
WALK_LIMIT = 3000  # entrées parcourues au plus (un dossier fait pour saturer s'arrête là)
READ_MAX = 1_000_000  # octets lus par fichier ; au-delà, le fichier est signalé et contrôlé sur ce début

PROSE_EXT = (".md", ".markdown", ".mdx", ".txt", ".rst")
DATA_EXT = (".json", ".yaml", ".yml", ".toml", ".csv", ".tsv", ".ini", ".cfg", ".xml", ".html", ".htm", ".css",
            ".svg", ".env", ".lock")
SCRIPT_EXT = (".py", ".pyw", ".sh", ".bash", ".zsh", ".fish", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".ps1",
              ".psm1", ".bat", ".cmd", ".vbs", ".rb", ".php", ".pl", ".lua", ".go", ".rs")
MEDIA_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".avif", ".pdf", ".woff", ".woff2", ".ttf",
             ".otf", ".eot", ".mp3", ".wav", ".ogg", ".mp4", ".webm", ".mov")
EXEC_EXT = (".exe", ".dll", ".so", ".dylib", ".bin", ".com", ".msi", ".scr", ".jar", ".class", ".pyc", ".pyo", ".pyd",
            ".wasm", ".node", ".apk", ".deb", ".rpm", ".dmg", ".elf", ".o", ".a")
ARCHIVE_EXT = (".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".whl", ".egg")
EXEC_MAGIC = (b"MZ", b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce",
              b"\xca\xfe\xba\xbe", b"\x00asm", b"PK\x03\x04")
QUIET_HIDDEN = {".gitignore", ".gitattributes", ".editorconfig", ".npmignore", ".prettierrc", ".prettierignore",
                ".eslintrc", ".eslintrc.json", ".python-version", ".nvmrc"}

# Raisons du contrôle de l'échange (lint_text) qui suffisent à refuser ; les autres demandent un regard humain.
# Dans un texte (SKILL.md, références), une commande citée peut être un exemple ou une mise en garde : à vérifier ; dans
# un script ou dans la description (lue par Claude à chaque session), elle refuse la skill.
LINT_REFUS_TEXT = {"consigne qui annule celles de l'utilisateur", "action cachée à l'utilisateur", "garde-fous à couper",
                   "envoi de données vers l'extérieur"}
LINT_REFUS = LINT_REFUS_TEXT | {"téléchargement exécuté directement", "accès aux secrets ou aux identifiants"}
_BIDI = re.compile("[\u202a-\u202e\u2066-\u2069]")  # texte qui s'affiche dans un autre ordre que celui lu (Trojan Source)
_NEG = re.compile(r"\b(?:ne|n'|jamais|aucun|aucune|rien|pas|never|not|don't|do not|no)\b")
_PROSE_SRC = (  # texte replié : minuscules, sans accents
    (REFUS, "rôle détourné (« tu n'as aucune restriction »)",
     r"(?:pretend|act as if|imagine) (?:that )?you have no (?:restrictions?|limits?|rules?)|you have no restrictions|"
     r"tu n'as (?:plus )?aucune (?:restriction|limite|regle)|fais comme si tu n'avais (?:aucune|pas de) (?:restriction|"
     r"limite|regle)|act as (?:root|an? unrestricted)|\bjailbreak\b"),
    (VERIF, "permissions démesurées demandées",
     r"run any command|execute any command|full (?:filesystem|disk|system) access|acces complet (?:au disque|aux "
     r"fichiers|au systeme|a l'ordinateur)|n'importe quelle commande"),
    (REFUS, "envoi de fichiers, de clés ou de mots de passe demandé",
     r"(?:send|upload|post|exfiltrate|envoie|televerse|transmets|copie)[a-z]{0,4} (?:moi |me )?(?:tout |all )?"
     r"(?:le contenu de|the contents? of|tous les fichiers|all (?:the )?files|les cles|the keys|les mots de passe|"
     r"(?:the )?passwords|les identifiants|(?:the )?credentials)"),
)
_PROSE = [(lvl, label, re.compile(rx)) for lvl, label, rx in _PROSE_SRC]

# Scripts hors Python : motifs (texte replié), toujours « à vérifier ».
_OTHER_SRC = (
    ("exécution de code dynamique (eval, new Function)", r"\beval\s*[(\s]|new\s+function\s*\("),
    ("commande shell lancée par le script", r"child_process|\bexecsync\b|\bspawnsync\b|start-process|\bshell_exec\b|"
                                            r"\bpassthru\b|\bsystem\s*\(|\bpopen\s*\("),
    ("accès réseau", r"\bfetch\s*\(|xmlhttprequest|https?\.request\s*\(|\baxios\b|\bcurl\s|\bwget\s|invoke-webrequest|"
                     r"invoke-restmethod|net\.webclient|\bnc\s"),
    ("décodage de données cachées (base64)", r"\batob\s*\(|base64\s+(?:-d|--decode)|frombase64string|"
                                            r"buffer\.from\([^)]{0,200}base64"),
    ("droits élevés (sudo, setuid, chmod 777)", r"\bsudo\s|chmod\s+(?:[0-7]?777|\+s|u\+s)|\bsetuid\b|runas\s"),
)
_OTHER = [(label, re.compile(rx)) for label, rx in _OTHER_SRC]
_PERSIST = re.compile(r"\.bashrc|\.bash_profile|\.zshrc|(?<![\w.])\.profile\b|crontab|launchagents|launchdaemons|"
                      r"/etc/(?:passwd|shadow|sudoers|cron|systemd|profile)|currentversion\\\\?run|schtasks|"
                      r"start menu\\\\?programs\\\\?startup|systemctl\s+enable")
_INSTALL = re.compile(r"\b(?:pip3?|npm|pnpm|yarn|gem|cargo)\s+(?:install|add|i)\b")
_B64_STR = re.compile(r"['\"]([A-Za-z0-9+/]{40,}={0,2})['\"]")
_HIDDEN_CODE = re.compile(r"\b(?:import|exec|eval|subprocess|os\.system|/bin/(?:ba)?sh|powershell|curl|wget|https?://|"
                          r"socket|require\(|child_process)")

NET_MODULES = {"socket", "urllib", "http", "requests", "httpx", "aiohttp", "ftplib", "smtplib", "telnetlib",
               "paramiko", "websocket", "websockets", "urllib3", "pycurl", "xmlrpc"}
SHELL_CALLS = {"os.system", "os.popen", "os.execv", "os.execve", "os.execl", "os.execlp", "os.execvp", "os.spawnl",
               "os.spawnv", "os.startfile", "pty.spawn", "commands.getoutput"}
DECODE_CALLS = {"base64.b64decode", "base64.b32decode", "base64.b85decode", "base64.a85decode", "base64.decodebytes",
                "base64.urlsafe_b64decode", "codecs.decode", "bytes.fromhex", "binascii.unhexlify", "zlib.decompress",
                "binascii.a2b_base64"}
UNSAFE_LOADS = {"pickle.loads", "pickle.load", "marshal.loads", "marshal.load", "shelve.open", "dill.loads"}


def _finding(level, rel, reason, line=0) -> dict:
    return {"niveau": level, "fichier": rel, "ligne": line, "raison": reason}


def _lint(text, rel, code, out) -> None:
    """Le contrôle de l'échange (lint_text), raison par raison, avec la première ligne en cause si on la trouve."""
    labels = lint_text(text, code=code)
    if not labels:
        return
    lines = text.splitlines()[:5000]
    for label in labels:
        line = 0
        for i, ln in enumerate(lines, 1):
            if label in lint_text(ln, code=True) or (not code and label in lint_text(ln)):
                line = i
                break
        if label == "caractères invisibles" and _BIDI.search(text):
            label = "caractères qui inversent le sens d'affichage (Trojan Source) : à lire dans un éditeur qui les montre"
        out.append(_finding(REFUS if label in (LINT_REFUS if code else LINT_REFUS_TEXT) else VERIF, rel, label, line))


def _prose(text, rel, out) -> None:
    folded = fold(text)
    for level, label, rx in _PROSE:
        for m in rx.finditer(folded):
            if _NEG.search(folded[max(0, m.start() - 45):m.start()]):
                continue  # « ne demande jamais tous les fichiers » : une interdiction, pas une demande
            out.append(_finding(level, rel, label, folded.count("\n", 0, m.start()) + 1))
            break


def _b64_hides_code(s) -> bool:
    """Une chaîne base64 qui, décodée, est du texte où se lit du code ou une commande."""
    try:
        raw = base64.b64decode(s + "=" * (-len(s) % 4), validate=True)
        text = raw.decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return False
    printable = sum(c.isprintable() or c in "\n\r\t" for c in text)
    return printable >= 0.9 * max(1, len(text)) and bool(_HIDDEN_CODE.search(text.lower()) or lint_text(text, code=True))


class _Py(ast.NodeVisitor):
    """Lecture d'un script Python : appels et imports qui méritent un regard (rien n'est exécuté)."""

    def __init__(self):
        self.alias, self.hits, self.decode, self.run, self.chr = {}, [], 0, 0, 0
        self.parents = {}

    def name(self, node) -> str:
        """Nom complet d'une expression `a.b.c`, alias d'import remplacés (`from os import system as s` : s → os.system)."""
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return ""
        parts.append(self.alias.get(node.id, node.id))
        return ".".join(reversed(parts))

    def hit(self, level, reason, node):
        self.hits.append((level, reason, getattr(node, "lineno", 0)))

    def visit_Import(self, node):
        for a in node.names:
            self.alias[(a.asname or a.name).split(".")[0]] = a.asname and a.name or a.name.split(".")[0]
            self._module(a.name, node)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        mod = node.module or ""
        for a in node.names:
            self.alias[a.asname or a.name] = f"{mod}.{a.name}" if mod else a.name
        self._module(mod, node)
        self.generic_visit(node)

    def _module(self, mod, node):
        top = mod.split(".")[0]
        if top in NET_MODULES:
            self.hit(VERIF, f"accès réseau (module {top})", node)
        elif top == "ctypes":
            self.hit(VERIF, "appels directs au système (ctypes)", node)

    def visit_Call(self, node):
        full = self.name(node.func)
        short = full.rsplit(".", 1)[-1]
        if full in ("eval", "exec"):
            self.run += 1
            self.hit(REFUS if self._dynamic(node) else VERIF, f"exécution de code dynamique ({full})", node)
        elif full in ("compile", "__import__", "importlib.import_module"):
            self.hit(VERIF, f"chargement de code dynamique ({full})", node)
        elif full in SHELL_CALLS:
            self.hit(VERIF, f"commande shell lancée par le script ({full})", node)
        elif full.startswith("subprocess."):
            shell = any(k.arg == "shell" and not (isinstance(k.value, ast.Constant) and not k.value.value)
                        for k in node.keywords)
            if shell:
                self.hit(VERIF, f"commande shell lancée par le script ({full}, shell=True)", node)
            else:
                self.hit(INFO, f"programme lancé par le script ({full}, sans shell)", node)
        elif full in DECODE_CALLS:  # courant (images, fichiers compressés) : grave seulement suivi d'un exec ou d'un eval
            self.decode += 1
            self.hit(INFO, f"décodage de données ({full})", node)
        elif full in UNSAFE_LOADS or (full == "yaml.load" and not any(k.arg == "Loader" for k in node.keywords)):
            self.hit(VERIF, f"désérialisation non sûre ({full})", node)
        elif short in ("chmod", "setuid", "seteuid") and full.startswith("os."):
            self.hit(VERIF, f"droits de fichiers ou d'utilisateur changés ({full})", node)
        elif full == "chr":
            self.chr += 1
        self.generic_visit(node)

    @staticmethod
    def _dynamic(node) -> bool:
        """eval/exec d'autre chose qu'un texte écrit en dur dans le script."""
        return not (node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str))

    def visit_Attribute(self, node):
        if self.name(node) == "os.environ":
            parent = self.parents.get(node)
            ok = (isinstance(parent, ast.Subscript) and parent.value is node) or (
                isinstance(parent, ast.Attribute) and parent.attr in ("get", "setdefault", "pop")) or (
                isinstance(parent, ast.Compare) and node in parent.comparators)
            if not ok:
                self.hit(VERIF, "lit toutes les variables d'environnement (os.environ en entier)", node)
        self.generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, str) and len(node.value) >= 8:
            s = node.value
            if len(s) >= 40 and re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", s) and _b64_hides_code(s):
                self.hit(REFUS, "chaîne base64 qui cache du code ou une commande", node)
            low = s.lower()
            if _PERSIST.search(low):
                self.hit(VERIF, "touche au démarrage ou à la configuration du système (persistance)", node)
            if _INSTALL.search(low):
                self.hit(VERIF, "installe des paquets pendant qu'il tourne", node)


def _python(text, rel, out) -> None:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        out.append(_finding(VERIF, rel, "script Python illisible (erreur de syntaxe) : rien n'a pu être contrôlé"))
        return
    v = _Py()
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            v.parents[child] = parent
    try:
        v.visit(tree)
    except RecursionError:
        out.append(_finding(VERIF, rel, "script Python trop imbriqué pour être lu en entier"))
    if v.decode and v.run:
        out.append(_finding(REFUS, rel, "données décodées puis exécutées (code caché)"))
    if v.chr >= 10:
        out.append(_finding(VERIF, rel, f"texte assemblé caractère par caractère ({v.chr} appels à chr)"))
    seen = set()
    for level, reason, line in v.hits:
        if (level, reason) not in seen:  # une fois par raison et par fichier : la première ligne suffit
            seen.add((level, reason))
            out.append(_finding(level, rel, reason, line))


def _other_script(text, rel, out) -> None:
    folded = fold(text)
    for label, rx in _OTHER:
        m = rx.search(folded)
        if m:
            out.append(_finding(VERIF, rel, label, folded.count("\n", 0, m.start()) + 1))
    for rx, label in ((_PERSIST, "touche au démarrage ou à la configuration du système (persistance)"),
                      (_INSTALL, "installe des paquets pendant qu'il tourne")):
        m = rx.search(folded)
        if m:
            out.append(_finding(VERIF, rel, label, folded.count("\n", 0, m.start()) + 1))
    for m in _B64_STR.finditer(text):
        if _b64_hides_code(m.group(1)):
            out.append(_finding(REFUS, rel, "chaîne base64 qui cache du code ou une commande",
                                text.count("\n", 0, m.start()) + 1))
            break


def _skill_md(text, rel, out) -> None:
    meta, _body = frontmatter(text)
    if not meta.get("name") or not meta.get("description"):
        out.append(_finding(VERIF, rel, "en-tête incomplet (name ou description absent)"))
    desc = " ".join(str(meta.get("description") or "").split())
    if desc:  # la description est lue par Claude à chaque session : contrôlée sans indulgence, comme dans l'échange
        for label in dict.fromkeys(lint_text(desc, code=True) + lint_text(desc)):
            out.append(_finding(REFUS if label in LINT_REFUS else VERIF, rel, f"{label} (description)"))
    tools = str(meta.get("allowed-tools") or "")
    if re.search(r"\bBash\b(?!\()|Bash\(\s*\*\s*\)", tools):
        out.append(_finding(VERIF, rel, "toutes les commandes Bash permises sans demander (allowed-tools)"))
    if any(k == "hooks" or k.startswith("hooks.") for k in meta):
        out.append(_finding(VERIF, rel, "la skill déclare des hooks (commandes lancées toutes seules)"))


def _deps(name, text, rel, out) -> None:
    if name == "package.json":
        try:
            scripts = (json.loads(text) or {}).get("scripts") or {}
        except (ValueError, AttributeError):
            scripts = {}
        hooks = sorted(k for k in scripts if k in ("preinstall", "install", "postinstall", "prepare"))
        if hooks:
            out.append(_finding(VERIF, rel, f"script lancé à l'installation npm ({', '.join(hooks)})"))
    elif name.startswith("requirements") or name in ("pyproject.toml", "setup.cfg", "Pipfile"):
        for i, ln in enumerate(text.splitlines(), 1):
            if re.search(r"git\+|https?://|--(?:extra-)?index-url|--trusted-host", ln):
                out.append(_finding(VERIF, rel, "dépendance prise hors du dépôt officiel (PyPI)", i))
                break
    if name == "setup.py":
        out.append(_finding(VERIF, rel, "setup.py : du code lancé à l'installation"))


def _file(folder, rel, size, out) -> tuple:
    """Un fichier du dossier → (script ?, contrôlé ?)."""
    name = rel.rsplit("/", 1)[-1]
    ext = os.path.splitext(name)[1].lower()
    if name[:1] == "." and name not in QUIET_HIDDEN:
        out.append(_finding(VERIF, rel, "fichier caché (.env, réglages…) : à ouvrir avant d'installer"))
    if size > READ_MAX:
        out.append(_finding(VERIF, rel, f"gros fichier ({size // 1_000_000} Mo) : seul le début est contrôlé"))
    try:
        data = _read_capped(os.path.join(folder, *rel.split("/")), READ_MAX)[:READ_MAX]
    except OSError:
        out.append(_finding(VERIF, rel, "fichier illisible"))
        return False, False
    binary = b"\0" in data[:8192]
    if ext in EXEC_EXT or (binary and data.startswith(EXEC_MAGIC[:-1])):
        out.append(_finding(REFUS, rel, "exécutable ou code compilé, illisible par un humain"))
        return False, True
    if ext in ARCHIVE_EXT or (binary and data.startswith(EXEC_MAGIC[-1])):
        out.append(_finding(VERIF, rel, "archive : son contenu n'est pas contrôlé"))
        return False, True
    if ext in MEDIA_EXT:
        return False, True
    if binary:
        out.append(_finding(VERIF, rel, "fichier binaire d'un type inconnu"))
        return False, True
    text = data.decode("utf-8", "replace")
    script = ext in SCRIPT_EXT or (not ext and text.startswith("#!"))
    if script:
        _lint(text, rel, True, out)
        (_python if ext in (".py", ".pyw") or "python" in text[:80] else _other_script)(text, rel, out)
    else:
        _lint(text, rel, False, out)
        if ext in PROSE_EXT or ext not in DATA_EXT:
            _prose(text, rel, out)
        if ext in (".svg", ".html", ".htm") and re.search(r"<script\b|\bon(?:load|error|click)\s*=", text, re.I):
            out.append(_finding(VERIF, rel, "du JavaScript dans une image ou une page"))
        _deps(name, text, rel, out)
    if name == "SKILL.md":
        _skill_md(text, rel, out)
    return script, True


PRUNED = {"node_modules": "dépendances embarquées (node_modules) non contrôlées",
          "__pycache__": "fichiers Python compilés (__pycache__), qui peuvent différer du code lisible"}
SKIPPED = {".git"}  # historique git : pas lu (ce qui compte est dans les fichiers de la skill)


def _tree(folder, limit=WALK_LIMIT):
    """Parcours borné → [(chemin relatif, genre, taille)] trié, ou None au-delà de `limit` entrées. Genre : « f »
    fichier, « d » dossier parcouru, « p » dossier écarté (historique git, node_modules, __pycache__), « l » lien
    (jamais suivi), « x » autre. Contrairement au parcours de l'échange, les dossiers cachés sont lus : rien ne s'y
    cache."""
    out, stack, seen = [], [""], 0
    while stack:
        rel_dir = stack.pop()
        try:
            with os.scandir(os.path.join(folder, *rel_dir.split("/")) if rel_dir else folder) as it:
                entries = list(it)
        except OSError:
            continue
        for e in entries:
            seen += 1
            if seen > limit:
                return None
            rel = f"{rel_dir}/{e.name}" if rel_dir else e.name
            size = 0
            try:
                if e.is_symlink() or getattr(e, "is_junction", lambda: False)():
                    kind = "l"
                elif e.is_dir(follow_symlinks=False):
                    kind = "p" if e.name in PRUNED or e.name in SKIPPED else "d"
                elif e.is_file(follow_symlinks=False):
                    kind, size = "f", e.stat(follow_symlinks=False).st_size
                else:
                    kind = "x"
            except OSError:
                kind = "x"
            out.append((rel, kind, size))
            if kind == "d":
                stack.append(rel)
    return sorted(out)


def audit(folder) -> dict:
    """Dossier d'une skill → {"skill", "dossier", "verdict", "fichiers", "scripts", "constats": [{niveau, fichier,
    ligne, raison}]}. Rien n'est exécuté, aucun lien n'est suivi, chaque lecture est bornée."""
    folder = os.path.abspath(str(folder))
    if os.path.isfile(folder) and os.path.basename(folder) == "SKILL.md":
        folder = os.path.dirname(folder)
    out, n_files, n_scripts = [], 0, 0
    if not os.path.isdir(folder) or os.path.islink(folder):
        out.append(_finding(REFUS, "", "dossier introuvable (ou lien) : rien à auditer"))
        return _result(folder, out, 0, 0)
    rows = _tree(folder)
    if rows is None:
        out.append(_finding(VERIF, "", f"plus de {WALK_LIMIT} fichiers et dossiers : audit arrêté, à relire à la main"))
        return _result(folder, out, 0, 0)
    if "SKILL.md" not in {r[0] for r in rows}:
        out.append(_finding(VERIF, "", "pas de SKILL.md à la racine : est-ce bien le dossier d'une skill ?"))
    for rel, kind, size in rows:
        base = rel.rsplit("/", 1)[-1]
        if kind == "l":
            try:
                target = os.readlink(os.path.join(folder, *rel.split("/")))
            except OSError:
                target = "/"
            inside = os.path.normpath(os.path.join(folder, os.path.dirname(rel), target))
            try:
                outside = os.path.isabs(target) or os.path.commonpath([inside, folder]) != folder
            except ValueError:  # autre lecteur sous Windows
                outside = True
            out.append(_finding(REFUS if outside else VERIF, rel, "lien symbolique vers l'extérieur de la skill"
                                if outside else "lien symbolique (jamais suivi par l'audit)"))
        elif kind == "p":
            if base in PRUNED:
                out.append(_finding(VERIF, rel, PRUNED[base]))
        elif kind == "d":
            if base[:1] == ".":
                out.append(_finding(VERIF, rel, "dossier caché (lu quand même) : à ouvrir avant d'installer"))
        elif kind == "x":
            out.append(_finding(VERIF, rel, "fichier spécial (ni fichier ni dossier)"))
        else:
            script, read = _file(folder, rel, size, out)
            n_files += read
            n_scripts += script
    return _result(folder, out, n_files, n_scripts)


def _result(folder, found, n_files, n_scripts) -> dict:
    levels = {f["niveau"] for f in found}
    verdict = VERDICTS[2] if REFUS in levels else VERDICTS[1] if VERIF in levels else VERDICTS[0]
    order = {REFUS: 0, VERIF: 1, INFO: 2}
    found.sort(key=lambda f: (order[f["niveau"]], f["fichier"], f["ligne"]))
    return {"skill": os.path.basename(folder.rstrip("/\\")), "dossier": folder, "verdict": verdict,
            "fichiers": n_files, "scripts": n_scripts, "constats": found}


ICON = {VERDICTS[0]: "✅", VERDICTS[1]: "⚠️", VERDICTS[2]: "❌"}
MARK = {REFUS: "❌", VERIF: "⚠️", INFO: "·"}


def report(res, infos=False) -> str:
    """Compte rendu lisible ; `infos` : aussi les constats sans gravité (programme lancé sans shell…)."""
    L = [f"🔎 Audit de la skill « {res['skill']} » ({res['fichiers']} fichier(s), dont {res['scripts']} script(s)) : "
         f"{ICON[res['verdict']]} {res['verdict']}"]
    shown = [f for f in res["constats"] if infos or f["niveau"] != INFO]
    for f in shown:
        where = f["fichier"] + (f":{f['ligne']}" if f["ligne"] else "")
        L.append(f"  {MARK[f['niveau']]} {where + ' — ' if where else ''}{f['raison']}")
    hidden = len(res["constats"]) - len(shown)
    if hidden:
        L.append(f"  · {hidden} constat(s) sans gravité (--infos pour les voir)")
    L.append({VERDICTS[0]: "→ Aucun signal trouvé par l'analyse statique : ce n'est pas une garantie, lis quand même "
                           "SKILL.md avant d'installer.",
              VERDICTS[1]: "→ À lire avant d'installer : ouvre chaque fichier signalé et vérifie ce qu'il fait.",
              VERDICTS[2]: "→ Ne pas installer telle quelle : demande à l'auteur, ou retire ce qui est signalé."}
             [res["verdict"]])
    return "\n".join(L)


def summary_line(res) -> str:
    """Une ligne, sans aucun nom de fichier ni texte de la skill (affichable pour une skill reçue d'un ami)."""
    reasons = list(dict.fromkeys(re.sub(r" \([^)]*\)$", "", f["raison"]) for f in res["constats"]
                                 if f["niveau"] != INFO))
    more = f" (+{len(reasons) - 4})" if len(reasons) > 4 else ""
    return (f"audit : {ICON[res['verdict']]} {res['verdict']}"
            + (f" — {', '.join(reasons[:4])}{more}" if reasons else ""))
