"""Vie privée du cerveau commun : ce qui peut partir chez les amis et ce qui reste chez soi. Le verdict de chaque
souvenir (profil, règles, domaines perso et sujets sensibles restent privés), et la vue publique d'un souvenir
partageable : chemins, adresses, téléphones, courriels, liens privés et nom de l'utilisateur remplacés, propriétés
sans risque seulement.

Découpé de commun.py le 21/11/2026 (étape 8 du plan), sans changer le comportement : ces noms restent accessibles
depuis commun (`commun.clean`, `commun.verdict`…). Chargé seulement quand il sert (envoi, aperçu, adhésion) : un
hook qui ne fait que regarder les nouveautés des amis ne compile plus ces motifs."""
from __future__ import annotations

import hashlib
import re

from .common import fold, slugify
from .commun import NEVER, SAFE_META, is_foreign


KNOWLEDGE = ("source", "concept", "topic", "analysis", "entity", "learning")  # pas « reference » : outils et comptes


PERSONAL_DOMAINS = {"perso", "personnel", "prive", "vie-privee", "sante", "famille", "finances"}


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


# --- Règles du partage seulement (clean) : jamais appliquées à l'enregistrement, qui ne masque que les secrets.
# Chemins de fichiers du PC : lecteur Windows, partage réseau, %VARIABLE%, ~ ou $HOME, dossiers personnels et disques
# (/home, /Users, /mnt, /Volumes…). Un dossier peut avoir des espaces dans son nom (« C:\Users\Jean Dupont\… ») tant
# qu'un séparateur le suit. Pas une adresse web : « site.com/home/… » reste intact.
_SEG = r"[\w.()&+~$'’-]+(?: [\w.()&+~$'’-]+){1,3}"


_TAIL = rf"(?:[\\/](?:{_SEG}(?=[\\/])|[^\s\"'<>|`\\/]*))+"


PATH_RX = re.compile(rf"(?:(?<![\w/])[A-Za-z]:|\\\\[\w.$-]+|(?<![\w%])%[A-Za-z_][\w()]*%|\$env:\w+|"
                     rf"(?<![\w.:/~$-])(?:~|\$HOME\b|\$\{{HOME\}}))(?=[\\/]){_TAIL}|"
                     rf"(?<![\w.:/~-])(?:/[A-Za-z](?=/(?:Users|home)/))?/(?:home|Users|root|mnt|Volumes|media|run/media|"
                     rf"var/home)(?=[\\/]){_TAIL}")


# … sauf ceux de Claude Code et du plugin (~/.claude/…), les mêmes sur chaque PC — hors projects/, dont les noms de
# dossier recopient le chemin d'un projet (nom d'utilisateur compris)
TOOL_PATH = re.compile(r"(?:~|\$HOME|\$\{HOME\}|%USERPROFILE%|\$env:USERPROFILE)[\\/]\.claude"
                       r"(?!.*[\\/]projects(?:[\\/]|$))(?:[\\/]|$)", re.S)


# adresse d'un dépôt git par ssh (« ssh://… », « git@hôte:propriétaire/dépôt.git ») : l'accès de quelqu'un
REMOTE_RX = re.compile(r"(?i)\b(?:ssh|git|sftp|rsync|svn\+ssh|git\+ssh)://[^\s<>\"'`]+|"
                       r"(?<![\w.+/-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+:[^\s<>\"'`]+")


# e-mail déguisé : « marc [at] site.ch », « marc(at)site(dot)ch », « marc arobase site point ch »
_AT = r"(?:\s*[\[({<]\s*(?:at|@|arobase|chez)\s*[\])}>]\s*|\s+arobase\s+)"


_DOT = r"(?:\.|\s*[\[({<]\s*(?:dot|point)\s*[\])}>]\s*|\s+(?:dot|point)\s+)"


EMAIL_AT_RX = re.compile(rf"(?i)(?<![\w.+-])[\w.+-]+{_AT}[\w-]+(?:{_DOT}[\w-]+)+")


# téléphones : indicatif international (+32…, 0041…), annoncés (« tél. 079… »), ou nationaux en groupes (0470 12 34 56)
PHONE_INTL_RX = re.compile(r"(?<![\w+])(?:\+|00\s?)[1-9]\d{0,2}(?:\s?\(0\))?(?:[\s.\-/()]{0,2}\d){8,13}(?!\d)"
                           r"(?!\s?(?:[%€$£]|k€|M€|euros?\b|EUR\b|USD\b|CHF\b))")


