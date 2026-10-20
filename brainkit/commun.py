"""Le cerveau commun : ce que chacun apprend nourrit le cerveau de tous, presque en temps réel, sans jamais livrer sa
vie privée.

Un dépôt GitHub privé dont les amis sont membres. Le cerveau de chacun y publie sa part publique dans SON dossier
(`membres/<nom>/`, même format que le wiki : une page par souvenir) et lit celle des autres, en lecture seule (ids
`c--<nom>--<id>` dans le graphe, marqués 🤝). Personne n'écrit chez un autre : pas de conflit git, et rien de ce qui est
à moi ne peut fusionner dans la page d'un ami.

Ne part JAMAIS : profil et règles, contenu sensible (santé, argent, intimité, identité, opinions, accès), une page qui a
contenu un secret, les personnes (données de tiers), les documents personnels (source sans adresse web publique) et ce
qui n'est tiré que d'eux, les références (outils et comptes de chacun), le domaine « perso », les projets non partagés,
ce qui est marqué privé, le texte des sessions. Retirés du reste : coordonnées, secrets, chemins de fichiers du PC,
liens qui donnent un accès (document partagé, invitation, réunion, réseau local) ; un lien vers une page privée devient
« [privé] » ; un identifiant qui garde un ancien titre est remplacé par une empreinte.
Part : le savoir (sources web, recherches, concepts, sujets, analyses, entités qui ne sont pas des personnes,
apprentissages), tout ce qui appartient à un projet déclaré commun (tâches, décisions, faits, observations datées), et
ce qui est marqué partagé.

Rien ne part avant l'accord de chacun (`brain commun rejoindre --oui`). Ensuite, un ajout part en arrière-plan une
quinzaine de secondes après (regroupé avec les suivants ; une correction faite entre-temps part à sa place), et les pages
des amis sont récupérées au démarrage, à chaque message et en fin de tour (au plus une fois par minute ; après une pause,
le message attend quelques secondes la récupération)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .common import (BRAIN_DIR, BRAIN_PY, CODE_DIR, STATE_DIR, FileLock, fmt_date, fold, load_config, log, now_iso,
                     read_json, set_config, short, slugify, write_json, write_text)

FOREIGN = "c--"  # préfixe des pages des amis dans le graphe : lecture seule, jamais réécrites ni exportées
MARKER = ".cerveau-commun"
MEMBERS = "membres"
STATE_FILE = STATE_DIR / "commun.json"
EXPORT_CACHE = STATE_DIR / "commun-export.json"
EXPORT_PAGES = STATE_DIR / "commun-export-pages.json"
GIT_LOCK = STATE_DIR / "commun-git.lock"
STATE_LOCK = STATE_DIR / "commun-state.lock"
PULL_EVERY = 60  # s : récupération des pages des amis au plus une fois par minute (messages, fins de tour)
FRESH = 60  # s : dernière récupération plus vieille → le message attend la nouvelle (≤ 2,5 s) : chaque message voit ce
# que les amis ont envoyé plus d'une minute avant lui
DELAY = 15.0  # s : envoi différé après un ajout (regroupe les ajouts, laisse le temps de corriger ou de garder privé)
KNOWLEDGE = ("source", "concept", "topic", "analysis", "entity", "learning")  # pas « reference » : outils et comptes
NEVER = ("user", "feedback")
PERSONAL_DOMAINS = {"perso", "personnel", "prive", "vie-privee", "sante", "famille", "finances"}
SAFE_META = ("resume", "domaine", "sources", "due", "done", "keys", "stack", "format", "url", "auteur", "date_source",
             "alias")
PERSON_TAGS = {"personne", "personnes", "contact", "contacts", "client", "clients", "ami", "amis", "famille", "proche"}
# une entité ne part que si elle n'est visiblement pas une personne : tirée d'une source publique, ou étiquetée comme
# une organisation, un outil, un lieu, une œuvre…
THING_TAGS = {"entreprise", "entreprises", "societe", "marque", "marques", "outil", "outils", "logiciel", "produit",
              "produits", "service", "plateforme", "app", "application", "site", "lieu", "ville", "pays", "region",
              "organisation", "association", "techno", "technologie", "bibliotheque", "library", "framework", "langage",
              "api", "modele", "livre", "film", "media", "concurrent", "concurrents"}
SOURCE_LABELS = {"utilisateur", "verifie", "obsidian", "wiki", "claude", "mcp", "import", "auto", "deduit", "inference"}
# Catégories sensibles, sur le texte replié (minuscules, sans accents). Les tournures personnelles (« mon médecin »,
# « ma banque ») plutôt que les mots seuls : « rupture de stock », « livraison à domicile » ou « bienfaits pour la
# santé » sont du savoir à partager. Dans le doute, une page reste privée.
SENSITIVE = {
    "santé": r"(?:mon|ma|mes) (?:sante|medecin|docteur|maladie|traitement|medicaments?|psy|psychologue|psychiatre|"
             r"therapeute|therapie|diagnostic|ordonnance|operation|allergie|handicap|symptomes?)|arret maladie|"
             r"ordonnance medicale|dossier medical|hopital|urgences|depression|anxiete|crise d'angoisse|enceinte|"
             r"grossesse|cancer|diabete|my (?:health|doctor|illness|medication|therapy)",
    "argent personnel": r"(?:mon|ma|mes) (?:salaire|revenus?|dettes?|banque|compte bancaire|comptes|epargne|credit|"
                        r"pret|emprunt|patrimoine|impots|loyer|budget|depenses|finances|fiches? de paie|"
                        r"bulletins? de (?:paie|salaire))|compte bancaire|iban|rib|carte bancaire|numero de carte|"
                        r"code secret|livret a|avis d'imposition|impots? sur le revenu|my (?:salary|bank account)",
    "intimité": r"(?:ma|mon) (?:copine|copain|femme|mari|epouse|epoux|couple|fille|fils|mere|pere|famille|soeur|frere)|"
                r"petite amie|petit ami|mes enfants|mes parents|divorce|sexe|sexuel|sexuelle|"
                r"my (?:wife|husband|girlfriend|boyfriend)",
    "identité": r"adresse postale|mon adresse|j'habite|securite sociale|numero de secu|passeport|carte d'identite|"
                r"permis de conduire|date de naissance|social security|passport",
    "opinions": r"religion|religieux|religieuse|parti politique|opinion politique|syndicat|je vote|vote pour",
    "accès": r"mot de passe|mots de passe|password|code pin|code d'acces|\"[^\"\n]{0,40} masque\"",
}
SENSITIVE_RX = {k: re.compile(rf"(?<![a-z0-9])(?:{v})(?![a-z0-9])") for k, v in SENSITIVE.items()}
# chemins de fichiers du PC (pas une adresse web : « site.com/home/… » reste intact)
PATH_RX = re.compile(r"(?<![\w/])(?:[A-Za-z]:[\\/]|\\\\[\w.-]+\\)[^\s\"'<>|`]*|(?<![\w.:/])(?:/home/|/Users/|/root/)"
                     r"[^\s\"'<>`]*")
URL_RX = re.compile(r"(?i)\b(?:https?|ftp|file|smb)://[^\s<>\"'`\]\)]+")
# adresses qui donnent un accès (document partagé, invitation, réunion, contact direct) ou ne mènent qu'à un PC ou un
# réseau local : jamais publiées
PRIVATE_HOSTS = re.compile(
    r"(?:^|\.)(?:docs\.google\.com|drive\.google\.com|mail\.google\.com|calendar\.google\.com|meet\.google\.com|"
    r"photos\.google\.com|photos\.app\.goo\.gl|forms\.gle|dropbox\.com|dropboxusercontent\.com|onedrive\.live\.com|"
    r"1drv\.ms|sharepoint\.com|icloud\.com|box\.com|wetransfer\.com|we\.tl|notion\.so|figma\.com|airtable\.com|"
    r"trello\.com|miro\.com|canva\.com|loom\.com|zoom\.us|teams\.microsoft\.com|teams\.live\.com|whereby\.com|"
    r"discord\.gg|chat\.whatsapp\.com|wa\.me|t\.me|telegram\.me|slack\.com|calendly\.com|"
    r"localhost|local|lan|internal|intranet|home|corp)$")
PRIVATE_QUERY = re.compile(r"(?i)[?&#;](?:[\w.-]*(?:token|key|sig|signature|secret|auth|password|pwd|session|code|"
                           r"access|credential|invite)[\w.-]*|x-amz-[\w-]+|expires)=")
WIKI_LINK = re.compile(r"\[\[([^\]\n|#]{1,160})(#[^\]\n|]*)?(?:\|([^\]\n]{1,160}))?\]\]")


# ------------------------------------------------------------------------------------------ réglages et état
def settings() -> dict:
    """Réglages du cerveau commun (config « commun »), avec l'adresse par défaut livrée avec le plugin."""
    c = dict(load_config().get("commun") or {})
    if not c.get("repo"):
        c["repo"] = (read_json(CODE_DIR / "brainkit" / "commun.json", {}) or {}).get("repo")
    c.setdefault("path", str(BRAIN_DIR / "commun"))
    return c


def member() -> str:
    """Nom de membre si ce cerveau a rejoint le cerveau commun (et que le dossier est là), sinon "".
    Appelé à chaque chargement du cerveau : une seule lecture de config.json pour qui n'est pas membre."""
    if os.environ.get("CLAUDE_CODE_REMOTE"):
        return ""
    c = load_config().get("commun") or {}
    if c.get("etat") != "membre" or not c.get("nom"):
        return ""
    if not (Path(c.get("path") or BRAIN_DIR / "commun") / ".git").exists():
        return ""
    return c["nom"]


def state() -> dict:
    return read_json(STATE_FILE, {}) or {}


def save_state(**kw):
    """Mise à jour de l'état sous verrou : hooks et synchronisations en arrière-plan l'écrivent en même temps."""
    try:
        with FileLock(STATE_LOCK, timeout=2, stale=20):
            st = state()
            st.update(kw)
            write_json(STATE_FILE, st)
    except TimeoutError:
        st = state()
        st.update(kw)
        write_json(STATE_FILE, st)


def repo_url(repo) -> str:
    r = str(repo or "").strip()
    if not r:
        return ""
    if "://" in r or r.startswith(("/", ".", "~", "git@")) or re.match(r"^[A-Za-z]:[\\/]", r):
        return os.path.expanduser(r)
    return f"https://github.com/{r.removesuffix('.git')}.git"


def is_foreign(nid) -> bool:
    return str(nid or "").startswith(FOREIGN)


def author(node) -> str:
    return (node.get("meta") or {}).get("commun_par") or ""


# ------------------------------------------------------------------------------------------ vie privée
def sensitive(text) -> list:
    """Catégories sensibles repérées dans un texte (santé, argent, intimité, identité, opinions, accès)."""
    t = fold(text)
    return [k for k, rx in SENSITIVE_RX.items() if rx.search(t)]


def shared_projects(nodes) -> set:
    return {n["id"] for n in nodes.values() if n["type"] == "project" and (n.get("meta") or {}).get("partage")
            and n.get("status", "active") == "active"}


def _as_list(v) -> list:
    return [str(x) for x in v if str(x).strip()] if isinstance(v, (list, tuple)) else ([str(v)] if str(v or "").strip() else [])


def private_url(url) -> bool:
    """Adresse à ne jamais publier : document partagé, invitation, réunion, contact direct, fichier ou réseau local,
    identifiants ou jeton dans l'adresse."""
    from urllib.parse import urlsplit
    try:
        u = urlsplit(str(url).strip())
        host = (u.hostname or "").lower().rstrip(".")
        userinfo = u.username or u.password
    except ValueError:
        return True
    if u.scheme.lower() not in ("http", "https") or not host or userinfo or "." not in host:
        return True
    if re.fullmatch(r"[\d.]+|\[?[0-9a-f:]+\]?", host) or PRIVATE_HOSTS.search(host):
        return True
    return bool(re.search(r"(?i)/(?:invite|join|j)/", u.path) or PRIVATE_QUERY.search(str(url)))


def public_url(url) -> bool:
    return bool(url) and URL_RX.fullmatch(str(url).strip()) is not None and not private_url(url)