PHONE_CUE_RX = re.compile(r"(?i)\b((?:t[ée]l(?:[ée]phone)?|phone|mobile|portable|natel|gsm|fax|whatsapp)\.?\s*(?::|n°)?\s*)"
                          r"\(?\d(?:[\s.\-/()]{0,2}\d){7,14}(?!\d)")


PHONE_NAT_RX = re.compile(r"(?<![\w+.,/-])0\d{1,4}(?:[\s.\-/]\d{2,4}){2,4}(?![\w,]|[.,]\d)")


# adresses postales : numéro + voie + nom, avec ou sans code postal et ville (France ; aussi « Rue du Rhône 42, 1204
# Genève » et « 221B Baker Street »). Voie ambiguë (place, cours, route…) : seulement suivie de « du », « de la »…
_UP = "A-ZÀ-ÖØ-ÞŒ"


_NAME = rf"(?:[dlDL][’']\s?)?[{_UP}][\w’'-]*"


_PART = r"(?:de|du|des|la|le|les|aux|au|à|sur|sous|en|lès|d[’']|l[’'])"


_SURE = r"rue|ruelle|avenue|av\.|boulevard|bd|impasse|allée|allee|quai|chaussée|chaussee|faubourg|fbg|rond-point|esplanade|parvis"


_MAYBE = (r"place|cours|route|chemin|passage|voie|square|promenade|sentier|montée|montee|traverse|hameau|cité|cite|résidence|"
          r"residence|lotissement|lieu-dit")


_NUM = r"(?<![\w,.-])\d{1,4}(?:\s?(?:bis|ter|quater|[A-Da-d])\b)?,?\s+"


_MORE = rf"(?:[\s-]+(?:(?:{_PART}|\d{{1,4}})\s*)*{_NAME}){{0,4}}"


_TOWN = (rf"[\w’'-]*[^\W\d_][\w’'-]*(?:[\s-]+(?:{_PART}[\s-]+)*(?!(?i:cedex)\b)[{_UP}][\w’'-]*){{0,3}}"
         rf"(?:\s+(?i:cedex)(?:\s+\d{{1,2}})?)?")


ADDRESS_RXS = [
    re.compile(rf"{_NUM}(?i:{_SURE}|{_MAYBE})\.?\s+[^\n,;:]{{1,60}}?,?\s+(?:[A-Z]{{1,2}}-)?\d{{4,5}}\s+{_TOWN}"),
    re.compile(rf"(?<![\w-])(?i:{_SURE}|{_MAYBE})\s+(?:{_PART}\s*)*{_NAME}{_MORE}\s+\d{{1,4}}[a-zA-Z]?,?\s+"
               rf"(?:[A-Z]{{1,2}}-)?\d{{4}}\s+{_TOWN}"),
    re.compile(rf"{_NUM}(?i:{_SURE})\s+(?:(?:{_PART}|\d{{1,4}})\s*)*{_NAME}{_MORE}"),
    re.compile(rf"{_NUM}(?i:{_MAYBE})\s+(?:{_PART}\s*)+(?:\d{{1,4}}\s+)*{_NAME}{_MORE}"),
    re.compile(r"(?<![\w-])\d{1,5}[A-Za-z]?\s+(?:[A-Z][\w’'-]*\s+){1,3}(?:Street|St\.|Road|Rd\.|Avenue|Ave\.|Lane|Drive|"
               r"Boulevard|Blvd\.?)(?!\w)"),
]


# ce que le nettoyage met à la place : un souvenir qui n'est presque plus que ça reste privé (hollow)
PLACEHOLDER_RX = re.compile(r"«[^»\n]{0,40}»|\[(?:chemin|lien privé|privé|fichier)\]|l'utilisateur")


_OWNER = {}


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
    if hollow(node):
        return False, "presque rien sans ses données personnelles"
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