def verdict(node, projects) -> tuple:
    """Ce souvenir peut-il partir dans le cerveau commun ? → (oui ?, raison). Dans le doute : non."""
    from .privacy import find as find_secrets
    meta = node.get("meta") or {}
    t = node["type"]
    if is_foreign(node["id"]):
        return False, "page d'un ami"
    if node.get("status", "active") != "active":
        return False, "archivé"
    if t in NEVER:
        return False, "profil et règles restent privés"
    if meta.get("prive"):
        return False, "marqué privé"
    tags = {fold(x) for x in _as_list(node.get("tags"))}
    text = "\n".join(str(x) for x in [node.get("title") or "", node.get("body") or "", meta.get("url") or "",
                                      *_as_list(meta.get("keys")), *_as_list(meta.get("resume")),
                                      *_as_list(meta.get("alias")), *_as_list(meta.get("auteur")), *tags])
    if find_secrets(text):
        return False, "secret"
    shared = bool(meta.get("partage"))
    cats = sensitive(text)
    if cats and not shared:
        return False, "sensible (" + ", ".join(cats) + ")"
    if PERSONAL_DOMAINS & {slugify(x, 30) for x in _as_list(meta.get("domaine"))} and not shared:
        return False, "domaine perso"
    if t == "entity" and not shared:
        if PERSON_TAGS & tags:
            return False, "une personne (donnée de tiers)"
        if not THING_TAGS & tags and not _as_list(meta.get("sources")):
            return False, "entité sans source publique (peut-être une personne)"
    if shared:
        return True, "marqué partagé"
    if t == "project":
        return False, "projet privé (`brain commun projet <id>` pour le partager)"
    if node.get("project"):
        return (True, "projet commun") if node["project"] in projects else (False, "projet privé")
    if t == "source" and not public_url(meta.get("url")):
        return False, "document personnel (pas d'adresse web publique)"
    if t in KNOWLEDGE:
        return True, "savoir"
    return False, "personnel (hors projet commun)"


def _ref(brain, s):
    m = WIKI_LINK.search(str(s))
    return brain.get(m.group(1).strip()) if m else brain.get(str(s))


def judge(brain) -> dict:
    """{id: (part ?, raison)} pour chacun de mes souvenirs actifs. Une page qui ne s'appuie que sur des documents
    privés reste privée : son contenu vient d'eux."""
    projects = shared_projects(brain.nodes)
    out = {nid: verdict(n, projects) for nid, n in brain.nodes.items()
           if not is_foreign(nid) and n.get("status", "active") == "active"}
    for _ in range(5):
        changed = False
        for nid, (ok, _why) in list(out.items()):
            meta = brain.nodes[nid].get("meta") or {}
            if not ok or meta.get("partage"):
                continue
            srcs = [r for r in (_ref(brain, x) for x in _as_list(meta.get("sources"))) if r is not None and r["id"] != nid]
            if srcs and not any(is_foreign(r["id"]) or out.get(r["id"], (False,))[0] for r in srcs):
                out[nid] = (False, "tiré de documents privés")
                changed = True
        if not changed:
            break
    return out


def clean(text) -> str:
    """Texte public : liens qui donnent un accès retirés, secrets masqués, coordonnées retirées, chemins de fichiers
    du PC effacés."""
    from .privacy import redact_contacts
    def url(m):
        u = m.group(0).rstrip(".,;:!?")
        return ("[lien privé]" if private_url(u) else u) + m.group(0)[len(u):]

    return PATH_RX.sub("[chemin]", redact_contacts(URL_RX.sub(url, str(text or ""))))


def _clean_any(v):
    return clean(v) if isinstance(v, str) else [clean(str(x)) for x in v] if isinstance(v, (list, tuple)) else v


def public_id(node) -> str:
    """Id publié : celui du souvenir s'il ne dit rien de plus que le titre public ; sinon une empreinte (un id garde le
    titre d'origine : renommé depuis, ou qui contenait une coordonnée)."""
    nid = str(node["id"])
    words = set(slugify(clean(node.get("title") or ""), 400).split("-"))
    parts = [w for w in nid.split("-") if w]
    if parts and all(w in words or w.isdigit() for w in parts[:-1]) and (
            parts[-1] in words or parts[-1].isdigit() or any(w.startswith(parts[-1]) for w in words)):
        return nid
    return "p-" + hashlib.sha1(nid.encode("utf-8")).hexdigest()[:10]


def public(node, brain, eligible, me, ids=None) -> dict:
    """Vue publique d'un souvenir partageable : texte nettoyé, liens vers des pages privées remplacés par « [privé] »
    (liens vers un fichier : « [fichier] »), seules les propriétés sans risque gardées (pas de chemin, pas de fichier
    d'origine, pas de compteur), étiquettes qui nomment une page privée retirées."""
    ids = ids if ids is not None else {nid: public_id(n) for nid, n in eligible.items()}

    def title_of(target):
        return clean(target["title"])

    def link(m):
        target = brain.get(m.group(1).strip())
        if target is None:  # page pas encore écrite : son nom est déjà dans ce texte public ; un fichier, lui, non
            return "[fichier]" if re.search(r"[/\\]|\.\w{2,5}$", m.group(1).strip()) else m.group(0)
        if target["id"] in eligible or is_foreign(target["id"]):
            return f"[[{title_of(target)}{m.group(2) or ''}" + (f"|{m.group(3)}" if m.group(3) else "") + "]]"
        return "[privé]"

    meta = node.get("meta") or {}
    out_meta = {k: meta[k] for k in SAFE_META if meta.get(k) not in (None, "", [])}
    if "sources" in out_meta:
        keep = []
        for s in _as_list(out_meta["sources"]):
            target = _ref(brain, s)
            if target is not None and target["id"] != node["id"] and (target["id"] in eligible or is_foreign(target["id"])):
                keep.append(f"[[{title_of(target)}]]")
        out_meta["sources"] = list(dict.fromkeys(keep))
        if not keep:
            out_meta.pop("sources")
    for k in ("resume", "keys", "auteur", "alias", "domaine", "stack", "format"):
        if k in out_meta:
            out_meta[k] = _clean_any(out_meta[k])
    if "url" in out_meta and not public_url(out_meta["url"]):
        out_meta.pop("url")  # fichier du PC, document partagé, invitation… : pas une adresse publique
    out_meta["par"] = me
    tags = []
    for x in _as_list(node.get("tags")):
        named = brain.nodes.get(x) or brain.nodes.get(slugify(x, 40))
        if (named is not None and named["id"] not in eligible) or clean(x) != x:
            continue  # l'étiquette nomme une page privée (projet, personne…) ou contient une coordonnée
        tags.append(x)
    src = fold(str(node.get("source") or "claude")).strip()
    src = {"lucas": "utilisateur", "user": "utilisateur", "verified": "verifie"}.get(src, src)
    project = node.get("project")
    return {"id": ids.get(node["id"], node["id"]), "type": node["type"], "title": clean(node["title"]),
            "body": WIKI_LINK.sub(link, clean(node.get("body") or "")), "tags": tags,
            "importance": node.get("importance", 3), "project": ids.get(project) if project in eligible else None,
            "created": node.get("created"), "updated": node.get("updated"),
            "source": src if src in SOURCE_LABELS else "claude", "status": "active", "meta": out_meta}


def content_sig(nodes) -> str:
    """Empreinte du contenu de mes souvenirs (sans les compteurs) : l'export ne repart que s'il a changé."""
    from .wikistore import VOLATILE_META
    h = hashlib.sha1()
    for nid in sorted(nodes):
        if is_foreign(nid):
            continue
        n = nodes[nid]
        meta = sorted((k, v) for k, v in (n.get("meta") or {}).items() if k not in VOLATILE_META)
        h.update(repr((nid, n.get("type"), n.get("title"), n.get("body"), n.get("project"), n.get("status"),
                       n.get("tags"), n.get("importance"), meta)).encode("utf-8", "surrogatepass"))
    return h.hexdigest()


def preview(brain) -> dict:
    """Ce qui partirait maintenant (et ce qui reste privé, par raison)."""
    projects = shared_projects(brain.nodes)
    shared, private = [], {}
    for nid, (ok, why) in judge(brain).items():
        if ok:
            shared.append(brain.nodes[nid])
        else:
            private[why.split(" (")[0]] = private.get(why.split(" (")[0], 0) + 1
    return {"shared": shared, "private": private,
            "projects": [(p, p["id"] in projects) for p in brain.projects() if not is_foreign(p["id"])]}


# ------------------------------------------------------------------------------------------ git
def _env(interactive=False):
    """git sans question dans le terminal (ni fenêtre, hors adhésion) ; identité : seulement le pseudo du dépôt commun
    (jamais un nom ou un e-mail venu de l'environnement), heures en UTC (pas de fuseau horaire dans l'historique)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "SSH_ASKPASS": "", "TZ": "UTC"})
    if not interactive:
        env["GCM_INTERACTIVE"] = "never"
    return env


def git(path, *args, timeout=60, interactive=False):
    """git -C <dossier> … → (code, sortie). Jamais de question dans le terminal ; interactive=True (adhésion, demandée
    par l'utilisateur) : le gestionnaire d'identifiants peut ouvrir sa fenêtre de connexion GitHub. GitHub CLI connecté :
    il fournit l'accès si git n'en a pas."""
    cmd = ["git"] + ([] if interactive else ["-c", "credential.interactive=never"])
    if shutil.which("gh"):
        cmd += ["-c", "credential.https://github.com.helper=!gh auth git-credential"]
    cmd += (["-C", str(path)] if path else []) + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL, env=_env(interactive))
        return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)


def check_access(url) -> bool:
    return bool(url) and git(None, "ls-remote", "--heads", url, timeout=30)[0] == 0


def _pull(path, me) -> str:
    """pull --rebase ; un conflit se règle seul : dans mon dossier ma version gagne, ailleurs celle du dépôt
    (personne d'autre n'écrit dans mon dossier, je n'écris jamais ailleurs). → "" si tout va bien, sinon l'erreur."""
    code, branch = git(path, "rev-parse", "--abbrev-ref", "HEAD", timeout=10)
    if code or branch in ("", "HEAD"):
        return ""
    if git(path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}", timeout=10)[0] != 0:
        code, heads = git(path, "ls-remote", "--heads", "origin", branch, timeout=60)
        if code or not heads.strip():
            return ""  # dépôt commun encore vide : rien à récupérer
        args = ["pull", "--rebase", "--autostash", "origin", branch]
    else:
        args = ["pull", "--rebase", "--autostash"]
    code, out = git(path, *args, timeout=120)
    if code == 0:
        return ""
    mine = f"{MEMBERS}/{me}/"
    for _ in range(20):
        code, files = git(path, "diff", "--name-only", "--diff-filter=U", timeout=20)
        names = [f for f in files.splitlines() if f.strip()]
        if not names:
            break
        for f in names:
            side = "--theirs" if f.startswith(mine) else "--ours"  # rebase : « theirs » = mon commit rejoué
            if git(path, "checkout", side, "--", f)[0] == 0:
                git(path, "add", "--", f)
            else:
                git(path, "rm", "-q", "--", f)
        code, out = git(path, "-c", "core.editor=true", "rebase", "--continue", timeout=60)
        if code == 0:
            return ""
    if (Path(path) / ".git" / "rebase-merge").exists() or (Path(path) / ".git" / "rebase-apply").exists():
        git(path, "rebase", "--abort", timeout=30)
        return short(out, 300)
    return ""


def _unstick(path) -> None:
    """Un git interrompu (PC éteint, processus tué) ne bloque pas les synchronisations suivantes : verrous de git
    abandonnés retirés, rebase inachevé abandonné. Appelé sous GIT_LOCK : aucun autre git du cerveau ne tourne."""
    import time
    g = Path(path) / ".git"
    for name in ("index.lock", "HEAD.lock", "ORIG_HEAD.lock"):
        try:
            if time.time() - (g / name).stat().st_mtime > 120:
                (g / name).unlink()
        except OSError:
            pass
    if (g / "rebase-merge").exists() or (g / "rebase-apply").exists():
        git(path, "rebase", "--abort", timeout=30)


def _commit(path, me, message) -> bool | None:
    """→ True : commit fait ; False : rien de nouveau ; None : git a échoué (verrou, dépôt occupé), rien n'est parti."""
    code, out = git(path, "add", "-A", "--", f"{MEMBERS}/{me}")
    if code:
        log(f"commun : add : {short(out, 300)}")
        return None
    if git(path, "diff", "--cached", "--quiet")[0] == 0:
        return False
    code, out = git(path, "-c", f"user.name={me}", "-c", f"user.email={me}@cerveau.invalid", "commit", "-q", "-m",
                    message, timeout=60)
    if code:
        log(f"commun : commit : {out}")
        return None
    return True


# ------------------------------------------------------------------------------------------ export (ma part publique)
def member_root(me=None) -> Path:
    return Path(settings()["path"]) / MEMBERS / (me or member())


def export(brain, me) -> dict:
    """Écrit ma part publique dans membres/<moi>/ (seules les pages qui changent ; celles qui ne sont plus partagées
    s'en vont). → compte rendu de wikistore.save."""
    from . import wikistore as ws
    root = member_root(me)
    (root / ws.PAGES).mkdir(parents=True, exist_ok=True)
    if not (root / ws.MARKER).is_file():
        write_text(root / ws.MARKER, json.dumps({"membre": me}) + "\n")
    eligible = {nid: brain.nodes[nid] for nid, (ok, _why) in judge(brain).items() if ok}
    ids = {nid: public_id(n) for nid, n in eligible.items()}
    pub = {ids[nid]: public(n, brain, eligible, me, ids) for nid, n in eligible.items()}
    edges = [{"from": ids[e["from"]], "to": ids[e["to"]], "rel": e.get("rel") or "relates"}
             for e in brain.edges if e["from"] in eligible and e["to"] in eligible]
    prev = read_json(EXPORT_CACHE, {}) or {}
    w = prev.get("wiki") or {}
    files = (w.get("files") or {}) if w.get("root") == str(root) else {}
    data = {"version": 1, "created": prev.get("created") or now_iso(), "nodes": pub, "edges": edges,
            "wiki": {"root": str(root), "files": files, "sig": w.get("sig")}}
    rep = ws.save(data, root=root, cache_file=EXPORT_CACHE, parse_file=EXPORT_PAGES, guard=False)
    rep["shared"] = len(pub)
    return rep


def export_journal(brain, me) -> int:
    """membres/<moi>/journal/AAAA-MM.md : mes observations datées des projets communs (jamais le texte des sessions,
    jamais une observation sensible)."""
    from . import wiki
    projects = shared_projects(brain.nodes)
    if not projects:
        return 0
    pages = wiki.journal_pages(sessions=False, keep=lambda o: o.get("proj") in projects and not sensitive(o.get("t", "")))
    titles = {pid: clean(brain.nodes[pid]["title"]) for pid in projects}
    root = member_root(me)
    n = 0
    for rel, text in pages.items():
        text = re.sub(r" · ([a-z0-9-]+)$", lambda m: f" · {titles.get(m.group(1), m.group(1))}", clean(text), flags=re.M)
        p = root / rel
        try:
            if p.read_text(encoding="utf-8") == text:
                continue
        except OSError:
            pass
        write_text(p, text)
        n += 1
    return n


# ------------------------------------------------------------------------------------------ lecture (les amis)
def merge_foreign(data) -> None:
    """Ajoute au graphe les pages des amis (lecture seule) : ids « c--<ami>--<id> », propriété commun_par."""
    me = member()
    if not me:
        return
    from . import wikistore as ws
    base = Path(settings()["path"]) / MEMBERS
    try:
        folders = sorted(d for d in base.iterdir() if d.is_dir() and d.name != me and d.name[:1] not in "._")
    except OSError:
        return
    nodes, edges, who = data.setdefault("nodes", {}), data.setdefault("edges", []), []
    for d in folders:
        m = slugify(d.name, 40)
        try:
            fd = ws.load(d, cache_file=STATE_DIR / f"commun-{m}.json", parse_file=STATE_DIR / f"commun-{m}-pages.json")
        except Exception as exc:
            log(f"commun : lecture de {d.name} : {exc!r}")
            continue
        pre = f"{FOREIGN}{m}--"
        count = 0
        for nid, n in (fd.get("nodes") or {}).items():
            if n.get("status", "active") != "active":
                continue
            meta = {k: v for k, v in (n.get("meta") or {}).items() if k in SAFE_META or k == "par"}
            meta["commun_par"] = m
            nodes[pre + nid] = dict(n, id=pre + nid, project=(pre + n["project"]) if n.get("project") else None,
                                    meta=meta, source="commun")
            count += 1
        for e in fd.get("edges") or []:
            if pre + e["from"] in nodes and pre + e["to"] in nodes:
                edges.append(dict(e, **{"from": pre + e["from"], "to": pre + e["to"]}))
        if count:
            who.append((m, count))
    data["commun"] = {"membre": me, "amis": who}


# ------------------------------------------------------------------------------------------ synchronisation
def sync(pull=True, push=True, auto=False) -> list:
    """Export de ma part publique, commit, pull (conflits réglés seuls), push (réessayé si un ami a poussé entre-temps).
    Plusieurs déclenchements rapprochés se regroupent : celui qui tourne reprend ce qui est arrivé pendant ce temps (un
    envoi demandé pendant une simple récupération compris)."""
    me = member()
    if not me:
        return ["· pas membre du cerveau commun (`brain commun` pour voir)"]
    path = Path(settings()["path"])
    out = []
    save_state(pending=True, **({"push_pending": True} if push else {}))
    try:
        with FileLock(GIT_LOCK, timeout=1 if auto else 30, stale=600):
            import time
            from .common import days_since
            from .store import Brain
            failed = False
            for _ in range(4):
                _unstick(path)  # à chaque tour : un verrou abandonné pendant qu'une synchro tourne ne bloque pas la suite
                push = push or bool(state().get("push_pending"))
                save_state(pending=False, push_pending=False)
                committed = False
                if push:
                    brain = Brain.load()
                    rep = export(brain, me)
                    j = export_journal(brain, me)
                    committed = _commit(path, me, f"cerveau commun : {me} — {rep['shared']} page(s) partagée(s)")
                    failed = committed is None
                    if failed:  # rien n'est parti : pas compté comme envoyé, repris au tour suivant ou à la prochaine synchro
                        save_state(push_pending=True)
                        time.sleep(2)
                        continue
                    if committed:
                        out.append(f"✓ {rep['written']} page(s) écrite(s), {rep['removed']} retirée(s)"
                                   + (f", journal ({j} mois)" if j else ""))
                    save_state(exported=content_sig(brain.nodes))
                # rien de public n'a changé (un souvenir privé modifié) et récupéré il y a peu : pas d'aller-retour réseau
                quiet = auto and push and not committed and days_since(state().get("pulled")) * 86400 < PULL_EVERY
                if (pull or push) and not quiet:
                    err = _pull(path, me)
                    if err:
                        save_state(conflict=now_iso())
                        out.append(f"✗ récupération : {err}")
                        break
                    save_state(pulled=now_iso(), conflict=None)
                if push and not quiet:
                    tracked = git(path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}",
                                  timeout=10)[0] == 0
                    ahead = git(path, "rev-list", "--count", "@{upstream}..HEAD", timeout=10)[1].strip() if tracked else "1"
                    for _attempt in range(3 if ahead not in ("0", "") else 0):  # un ami a poussé entre-temps : on reprend
                        code, txt = git(path, "push", "-u", "origin", "HEAD", timeout=120)
                        if code == 0:
                            out.append("✓ envoyé au cerveau commun")
                            save_state(pushed=now_iso())
                            break
                        if any(k in txt for k in ("rejected", "fetch first", "non-fast-forward")):
                            _pull(path, me)
                            continue
                        out.append(f"✗ envoi : {short(txt, 200)}")
                        break
                st = state()
                if not st.get("pending") and not st.get("push_pending") and (
                        not push or st.get("exported") == content_sig(Brain.load().nodes)):
                    break  # rien de nouveau pendant ce tour (un changement arrivé entre-temps repart tout de suite)
            if failed:
                out.append("✗ enregistrement local : git occupé, nouvel essai à la prochaine synchro")
    except TimeoutError:
        out.append("· synchronisation déjà en cours (elle reprendra ce changement)")
    if auto:
        log("commun : " + (" | ".join(out) or "à jour"))
    return out or ["✓ à jour"]


def spawn(args):
    """`brain.py <args>` en arrière-plan (sans fenêtre, priorité basse) → le processus (False si échec) ;
    BRAIN_COMMUN_FG=1 : tout de suite (tests)."""
    if os.environ.get("BRAIN_COMMUN_FG") == "1":
        import contextlib
        from . import cli
        try:
            with contextlib.redirect_stdout(sys.stderr):  # la sortie d'un hook reste du JSON valide
                cli.main(list(args))
        except SystemExit:
            pass
        return True
    try:
        exe = Path(sys.executable)
        if os.name == "nt" and (exe.parent / "pythonw.exe").exists():
            exe = exe.parent / "pythonw.exe"
        kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                  cwd=str(BRAIN_DIR), env={**os.environ, "BRAIN_BG": "1"})
        if os.name == "nt":
            kw["creationflags"] = 0x00000008 | 0x00000200 | 0x00004000
        else:
            kw["start_new_session"] = True
        return subprocess.Popen([str(exe), "-I", "-S", str(BRAIN_PY), *args], **kw)
    except Exception as exc:
        log(f"commun : arrière-plan {args} : {exc!r}")
        return False