def _owner_rx():
    """Prénom de l'utilisateur (réglage local publish.owner) : jamais partagé, il devient « l'utilisateur » (comme dans
    les skills de l'échange). Relu seulement quand config.json change."""
    from .common import CONFIG_FILE, owner_name
    try:
        stamp = CONFIG_FILE.stat().st_mtime_ns
    except OSError:
        stamp = None
    if "rx" not in _OWNER or _OWNER.get("stamp") != stamp:
        name = owner_name()
        _OWNER.update(stamp=stamp, rx=re.compile(rf"(?<![\w-]){re.escape(name)}(?![\w-])", re.I) if len(name) >= 3 else None)
    return _OWNER["rx"]


def _path(m) -> str:
    """Chemin du PC → « [chemin] » (la ponctuation de la phrase reste) ; un chemin de Claude Code ou du plugin reste."""
    p = m.group(0)
    core = p.rstrip(".,;:!?)")
    return p if TOOL_PATH.match(core) else "[chemin]" + p[len(core):]


def _phone(m) -> str:
    """Numéro national en groupes : un téléphone s'il a 9 à 11 chiffres (« 01 02 2024 », une date, reste)."""
    return "«téléphone»" if 9 <= sum(c.isdigit() for c in m.group(0)) <= 11 else m.group(0)


def clean(text) -> str:
    """Texte public, avant tout partage (souvenirs du cerveau commun, skills de l'échange) : liens qui donnent un accès et
    adresses de dépôt git par ssh retirés, secrets masqués, coordonnées retirées (e-mails, même écrits « [at] » ;
    téléphones d'ici et d'ailleurs ; adresses postales), chemins de fichiers du PC effacés (sauf ceux de Claude Code et du
    plugin, ~/.claude/…), prénom de l'utilisateur remplacé par « l'utilisateur »."""
    from .privacy import redact_contacts
    def url(m):
        u = m.group(0).rstrip(".,;:!?")
        return ("[lien privé]" if private_url(u) else u) + m.group(0)[len(u):]

    text = URL_RX.sub(url, REMOTE_RX.sub("[lien privé]", str(text or "")))
    text = PATH_RX.sub(_path, text)
    text = EMAIL_AT_RX.sub("«e-mail»", text)
    for rx in ADDRESS_RXS:
        text = rx.sub("«adresse»", text)
    text = PHONE_CUE_RX.sub(lambda m: m.group(1) + "«téléphone»", text)
    text = PHONE_NAT_RX.sub(_phone, PHONE_INTL_RX.sub("«téléphone»", text))
    text = redact_contacts(text)
    owner = _owner_rx()
    return owner.sub("l'utilisateur", text) if owner else text


def hollow(node) -> bool:
    """Sans ses coordonnées, chemins, liens privés et prénom, ce souvenir ne dirait presque plus rien
    (« «e-mail», «téléphone» ») : il reste privé plutôt que de partir vide."""
    for text, least in ((node.get("title") or "", 2), (node.get("body") or "", 4)):
        public = clean(text)
        if public != text and len(re.findall(r"[^\W\d_]{3,}", PLACEHOLDER_RX.sub(" ", public))) < least:
            return True
    return False


def _clean_any(v):
    return clean(v) if isinstance(v, str) else [clean(str(x)) for x in v] if isinstance(v, (list, tuple)) else v


def public_id(node) -> str:
    """Id publié : celui du souvenir s'il ne dit rien de plus que le titre public ; sinon une empreinte (un id garde le
    titre d'origine : renommé depuis, ou qui contenait une coordonnée — numéro de téléphone compris)."""
    nid = str(node["id"])
    title = str(node.get("title") or "")
    pub = clean(title)
    words = set(slugify(pub, 400).split("-"))
    parts = [w for w in nid.split("-") if w]
    if parts and pub == title and all(w in words or w.isdigit() for w in parts[:-1]) and (
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
    src = {"user": "utilisateur", "verified": "verifie"}.get(src, src)
    project = node.get("project")
    return {"id": ids.get(node["id"], node["id"]), "type": node["type"], "title": clean(node["title"]),
            "body": WIKI_LINK.sub(link, clean(node.get("body") or "")), "tags": tags,
            "importance": node.get("importance", 3), "project": ids.get(project) if project in eligible else None,
            "created": node.get("created"), "updated": node.get("updated"),
            "source": src if src in SOURCE_LABELS else "claude", "status": "active", "meta": out_meta}


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