def delay() -> float:
    """Délai avant l'envoi (config commun.delai, 15 s) : des ajouts rapprochés partent ensemble, et une correction ou un
    « garde ça pour moi » juste après un ajout empêche le premier jet de partir."""
    try:
        return max(0.0, float(os.environ.get("BRAIN_COMMUN_DELAY") or settings().get("delai", DELAY)))
    except (TypeError, ValueError):
        return DELAY


def after_save(data) -> None:
    """Après une écriture du cerveau : si ma part publique a pu changer, export et envoi en arrière-plan (différé de
    quelques secondes ; une synchronisation déjà prévue emporte ce changement)."""
    if not member():
        return
    try:
        import time
        sig = content_sig(data.get("nodes") or {})
        st = state()
        if sig == st.get("exported") or sig == st.get("queued"):
            return
        fg = os.environ.get("BRAIN_COMMUN_FG") == "1"
        if not fg and time.time() < float(st.get("scheduled") or 0):
            save_state(queued=sig, pending=True)  # la synchronisation prévue n'a pas encore commencé : elle l'emporte
            return
        wait = 0.0 if fg else delay()
        save_state(queued=sig, pending=True, scheduled=time.time() + wait)
        if not spawn(["commun", "sync", "--auto"] + (["--delai", f"{wait:g}"] if wait else [])):
            save_state(scheduled=0)
    except Exception as exc:
        log(f"commun : après écriture : {exc!r}")


def maybe_pull(wait=0.0) -> None:
    """Démarrage, chaque message, fin de tour : récupère les pages des amis en arrière-plan, au plus une fois par minute.
    Dernière récupération de plus de FRESH s : attend jusqu'à `wait` s qu'elle finisse, pour que ce message voie déjà les
    nouveautés ; au-delà il continue et elle finit seule."""
    if not member():
        return
    from .common import days_since
    st = state()
    if days_since(st.get("pull_asked")) * 86400 < PULL_EVERY:
        return
    stale = days_since(st.get("pulled")) * 86400 > FRESH
    save_state(pull_asked=now_iso())
    proc = spawn(["commun", "sync", "--auto", "--no-push"])
    if wait and stale and hasattr(proc, "wait"):
        try:
            proc.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            pass


# ------------------------------------------------------------------------------------------ adhésion
SCHEMA = """# 🤝 Cerveau commun — schéma

Ce dépôt réunit la **part publique** du cerveau de chaque membre (plugin « cerveau » pour Claude Code). Le cerveau de
chacun publie la sienne dans `membres/<nom>/` (une page par souvenir partagé, même format que le wiki) et lit celle des
autres, presque en temps réel. Personne n'écrit chez un autre : c'est le cerveau de chacun qui écrit son dossier, seul.

## Ce qui ne part jamais
Profil et règles (préférences) · tout contenu sensible (santé, argent personnel, intimité, identité, opinions, accès) ·
une page qui a contenu un secret · les personnes (données de tiers) · les documents personnels (source sans adresse web
publique) et ce qui n'est tiré que d'eux · les références (outils et comptes de chacun) · le domaine « perso » · les
projets non partagés · ce qui est marqué privé · le texte des sessions. Retirés du reste : coordonnées, secrets, chemins
de fichiers du PC, liens qui donnent un accès (document partagé, invitation, réunion, réseau local) ; un lien vers une
page privée devient « [privé] ».

## Ce qui part
Le savoir (sources web, recherches, concepts, sujets, analyses, entités qui ne sont pas des personnes, apprentissages),
tout ce qui appartient à un projet déclaré commun (tâches, décisions, faits, observations datées dans `journal/`), et ce
qui est marqué partagé.

## Pour Claude
- Les pages des amis apparaissent dans ton cerveau en lecture seule, marquées « 🤝 nom » : t'en servir, les citer.
- Pour compléter le savoir d'un ami : écrire ta propre page (elle sera partagée) en citant la sienne.
- Ne jamais modifier les fichiers de ce dépôt à la main ; ce qui y est envoyé reste dans son historique git.
- Commandes : `brain commun` (état), `brain commun apercu` (ce qui part), `brain commun projet <id>` (partager un
  projet), `--commun non` sur `add`/`edit` (garder privé), `brain commun quitter`.
"""

README = """# 🤝 Cerveau commun

La part publique du cerveau de chaque membre : ce que chacun apprend (recherches, savoir, projets communs) nourrit le
cerveau de tous, presque en temps réel. Le profil, les préférences et tout ce qui est personnel ne quittent jamais le PC
de chacun. Détail et règles : [CLAUDE.md](CLAUDE.md).

Rejoindre : être invité sur ce dépôt (GitHub), accepter l'invitation, puis dire oui quand Claude le propose (ou
`python "$HOME/.claude/brain/brain.py" commun rejoindre --oui`). Dépôt **privé** : à garder ainsi.
"""


def _scaffold(path) -> bool:
    made = False
    for rel, text in ((MARKER, json.dumps({"version": 1}) + "\n"), ("CLAUDE.md", SCHEMA), ("README.md", README),
                      (".gitattributes", "* text=auto eol=lf\n")):
        p = Path(path) / rel
        if not p.exists():
            write_text(p, text)
            made = True
    return made


def apercu_text(brain) -> str:
    from .store import TYPES
    pv = preview(brain)
    by = {}
    for n in pv["shared"]:
        by[n["type"]] = by.get(n["type"], 0) + 1
    rows = [f"🤝 Cerveau commun — ce qui partirait de ton cerveau : {len(pv['shared'])} page(s)"
            + (" (" + ", ".join(f"{TYPES.get(t, t)} {c}" for t, c in sorted(by.items(), key=lambda x: -x[1])) + ")"
               if by else "")]
    for n in sorted(pv["shared"], key=lambda n: n["title"])[:15]:
        rows.append(f"  + {n['title']} [{TYPES.get(n['type'], n['type'])}]")
    if len(pv["shared"]) > 15:
        rows.append(f"  … +{len(pv['shared']) - 15}")
    if pv["private"]:
        rows.append("Reste privé : " + " · ".join(f"{why} {c}" for why, c in sorted(pv["private"].items(), key=lambda x: -x[1])))
    if pv["projects"]:
        rows.append("Projets (privés tant que tu ne les partages pas — `brain commun projet <id>`) : "
                    + " · ".join(f"{p['title']} `{p['id']}`" + (" ✓ commun" if on else "") for p, on in pv["projects"]))
    rows.append("Jamais : profil, règles, contenu sensible, personnes, documents personnels, références, domaine perso, "
                "texte des sessions ; coordonnées, secrets, chemins de fichiers et liens d'accès (documents partagés, "
                "invitations, réunions) retirés ; lien vers une page privée → « [privé] ». Ce qui est envoyé reste dans "
                "l'historique du dépôt commun.")
    return "\n".join(rows)


def join(nom=None, oui=False) -> list:
    """Rejoindre le cerveau commun (seulement avec l'accord : oui=True)."""
    from .store import Brain
    c = settings()
    url = repo_url(c.get("repo"))
    if not url:
        raise RuntimeError("aucun cerveau commun configuré : `brain config commun.repo proprietaire/depot`")
    brain = Brain.load()
    if not oui:
        return [apercu_text(brain), f"→ pour rejoindre {c.get('repo')} : `brain commun rejoindre --oui [--nom pseudo]` "
                                   "(rien n'est envoyé avant)"]
    path = Path(c["path"])
    out = []
    if not (path / ".git").exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        code, txt = git(None, "clone", "-q", url, str(path), timeout=300, interactive=True)
        if code:
            raise RuntimeError(f"accès refusé au cerveau commun ({short(txt, 160)}) : accepte d'abord l'invitation GitHub "
                               f"au dépôt {c.get('repo')} ; si c'est fait, connecte git à GitHub une fois dans un terminal "
                               f"(`gh auth login`, ou `git clone {url}` qui ouvre la fenêtre de connexion), puis relance")
        out.append(f"✓ cerveau commun récupéré : {path}")
    if not nom:  # le prénom seulement (le pseudo se voit chez tous les amis)
        code, gname = git(None, "config", "--global", "user.name", timeout=10)
        nom = gname.split()[0] if code == 0 and gname.strip() else (os.environ.get("USERNAME") or os.environ.get("USER")
                                                                    or "membre")
    me = slugify(nom, 30)
    root = path / MEMBERS / me
    mine = c.get("id") or hashlib.sha1(os.urandom(16)).hexdigest()[:12]  # pas un secret : évite deux amis au même pseudo
    if root.exists() and (read_json(root / "membre.json", {}) or {}).get("id") != mine:
        raise RuntimeError(f"le pseudo « {me} » est déjà pris dans le cerveau commun : choisis-en un autre "
                           f"(`brain commun rejoindre --oui --nom <autre>`)")
    set_config("commun.id", mine)
    git(path, "config", "user.name", me)  # identité locale : un PC sans git configuré ne bloque ni commit ni rebase
    git(path, "config", "user.email", f"{me}@cerveau.invalid")
    if git(path, "rev-parse", "--verify", "-q", "HEAD")[0] != 0:  # dépôt encore vide : la branche par défaut du dépôt
        code, txt = git(path, "ls-remote", "--symref", "origin", "HEAD", timeout=60)
        m = re.search(r"ref: refs/heads/(\S+)\s+HEAD", txt)
        git(path, "symbolic-ref", "HEAD", f"refs/heads/{m.group(1) if m else 'main'}")
    if _scaffold(path):
        git(path, "add", "-A", "--", MARKER, "CLAUDE.md", "README.md", ".gitattributes")
        git(path, "-c", f"user.name={me}", "-c", f"user.email={me}@cerveau.invalid", "commit", "-q", "-m",
            "cerveau commun : squelette")
    if root.exists():
        out.append(f"· dossier membres/{me} déjà là : repris")
    root.mkdir(parents=True, exist_ok=True)
    info = read_json(root / "membre.json", {}) or {}
    write_text(root / "membre.json", json.dumps({"nom": me, "id": mine, "depuis": info.get("depuis") or now_iso()[:10]},
                                                ensure_ascii=False) + "\n")
    set_config("commun.etat", "membre")
    set_config("commun.nom", me)
    set_config("commun.path", str(path))
    for line in sync(pull=True, push=True):
        out.append(line)
    b = Brain.load()
    amis = (b.data.get("commun") or {}).get("amis") or []
    shared = sum(1 for n in b.nodes.values() if not is_foreign(n["id"]) and verdict(n, shared_projects(b.nodes))[0])
    out.append(f"✓ membre « {me} » : {shared} page(s) partagée(s) ; "
               + (f"{sum(c for _, c in amis)} page(s) de {len(amis)} ami(s) : " + ", ".join(m for m, _ in amis)
                  if amis else "aucun ami n'a encore partagé"))
    return out


def decline() -> str:
    set_config("commun.etat", "refuse")
    return "✓ cerveau commun refusé : plus de proposition (`brain commun rejoindre` reste possible)"


def leave(keep=False) -> list:
    me = member()
    if not me:
        return ["· pas membre du cerveau commun"]
    path = Path(settings()["path"])
    out = []
    if not keep:
        with FileLock(GIT_LOCK, timeout=30, stale=600):
            git(path, "rm", "-r", "-q", "--", f"{MEMBERS}/{me}")
            git(path, "-c", f"user.name={me}", "-c", f"user.email={me}@cerveau.invalid", "commit", "-q", "-m",
                f"cerveau commun : {me} s'en va")
            err = _pull(path, me)
            code, txt = git(path, "push", timeout=120)
            out.append("✓ tes pages sont retirées du cerveau commun (elles restent dans son historique git)" if code == 0
                       else f"✗ retrait non envoyé : {short(err or txt, 200)} — relance `brain commun quitter`")
    set_config("commun.etat", "parti")
    out.append("✓ tu ne reçois plus les pages des amis ; ton cerveau reste intact")
    return out


def set_project(ref, share=True) -> str:
    from .store import Brain
    with Brain.edit() as b:
        p = b.get(ref)
        if not p or p["type"] != "project" or is_foreign(p["id"]):
            raise RuntimeError(f"projet introuvable : {ref} (voir `brain proj`)")
        meta = dict(p.get("meta") or {})
        if share:
            meta["partage"] = True
            meta.pop("prive", None)
        else:
            meta.pop("partage", None)
        b.update(p["id"], meta=meta)
        n = sum(1 for x in b.nodes.values() if x.get("project") == p["id"] and x.get("status", "active") == "active")
    return (f"✓ projet « {p['title']} » commun : ses {n} souvenir(s) non sensibles partent dans le cerveau commun"
            if share else f"✓ projet « {p['title']} » de nouveau privé : ses pages quittent le cerveau commun")


def status(brain=None) -> str:
    from .store import Brain
    c = settings()
    me = member()
    if not me:
        etat = c.get("etat")
        hint = {"refuse": "refusé", "parti": "quitté"}.get(etat, "pas encore rejoint")
        return (f"🤝 Cerveau commun ({c.get('repo') or 'non configuré'}) : {hint} — `brain commun apercu` montre ce qui "
                "partirait ; `brain commun rejoindre --oui` pour entrer")
    brain = brain or Brain.load()
    st = state()
    amis = (brain.data.get("commun") or {}).get("amis") or []
    mine = len((read_json(EXPORT_CACHE, {}) or {}).get("nodes") or {})
    rows = [f"🤝 Cerveau commun ({c.get('repo')}) : membre « {me} » · {mine} page(s) partagée(s) · "
            + (f"{sum(n for _, n in amis)} page(s) de {len(amis)} ami(s) ({', '.join(f'{m} {n}' for m, n in amis)})"
               if amis else "aucun ami n'a encore partagé"),
            f"Synchro : récupéré {fmt_date(st.get('pulled'))} {str(st.get('pulled') or '')[11:16]} · envoyé "
            f"{fmt_date(st.get('pushed'))} {str(st.get('pushed') or '')[11:16]}"
            + (" · ⚠ conflit non réglé (`brain commun sync`)" if st.get("conflict") else "")]
    return "\n".join(rows)


def notice(brain) -> str:
    """Ligne du démarrage : l'état du cerveau commun pour un membre, ou (une fois par jour) la proposition d'y entrer."""
    me = member()
    if me:
        amis = (brain.data.get("commun") or {}).get("amis") or []
        new = sorted((n for n in brain.nodes.values() if is_foreign(n["id"]) and n.get("status", "active") == "active"),
                     key=lambda n: n.get("updated") or "", reverse=True)[:3]
        return (f"🤝 Cerveau commun : {sum(n for _, n in amis)} page(s) de {len(amis)} ami(s) dans ton cerveau "
                f"(lecture seule, marquées 🤝)" + (" — récentes : " + " · ".join(f"« {short(n['title'], 50)} » ({author(n)})"
                                                                                  for n in new) if new else "")
                + ". Ce que tu apprends part tout seul, sauf le privé (profil, règles, sensible, projets non partagés) ; "
                  "`--commun non` garde une page pour toi.")
    if os.environ.get("CLAUDE_CODE_REMOTE"):
        return ""
    c = settings()
    if c.get("etat") in ("refuse", "parti") or not c.get("repo"):
        return ""
    st = state()
    from .common import days_since
    if days_since(st.get("access_checked")) > 1:
        save_state(access_checked=now_iso())
        spawn(["commun", "verifier"])
        return ""
    if not st.get("access"):
        if st.get("hinted"):
            return ""
        save_state(hinted=now_iso())  # accès pas vérifiable (invitation pas encore acceptée, git pas connecté) : une fois
        return (f"🤝 Cerveau commun de tes amis ({c['repo']}) : accès pas encore vérifié. Si l'utilisateur y a été invité, "
                "propose-le lui une fois avec ce qui partirait (`brain commun apercu`) ; s'il accepte : invitation GitHub "
                "acceptée, puis `brain commun rejoindre --oui --nom <pseudo>` (une fenêtre de connexion GitHub peut "
                "s'ouvrir) ; s'il refuse : `brain commun non`.")
    if days_since(st.get("offered")) < 1:
        return ""
    save_state(offered=now_iso())
    return (f"🤝 Le cerveau commun de tes amis ({c['repo']}) t'est ouvert. Propose-le à l'utilisateur, une fois, en lui "
            "disant ce qui partirait : `brain commun apercu` (jamais profil, règles, contenu sensible, chemins, texte des "
            "sessions). S'il accepte : `brain commun rejoindre --oui --nom <pseudo>` ; s'il refuse : `brain commun non`.")
