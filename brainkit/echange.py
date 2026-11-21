"""Échange de skills et d'outils entre cerveaux — ce qu'un cerveau apprend sert à tous, en deux étages.

Étage 1, entre membres du cerveau commun (dépôt GitHub privé, voir commun.py) : chaque cerveau publie dans SON dossier
`membres/<nom>/` ses skills apprises (`skills/<skill>/` : SKILL.md, références, scripts, `skill.json`), ses déclencheurs
appris (`declencheurs.json`), l'usage qu'il fait des skills reçues (`usage.json`) et ses retours techniques
(`retours.json` : des compteurs, jamais de texte de session). Il lit ceux des autres, en lecture seule.
Étage 2, pour tous ceux qui ont le plugin : une skill qui a fait ses preuves est proposée (`propositions`), et le
propriétaire du plugin la fait entrer dans une version (`promouvoir`), que Claude Code distribue à tout le monde.

Ce qui part (jamais avant l'accord de l'auteur : `brain echange oui`) : les skills que le cerveau a rédigées lui-même
(marque `.cerveau-appris`) et celles que l'utilisateur désigne (`partager <nom>`) ; jamais une skill qui contient un
secret, ni — pour une skill apprise — du contenu sensible. Coordonnées, chemins du PC et liens d'accès sont retirés du
texte ; un script qui en contient garde la skill privée (on ne réécrit pas du code).

Ce qui arrive (réglage `echange.reception`, actif par défaut pour un membre) :
- le TEXTE d'une skill s'active seul : contrôlé à l'arrivée (`lint` : consigne cachée, téléchargement exécuté,
  commande destructrice, accès aux secrets, réglages de Claude, envoi de données, caractères invisibles), puis soufflé
  quand un message colle à un de ses déclencheurs — marqué 🤝, présenté comme une méthode proposée par un ami et non
  comme un ordre. Une skill qui échoue au contrôle reste en quarantaine jusqu'à ce que l'utilisateur l'adopte ;
- un SCRIPT ne s'active jamais seul : il tournerait sur le PC de celui qui le reçoit. Il attend son oui
  (`approuver <ami/skill> --oui`), donné sur une empreinte : la copie approuvée est figée hors du dépôt commun, et un
  script modifié par son auteur redemande l'accord ;
- les DÉCLENCHEURS voyagent aussi : ceux qu'un ami a appris pour une skill de plugin que j'ai (ajoutés à mes réglages,
  retirables d'un coup), et ceux qu'un auteur a appris pour sa propre skill partagée (ils la suivent dans l'index, sans
  toucher à mes réglages). Des mots seulement, jamais une phrase qui désigne déjà une de mes skills.

Le dossier d'un ami est une donnée, pas une source sûre — n'importe quel membre du dépôt peut y écrire n'importe quoi :
- liste fermée : un dossier de skill reçu ne contient que du texte et des scripts au nom simple ; un lien, un fichier
  caché ou d'un autre type le met en quarantaine (le texte de la skill pourrait y renvoyer) ;
- rien de ce qu'un ami a écrit n'entre tel quel dans une ligne lue par Claude : pseudos et noms de skills ont une forme
  imposée, la description est citée et nettoyée, le nom d'un fichier n'est jamais recopié, la description d'une skill
  en quarantaine n'est affichée nulle part ;
- temps borné : parcours et lectures plafonnés (WALK_MAX, SIG_BUDGET, BUILD_BYTES…), contrôle en temps linéaire ;
- jamais de contrôle dans un hook : l'index des skills reçues est refait en tâche de fond (après chaque synchro, ou à
  la demande d'un hook qui le trouve périmé) ; un hook ne lit que son résultat, et ne se fie pas à un verdict rendu
  sur un contenu qui a changé depuis ;
- un accord (adopter, approuver) porte sur l'empreinte de ce qui a été montré, et la copie est faite des octets
  contrôlés, pas d'une relecture.
Limite connue : les pseudos ne sont pas authentifiés (un membre peut écrire dans le dossier d'un autre) ; le dépôt
commun reste un cercle de confiance, et ces contrôles en limitent les dégâts.

Python seul, sur toutes les plateformes (voir plus.py).

Découpage du 21/11/2026, sans changer le comportement : le contrôle d'un texte et des fichiers d'une skill est dans
echange_controle, la réception des skills des amis (index, réflexe, usage) dans echange_reception ; leurs noms restent
accessibles ici (`echange.lint_text`, `from .echange import safe_rel`…, __getattr__), chargés à la demande."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from .common import (BRAIN_DIR, CMD, CODE_DIR, PLUGIN, STATE_DIR, FileLock, days_since, fmt_date, fold, load_config, log,
                     now_iso, parse_iso, read_json, set_config, short, update_config, write_json)

SKILLS, MANIFEST = "skills", "skill.json"
TRIGGERS, USAGE, FEEDBACK = "declencheurs.json", "usage.json", "retours.json"
ADOPTED = ".cerveau-commun"  # dans ~/.claude/skills/<nom>/ : skill adoptée d'un ami
SOURCE = "commun"  # les skills reçues s'appellent « commun:<nom> » dans le réflexe
INDEX = STATE_DIR / "echange_index.json"
STATE = STATE_DIR / "echange.json"
APPROVED = BRAIN_DIR / "echange" / "approuves"  # copie figée des skills dont l'utilisateur a approuvé les scripts
TEXT_EXT = (".md", ".txt", ".json", ".csv", ".yaml", ".yml", ".toml", ".html", ".css")
SCRIPT_EXT = (".py", ".js", ".mjs", ".ts", ".sh", ".ps1", ".bat", ".cmd", ".rb", ".php")
MAX_FILES, MAX_FILE, MAX_TOTAL = 40, 200_000, 600_000
WALK_MAX = 400  # entrées (fichiers et dossiers) parcourues dans un dossier de skill avant d'abandonner
FRIENDS_MAX, SKILLS_MAX = 60, 80  # amis lus, skills lues par ami
MEMBERS_SCAN, SKILLS_SCAN = 2000, 300  # entrées listées dans membres/ et dans skills/ d'un ami ; au-delà : ignoré
# Entrées regardées pour l'empreinte de l'index : par membre (80 skills de 40 fichiers y tiennent), et pour tous les amis.
FRIEND_BUDGET, SIG_BUDGET = 4000, 12000
BUILD_SKILLS, BUILD_BYTES = 300, 20_000_000  # skills et octets contrôlés par reconstruction de l'index
USAGE_MAX = 400  # skills reçues dont l'usage est compté
# Chemin d'un fichier partagé : lettres sans accent, chiffres, tiret, point, souligné (5 niveaux au plus). Ce nom est
# affiché à celui qui reçoit, dans des lignes que Claude lit : il ne doit rien pouvoir « dire ».
SAFE_REL = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}(?:/[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}){0,4}")
REF_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*")  # « ami/skill »
# Noms que Windows réserve (avec ou sans extension) : Git pour Windows refuse d'extraire un tel chemin, et la synchro du
# dépôt commun échouerait chez chaque membre sous Windows.
_WIN_RESERVED = re.compile(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", re.I)
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_PHRASE = re.compile(r"[^\W\d_]+(?:[ '’-][^\W\d_]+)*")  # déclencheur reçu d'un ami : des mots, rien d'autre
SESSION_CAP = 3  # skills reçues soufflées par session
PROVEN_MEMBERS, PROVEN_USES = 2, 3  # « a fait ses preuves » : suivie par 2 membres, ou 3 fois
INDEX_V = 2


# ------------------------------------------------------------------------------------------ réglages et état
def settings(cfg=None) -> dict:
    d = (cfg or load_config()).get("echange")
    return d if isinstance(d, dict) else {}


def sending(cfg=None):
    """« oui », « non », ou None tant que l'utilisateur n'a pas répondu."""
    v = settings(cfg).get("envoi")
    return v if v in ("oui", "non") else None


def receiving(cfg=None) -> bool:
    return settings(cfg).get("reception", "oui") != "non"


def me() -> str:
    from . import commun
    return commun.member()


def commun_root() -> Path:
    from . import commun
    return Path(commun.settings()["path"])


def _members_dir() -> Path:
    from . import commun
    return commun_root() / commun.MEMBERS


def state() -> dict:
    d = read_json(STATE, {}) or {}
    return d if isinstance(d, dict) else {}


def _edit(change) -> dict:
    with FileLock(str(STATE) + ".lock", timeout=2.0, stale=15.0, strict=False):
        d = state()
        change(d)
        write_json(STATE, d)
    return d


def _sha(data) -> str:
    return hashlib.sha256(data).hexdigest()


def _recent(stamp, seconds) -> bool:
    """`stamp` date de moins de `seconds` secondes. Une date dans le futur (horloge reculée, changement d'heure) ne
    compte pas : elle ne bloque rien."""
    d = parse_iso(stamp)
    return d is not None and 0 <= (_dt.datetime.now() - d).total_seconds() < seconds


def safe_rel(rel) -> bool:
    """Chemin relatif acceptable dans l'échange : forme simple (SAFE_REL), et utilisable sur toutes les plateformes
    (ni nom réservé par Windows, ni point final)."""
    return bool(SAFE_REL.fullmatch(rel)) and not any(part.endswith(".") or _WIN_RESERVED.fullmatch(part)
                                                     for part in rel.split("/"))


def _show(name) -> str:
    """Un nom de fichier de chez moi, affichable même s'il n'est pas de l'UTF-8 valide."""
    return str(name).encode("utf-8", "replace").decode("utf-8")


# ------------------------------------------------------------------------------------------ mes skills (envoi)
def local_skills() -> list:
    """Skills personnelles d'ici → [{"name", "dir", "appris"}] : ni celles d'un plugin ou du compte claude.ai, ni les
    copies posées par le cerveau classique, ni celles adoptées d'un ami."""
    from .apprendre import MARK
    from .skills import COPY_MARK, NAME_RE, SKILLS_DIR
    out = []
    try:
        dirs = sorted(d for d in SKILLS_DIR.iterdir() if d.is_dir() and not d.is_symlink())
    except OSError:
        return out
    for d in dirs:
        if d.name == "synced" or d.name[:1] in "._" or not NAME_RE.match(d.name) or not (d / "SKILL.md").is_file():
            continue
        if (d / COPY_MARK).exists() or (d / ADOPTED).exists():
            continue
        out.append({"name": d.name, "dir": d, "appris": (d / MARK).exists()})
    return out


def plan(cfg=None) -> dict:
    """Ce qui partirait de mes skills → {"partent": {nom: (fichiers publics, scripts, appris)}, "privees": {nom: raison},
    "avis": {nom: ce que le contrôle à l'arrivée lui reprochera chez mes amis}}."""
    from .echange_controle import collect, public_files
    from .echange_reception import _content_reasons
    e = settings(cfg)
    keep, share = set(e.get("garder") or []), set(e.get("partager") or [])
    out = {"partent": {}, "privees": {}, "avis": {}}
    for s in local_skills():
        name = s["name"]
        if name in keep:
            out["privees"][name] = "gardée pour toi"
            continue
        if not s["appris"] and name not in share:
            out["privees"][name] = f"écrite à la main : la partager avec `{CMD} echange partager {name}`"
            continue
        if _WIN_RESERVED.fullmatch(name):
            out["privees"][name] = "son nom est réservé par Windows (tes amis sous Windows ne pourraient plus synchroniser)"
            continue
        files, scripts, problems = collect(s["dir"])
        public, why = public_files(files, scripts, strict=name not in share) if not problems else ({}, [])
        if problems or why:
            out["privees"][name] = "; ".join(problems + why)
            continue
        out["partent"][name] = (public, [r for r in scripts if r in public], s["appris"])
        held = _content_reasons(public, scripts)
        if held:
            out["avis"][name] = " ; ".join(held)[:300]
    return out


def _held_line(name, why) -> str:
    return (f"  ⚠ {name} : chez tes amis, elle attendra en quarantaine ({why}) — normal pour une skill qui installe, "
            "supprime ou règle quelque chose : ils l'adoptent après l'avoir lue")


def _description(data) -> str:
    from .skills import frontmatter
    try:
        return " ".join((frontmatter(data.decode("utf-8", "replace"))[0].get("description") or "").split())
    except Exception:
        return ""


def _write_if_changed(path, data) -> bool:
    try:
        if path.read_bytes() == data:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def _json_bytes(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def shared_triggers(cfg, mine) -> dict:
    """Déclencheurs que j'ai ajoutés (appris ou posés avec `skill trig`), pour les skills que d'autres peuvent avoir :
    celles d'un plugin (« plugin:skill ») et celles que je partage. Jamais ceux reçus d'un ami, ni une phrase sensible,
    longue ou qui contient un chiffre ou une coordonnée."""
    from . import commun
    trig = ((cfg.get("skills") or {}).get("triggers") or {})
    got = settings(cfg).get("declencheurs_recus") or {}
    out = {}
    for skill, phrases in sorted(trig.items()):
        if not isinstance(phrases, list) or not (":" in skill or skill in mine) or skill.startswith(f"{SOURCE}:"):
            continue
        key = f"{SOURCE}:{skill}" if skill in mine else skill
        ok = [p for p in phrases if isinstance(p, str) and 3 <= len(p) <= 60 and len(p.split()) <= 6
              and not re.search(r"\d", p) and commun.clean(p) == p and not commun.sensitive(p)
              and fold(p) not in {fold(x) for x in got.get(skill) or []}]
        if ok:
            out[key] = ok[:12]
    return out


def export(cfg=None) -> dict:
    """Écrit ma part d'échange dans membres/<moi>/ (seulement ce qui change ; ce qui n'est plus partagé s'en va).
    → {"skills": [noms], "privees": {nom: raison}, "ecrits": n, "retires": n}. Rien sans accord d'envoi."""
    from .echange_controle import _signature
    cfg = cfg or load_config()
    who = me()
    rep = {"skills": [], "privees": {}, "ecrits": 0, "retires": 0}
    if not who:
        return rep
    root = _members_dir() / who
    base = root / SKILLS
    if sending(cfg) != "oui":
        if sending(cfg) == "non":  # accord retiré : ce qui avait été envoyé s'en va
            for p in (base, root / TRIGGERS, root / USAGE, root / FEEDBACK):
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                    rep["retires"] += 1
                elif p.exists():
                    p.unlink()
                    rep["retires"] += 1
        return rep
    pl = plan(cfg)
    rep["privees"] = pl["privees"]
    proposed = set(settings(cfg).get("proposees") or [])
    for name, (files, scripts, appris) in sorted(pl["partent"].items()):
        folder = base / name
        sig = _signature(files)
        old = read_json(folder / MANIFEST, {}) or {}
        manifest = {"v": 1, "nom": name, "par": who, "appris": bool(appris), "sig": sig,
                    "maj": old.get("maj") if old.get("sig") == sig and old.get("maj") else now_iso(),
                    "resume": short(_description(files.get("SKILL.md", b"")), 300), "scripts": sorted(scripts),
                    "fichiers": {rel: _sha(data) for rel, data in sorted(files.items())},
                    "propose": name in proposed}
        for rel, data in files.items():
            rep["ecrits"] += _write_if_changed(folder / rel, data)
        rep["ecrits"] += _write_if_changed(folder / MANIFEST, _json_bytes(manifest))
        for p in sorted(folder.rglob("*"), reverse=True):  # fichiers retirés de la skill depuis le dernier envoi
            rel = p.relative_to(folder).as_posix()
            if p.is_file() and rel != MANIFEST and rel not in files:
                p.unlink()
                rep["retires"] += 1
            elif p.is_dir() and not any(p.iterdir()):
                p.rmdir()
        rep["skills"].append(name)
    try:
        for d in sorted(base.iterdir()) if base.is_dir() else ():
            if d.is_dir() and d.name not in pl["partent"]:
                shutil.rmtree(d, ignore_errors=True)
                rep["retires"] += 1
    except OSError:
        pass
    trig = shared_triggers(cfg, set(pl["partent"]))
    usage = {ref: int(u.get("suivie") or 0) for ref, u in (state().get("usage") or {}).items()
             if isinstance(u, dict) and u.get("suivie")}
    for name, body in ((TRIGGERS, {"v": 1, "skills": trig} if trig else None),
                       (USAGE, {"v": 1, "suivies": usage} if usage else None)):
        p = root / name
        if body is None:
            if p.exists():
                p.unlink()
                rep["retires"] += 1
        else:
            rep["ecrits"] += _write_if_changed(p, _json_bytes(body))
    try:  # retours techniques : réécrits quand ils changent, ou une fois par semaine (pas un commit par jour pour une date)
        from . import apprendre
        fb = apprendre.feedback()
        old = read_json(root / FEEDBACK, {}) or {}
        same = {k: v for k, v in fb.items() if k != "le"} == {k: v for k, v in old.items() if k != "le"}
        if not same or days_since(old.get("le")) >= 7:
            rep["ecrits"] += _write_if_changed(root / FEEDBACK, _json_bytes(fb))
    except Exception as exc:
        log(f"échange (retours) : {exc!r}")
    return rep


# ------------------------------------------------------------------------------------------ déclencheurs des amis
def import_triggers(cfg=None) -> list:
    """Déclencheurs appris par les amis, pour les skills que j'ai aussi : ajoutés à `skills.triggers` s'ils ne désignent
    aucune autre de mes skills (5 au plus par skill), et notés dans `echange.declencheurs_recus` pour pouvoir les
    retirer d'un coup (`brain echange declencheurs non`). → [(skill, phrase, ami)]."""
    from .echange_reception import _friend_json, _friends, _phrase_ok
    cfg = cfg or load_config()
    e = settings(cfg)
    if not receiving(cfg) or e.get("declencheurs", "oui") == "non":
        return []
    offers = []
    for friend, d in _friends():
        rows = _friend_json(d / TRIGGERS).get("skills")
        for skill, phrases in (list(rows.items())[:200] if isinstance(rows, dict) else ()):
            if not isinstance(skill, str) or skill.startswith(f"{SOURCE}:"):
                continue  # ceux d'une skill partagée par son auteur vont avec elle : voir _author_triggers
            for p in phrases[:12] if isinstance(phrases, list) else ():
                if _phrase_ok(p):
                    offers.append((skill[:140], " ".join(p.split()), friend))
    if not offers:
        return []
    from . import skills
    kc = cfg.get("skills") or {}
    catalog = skills.index(None, kc)
    names = {s["name"] for s in catalog}
    have = {k: {fold(x) for x in v} for k, v in (kc.get("triggers") or {}).items() if isinstance(v, list)}
    got = {k: list(v) for k, v in (e.get("declencheurs_recus") or {}).items() if isinstance(v, list)}
    refused = {fold(x) for x in e.get("declencheurs_refuses") or []}
    new = []
    for skill, phrase, friend in offers:
        if skill not in names or fold(phrase) in have.get(skill, set()) or fold(phrase) in refused \
                or len(got.get(skill, [])) >= 5 or fold(phrase) in {fold(x) for x in got.get(skill, [])}:
            continue  # (déjà reçu puis retiré par l'utilisateur : il ne revient pas)
        g = skills.phrase_groups(phrase)
        if len(g) < 2 or not skills.usable(g):
            continue
        if any(r["strong"] and r["name"] != skill for r in skills.match(phrase, catalog)):
            continue
        new.append((skill, phrase, friend))
        have.setdefault(skill, set()).add(fold(phrase))
        got.setdefault(skill, []).append(phrase)
    if not new:
        return []

    def change(c):
        trig = c.setdefault("skills", {}).setdefault("triggers", {})
        rec = c.setdefault("echange", {}).setdefault("declencheurs_recus", {})
        for skill, phrase, _ in new:
            if phrase not in trig.setdefault(skill, []):
                trig[skill].append(phrase)
            if phrase not in rec.setdefault(skill, []):
                rec[skill].append(phrase)
    update_config(change)
    return new


def drop_triggers() -> str:
    """`brain echange declencheurs non` : retire tous les déclencheurs reçus des amis et n'en prend plus."""
    n = []

    def change(c):
        e = c.setdefault("echange", {})
        rec = e.pop("declencheurs_recus", None) or {}
        trig = (c.get("skills") or {}).get("triggers") or {}
        refused = set(e.get("declencheurs_refuses") or [])
        for skill, phrases in rec.items():
            cur = trig.get(skill) or []
            keep = [p for p in cur if p not in phrases]
            n.append(len(cur) - len(keep))
            refused |= set(phrases)
            if keep:
                trig[skill] = keep
            else:
                trig.pop(skill, None)
        e["declencheurs"] = "non"
        e["declencheurs_refuses"] = sorted(refused)
    update_config(change)
    return f"✓ {sum(n)} déclencheur(s) reçu(s) des amis retiré(s) ; plus aucun ne sera pris (`{CMD} echange declencheurs oui`)"


def allow_triggers() -> str:
    """`brain echange declencheurs oui` : les déclencheurs des amis sont de nouveau pris, y compris ceux qui avaient
    été retirés d'un coup par `declencheurs non`."""
    def change(c):
        e = c.setdefault("echange", {})
        e["declencheurs"] = "oui"
        e.pop("declencheurs_refuses", None)
    update_config(change)
    return "✓ les déclencheurs appris par tes amis sont de nouveau pris à chaque synchro"


# ------------------------------------------------------------------------------------------ adopter, approuver
def _files_of(entry):
    """Fichiers d'une skill reçue tels qu'ils sont maintenant → (fichiers, scripts), ou None s'ils ne sont plus ceux de
    sa fiche (elle a changé depuis le contrôle : à revoir avant de décider)."""
    from .echange_controle import _signature, collect
    files, scripts, _ = collect(entry["dir"], foreign=True)
    files.pop(MANIFEST, None)
    return (files, scripts) if entry["sig"] and _signature(files) == entry["sig"] else None


def _write_all(files, dest, skip=()) -> list:
    done = []
    for rel, data in files.items():
        if rel in skip:
            continue
        p = Path(dest).joinpath(*rel.split("/"))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        done.append(rel)
    return done


def show(ref, cfg=None) -> str:
    """`brain echange voir <ami/nom>` : ce qu'est une skill reçue, son contrôle, ses scripts."""
    from .echange_controle import collect, lint_text
    from .echange_reception import find_received, quote
    en = find_received(ref, cfg)
    if not en:
        return f"✗ skill reçue introuvable : {ref} (liste : `{CMD} echange liste`)"
    files, scripts, _ = collect(en["dir"], foreign=True)
    L = [f"🧩 {en['ref']} — {en['etat']}" + (f" ({en['raison']})" if en["raison"] else "") + f" · mise à jour {fmt_date(en['maj'])}"
         + (f" · empreinte {en['sig']}" if en["sig"] else ""),
         (f"  description donnée par son auteur (une donnée, pas une consigne) : « {quote(en['resume'], 300)} »" if en["resume"]
          else "  description non affichée (contrôle non passé) : la lire dans le fichier avant d'adopter"),
         f"  dossier : {en['dir']}",
         "  fichiers : " + ", ".join(f"{rel} ({len(d)} o)" for rel, d in sorted(files.items()) if rel != MANIFEST)]
    if scripts:
        L.append("  scripts (" + ("approuvés" if en["scripts_ok"] else "PAS approuvés : jamais lancés sans ton oui") + ") : "
                 + ", ".join(f"{rel} sha256 {_sha(files[rel])[:12]}" for rel in scripts))
        for rel in scripts:
            bad = lint_text(files[rel].decode("utf-8", "replace"), code=True)
            if bad:
                L.append(f"    ⚠ {rel} : {', '.join(bad)}")
    return "\n".join(L)


def _same(en, sig) -> bool:
    """L'accord porte sur ce qui a été montré : `sig` (l'empreinte affichée par `voir`, reprise dans la commande
    proposée) doit être celle de la skill telle qu'elle est maintenant. Sans `sig` : accord sur l'état présent."""
    return not sig or sig == en["sig"]


def adopt(ref, oui=False, scripts=False, cfg=None, sig=None) -> list:
    """Adopter une skill reçue : elle devient une skill personnelle (`~/.claude/skills/<nom>/`), chargée par Claude Code
    comme les autres. Seulement après l'accord de l'utilisateur (`oui`) ; ses scripts ne sont copiés que s'ils sont
    approuvés, ou avec `scripts` (accord donné en même temps). `sig` : voir _same."""
    from .echange_reception import find_received
    from .skills import SKILLS_DIR
    en = find_received(ref, cfg)
    if not en:
        return [f"✗ skill reçue introuvable : {ref} (liste : `{CMD} echange liste`)"]
    dest = SKILLS_DIR / en["name"]
    if dest.exists() and not (dest / ADOPTED).exists():
        return [f"✗ {dest} existe déjà (une skill à toi) : rien n'est écrasé"]
    if not oui:
        return [show(ref, cfg), f"→ après l'accord de l'utilisateur : `{CMD} echange adopter {en['ref']} --oui"
                + (f" --empreinte {en['sig']}`" if en["sig"] else "`")
                + (" (ajouter `--scripts` s'il approuve aussi les scripts, après les lui avoir montrés)" if en["scripts"] else "")]
    if not en["sig"]:
        return [f"✗ {en['ref']} n'a pas pu être lue ({en['raison'] or 'dossier illisible'}) : rien à adopter"]
    got = _files_of(en) if _same(en, sig) else None
    if got is None:
        return [f"✗ {en['ref']} a changé depuis qu'elle a été montrée : la revoir (`{CMD} echange voir {en['ref']}`) "
                "avant de l'adopter"]
    files, script_files = got
    with_scripts = bool(en["scripts"]) and (scripts or en["scripts_ok"])
    if en["etat"] == "quarantaine":  # l'utilisateur l'a lue et l'accepte telle qu'elle est : notée sur son empreinte
        set_config(f"echange.acceptees.{en['ref']}", en["sig"])
    if scripts and en["scripts"]:
        res = approve(en["ref"], oui=True, sig=en["sig"])
        if any(line.startswith("✗") for line in res):
            return res
    shutil.rmtree(dest, ignore_errors=True)
    done = _write_all(files, dest, skip=() if with_scripts else script_files)
    write_json(dest / ADOPTED, {"de": en["par"], "le": now_iso(), "sig": en["sig"], "scripts": with_scripts})
    _refresh()
    out = [f"✓ skill « {en['name']} » de {en['par']} adoptée : {dest} ({len(done)} fichier(s)"
           + (", scripts compris)" if with_scripts else ")")]
    if en["scripts"] and not with_scripts:
        out.append(f"  ses scripts ne sont pas copiés (pas approuvés) : `{CMD} echange approuver {en['ref']}`")
    return out


def approve(ref, oui=False, cfg=None, sig=None) -> list:
    """Approuver les scripts d'une skill reçue. Sans `oui` : ce qui serait approuvé (à montrer à l'utilisateur). Avec :
    l'accord est noté sur l'empreinte de chaque script, et la skill est copiée hors du dépôt commun — c'est cette copie
    figée qui sert ; un script modifié ensuite par son auteur redemande l'accord."""
    from .echange_reception import approved_dir, find_received
    en = find_received(ref, cfg)
    if not en:
        return [f"✗ skill reçue introuvable : {ref} (liste : `{CMD} echange liste`)"]
    if not en["scripts"]:
        return [f"· {en['ref']} n'a aucun script : rien à approuver"]
    if not oui:
        return [show(ref, cfg), "Un script tourne sur ton PC avec tes droits : le lire avant d'accepter.",
                f"→ après l'accord de l'utilisateur : `{CMD} echange approuver {en['ref']} --oui --empreinte {en['sig']}`"]
    got = _files_of(en) if _same(en, sig) else None
    if got is None:
        return [f"✗ {en['ref']} a changé depuis qu'elle a été montrée : la revoir (`{CMD} echange voir {en['ref']}`) "
                "avant d'approuver"]
    files, scripts = got
    dest = approved_dir(en)
    shutil.rmtree(dest, ignore_errors=True)
    _write_all(files, dest)  # la copie figée est faite des octets dont l'empreinte est notée, pas d'une relecture
    set_config(f"echange.scripts.{en['ref']}", {rel: _sha(files[rel]) for rel in scripts})
    _refresh()
    return [f"✓ scripts de {en['ref']} approuvés ({', '.join(scripts)}) : copie figée dans {dest}"]


def _refresh() -> None:
    """Un accord vient de changer : l'index est refait tout de suite (les hooks ne le reconstruisent pas eux-mêmes)."""
    from .echange_reception import index
    try:
        index(load_config(), build=True)
    except Exception as exc:
        log(f"échange (index) : {exc!r}")


# ------------------------------------------------------------------------------------------ consentement, choix
def consent(value) -> list:
    v = "oui" if value in ("oui", "yes", True) else "non"
    set_config("echange.envoi", v)
    if v == "non":
        out = ["✓ rien de ce que ton cerveau apprend ne part (skills, déclencheurs, retours techniques) ; ce qui avait été "
               "envoyé est retiré à la prochaine synchro"]
    else:
        out = ["✓ ton cerveau partage avec tes amis les skills qu'il apprend, ses déclencheurs et ses retours techniques "
               f"(jamais une skill écrite à la main sans `{CMD} echange partager <nom>`, jamais un secret)"]
    if me():
        spawn_sync()
    return out


def set_receiving(value) -> str:
    v = "non" if value in ("non", "no", False) else "oui"
    set_config("echange.reception", v)
    return ("✓ les skills de tes amis ne sont plus proposées (elles restent dans le dépôt commun)" if v == "non" else
            "✓ les skills de tes amis sont de nouveau proposées quand un message colle (texte contrôlé, scripts sur accord)")


def _toggle(key, name, on) -> None:
    def change(c):
        cur = c.setdefault("echange", {}).setdefault(key, [])
        if on and name not in cur:
            cur.append(name)
        elif not on and name in cur:
            cur.remove(name)
    update_config(change)


def share(name, on=True) -> str:
    """`partager <nom>` : une skill écrite à la main part aussi (décision de l'utilisateur) ; `--non` : elle ne part plus."""
    if name not in {s["name"] for s in local_skills()}:
        return f"✗ skill personnelle introuvable : {name} (liste : `{CMD} echange apercu`)"
    _toggle("partager", name, on)
    if on:
        _toggle("garder", name, False)
    if me() and sending() == "oui":
        spawn_sync()
    why = plan().get("privees", {}).get(name)
    if on and why:
        return f"⚠ « {name} » marquée à partager, mais elle reste privée : {why}"
    return f"✓ « {name} » : " + ("partagée avec tes amis à la prochaine synchro" if on else "plus partagée d'office")


def keep(name, on=True) -> str:
    """`garder <nom>` : cette skill ne part jamais, même apprise ; `--non` lève la réserve."""
    _toggle("garder", name, on)
    if on:
        _toggle("partager", name, False)
    if me() and sending() == "oui":
        spawn_sync()
    return f"✓ « {name} » : " + ("gardée pour toi (retirée du dépôt commun à la prochaine synchro)" if on else
                                "plus réservée (les règles par défaut s'appliquent)")


def propose(name, on=True) -> str:
    """`proposer <nom>` : je propose ma skill partagée pour le plugin (le propriétaire décide)."""
    if name not in plan().get("partent", {}):
        return f"✗ « {name} » n'est pas partagée : seule une skill partagée peut être proposée pour le plugin"
    _toggle("proposees", name, on)
    if me() and sending() == "oui":
        spawn_sync()
    return f"✓ « {name} » : " + ("proposée pour le plugin (visible du propriétaire à la prochaine synchro)" if on else
                                "proposition retirée")


# ------------------------------------------------------------------------------------------ étage 2 : vers le plugin
def proposals(cfg=None, build=True) -> list:
    """Skills du cerveau commun candidates au plugin : proposées par leur auteur, ou qui ont fait leurs preuves (suivies
    par au moins 2 autres membres, ou 3 fois — l'usage qu'un auteur déclare de sa propre skill ne compte pas).
    → [{"ref", "name", "par", "resume", "membres", "suivies", "propose", "etat"}]. `build` : voir index()."""
    from .echange_reception import _friend_json, _friends, index
    use = {}  # ref → {membre: n}
    who = me()
    members = _friends() + ([(who, _members_dir() / who)] if who else [])
    for friend, d in members:
        rows = _friend_json(d / USAGE).get("suivies")
        for ref, n in (list(rows.items())[:USAGE_MAX] if isinstance(rows, dict) else ()):
            if not isinstance(ref, str) or not REF_RE.fullmatch(ref) or ref.split("/")[0] == friend:
                continue
            try:
                use.setdefault(ref, {})[friend] = max(0, min(int(n), 1000))
            except (TypeError, ValueError, OverflowError):
                continue
    for ref, u in (state().get("usage") or {}).items():  # mon usage des skills des autres, même pas encore exporté
        if who and isinstance(u, dict) and isinstance(u.get("suivie"), int) and REF_RE.fullmatch(str(ref)) \
                and ref.split("/")[0] != who:
            use.setdefault(ref, {})[who] = max(0, min(u["suivie"], 1000))
    idx = index(cfg, build)
    out = []
    for en in (idx.get("skills") or []) + (idx.get("miennes") or []):
        u = {m: n for m, n in use.get(en["ref"], {}).items() if n > 0}
        members_n, total = len(u), sum(u.values())
        if en["propose"] or members_n >= PROVEN_MEMBERS or total >= PROVEN_USES:
            out.append({"ref": en["ref"], "name": en["name"], "par": en["par"], "resume": en["resume"],
                        "membres": members_n, "suivies": total, "propose": en["propose"], "etat": en["etat"],
                        "dir": en["dir"], "sig": en["sig"]})
    return sorted(out, key=lambda r: (-r["membres"], -r["suivies"], r["ref"]))


def promote(ref, dest=None, force=False, cfg=None) -> list:
    """`promouvoir <ami/nom> --vers <dossier>` (propriétaire du plugin) : copie la skill, recontrôlée, dans `skills/` de
    l'arbre de développement ou du clone du dépôt du plugin. Elle arrive chez tous à la version suivante."""
    from .echange_controle import collect, lint_text, public_files
    from .echange_reception import find_received, index
    cfg = cfg or load_config()
    cand = {r["ref"]: r for r in proposals(cfg)}
    row = cand.get(ref) or next((r for r in cand.values() if r["name"] == ref), None)
    if row is None:  # pas (encore) candidate : une skill reçue ou une des miennes, sur décision du propriétaire
        en = find_received(ref, cfg)
        if en is None:
            mine = [m for m in index(cfg).get("miennes") or [] if ref in (m["ref"], m["name"])]
            en = mine[0] if len(mine) == 1 else None
        if en is None:
            return [f"✗ skill introuvable dans le cerveau commun : {ref} (`{CMD} echange propositions`)"]
        row = en
    if dest is None:
        dest = None if PLUGIN else CODE_DIR
    if dest is None:
        return ["✗ donne le dossier du plugin à compléter : `--vers <arbre de développement ou clone du dépôt>`"]
    dest = Path(dest).expanduser()
    if not (dest / "brainkit").is_dir() or not (dest / "skills").is_dir():
        return [f"✗ {dest} n'a pas l'air d'un arbre du cerveau (brainkit/ et skills/ attendus)"]
    target = dest / "skills" / row["name"]
    if target.exists() and not force:
        return [f"✗ {target} existe déjà (`--force` pour la remplacer)"]
    files, scripts, problems = collect(row["dir"], foreign=True)
    files.pop(MANIFEST, None)
    public, why = public_files(files, scripts, strict=True)
    bad = list(problems) + why
    for rel, data in public.items():
        bad += [f"{r} ({rel})" for r in lint_text(data.decode("utf-8", "replace"), code=rel in scripts)]
    if bad and not force:
        return [f"✗ {row['ref']} ne passe pas le contrôle : " + " ; ".join(dict.fromkeys(bad)),
                "  à corriger avec son auteur, ou `--force` après l'avoir relue en entier"]
    shutil.rmtree(target, ignore_errors=True)
    for rel, data in public.items():
        p = target / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    _edit(lambda d: d.setdefault("promues", {}).update({row["ref"]: now_iso()}))
    return [f"✓ skill « {row['name']} » (de {row['par']}) copiée dans {target} ({len(public)} fichier(s)"
            + (f", dont {len(scripts)} script(s) à relire" if scripts else "") + ")",
            "→ à faire avant de publier : la relire, l'ajouter au README (tableau des skills, dans publish.readme), monter "
            f"la version, puis `{CMD} publish` : tous ceux qui ont le plugin la reçoivent à la mise à jour"]


def feedback_all() -> str:
    """`brain echange retours` : les retours techniques de chaque membre (pour améliorer le plugin pour tous)."""
    from .echange_reception import _friend_json, _friends
    from . import apprendre
    who = me()
    rows = [(friend, apprendre.clean_feedback(_friend_json(d / FEEDBACK))) for friend, d in _friends()]
    L = [apprendre.feedback_text(who=" (ici)")]
    L += [apprendre.feedback_text(data=data, who=f" de {friend}") for friend, data in rows if data]
    if not who:
        L.append("(pas membre du cerveau commun : seuls les retours d'ici)")
    return "\n".join(L)


# ------------------------------------------------------------------------------------------ synchronisation
def spawn_sync() -> None:
    """Synchronisation en arrière-plan (BRAIN_COMMUN_FG=1, comme pour le cerveau commun : tout de suite — tests)."""
    if os.environ.get("BRAIN_COMMUN_FG") == "1":
        sync(auto=True)
        return
    from .hooks import spawn_background
    spawn_background(["echange", "sync", "--auto"])


def sync(auto=False) -> list:
    """Export de ma part d'échange, puis synchronisation du cerveau commun (commit, pull, push : commun.sync), puis
    déclencheurs des amis et annonce des nouvelles skills reçues."""
    from . import commun
    who = me()
    if not who:
        return ["· pas membre du cerveau commun : rien à échanger (`brain commun` pour voir)"]
    cfg = load_config()
    out = []
    rep = export(cfg)
    if sending(cfg) == "oui":
        out.append(f"✓ {len(rep['skills'])} skill(s) partagée(s)" + (f" ({', '.join(rep['skills'][:8])})" if rep["skills"] else "")
                   + (f" · {rep['ecrits']} fichier(s) écrit(s), {rep['retires']} retiré(s)" if rep["ecrits"] or rep["retires"] else ""))
    out += commun.sync(pull=True, push=True, auto=auto)
    _edit(lambda d: d.update(sync_le=now_iso()))
    try:
        new = import_triggers(load_config())
        if new:
            from . import apprendre
            apprendre.announce("🤝 Déclencheur(s) appris par tes amis ajoutés à tes skills : "
                               + " · ".join(f"`{s}` « {p} » ({f})" for s, p, f in new[:5])
                               + f" · tous les retirer : `{CMD} echange declencheurs non`")
            out.append(f"✓ {len(new)} déclencheur(s) des amis ajouté(s)")
    except Exception as exc:
        log(f"échange (déclencheurs des amis) : {exc!r}")
    _refresh()  # ce qui vient d'arriver est contrôlé ici, en tâche de fond : les hooks ne lisent que le résultat
    if auto:
        log("échange : " + " | ".join(out))
    return out


def after_learned(name) -> str:
    """Après `brain apprendre skill` : ce qui arrive à cette skill dans l'échange."""
    if not me():
        return ""
    if sending() == "oui":
        spawn_sync()
        return (f"🤝 elle part chez tes amis à la prochaine synchro (texte contrôlé chez eux, scripts sur leur accord) · la "
                f"garder pour toi : `{CMD} echange garder {name}`")
    if sending() is None:
        return (f"🤝 elle peut servir à tes amis : le proposer à l'utilisateur (`{CMD} echange apercu`, puis "
                f"`{CMD} echange oui` s'il accepte)")
    return ""


def on_session_end(cfg=None) -> None:
    """Fin de session : ma part d'échange part en arrière-plan si elle a pu changer (au plus une fois par quart d'heure)."""
    cfg = cfg or load_config()
    if not me() or (sending(cfg) != "oui" and not receiving(cfg)):
        return
    if _recent(state().get("sync_demande"), 900):
        return
    _edit(lambda d: d.update(sync_demande=now_iso()))
    spawn_sync()


# ------------------------------------------------------------------------------------------ notices et état
def notice(cfg=None, take=None) -> str:
    """Lignes du démarrage (chacune une seule fois) : proposition de partager ce que le cerveau apprend, nouvelles skills
    reçues, scripts en attente d'accord, et — pour le propriétaire du plugin — skills qui ont fait leurs preuves.
    `take(ligne)` : la ligne tient-elle sous le plafond de contexte du hook ? Une ligne refusée n'est notée nulle part
    comme montrée : elle attend un prochain démarrage."""
    from .echange_reception import received
    cfg = cfg or load_config()
    if not me() or os.environ.get("CLAUDE_CODE_REMOTE"):
        return ""
    take = take or (lambda line: True)
    st, lines = state(), []
    if sending(cfg) is None and days_since(st.get("propose_le")) >= 7:
        line = ("🤝 Échange de skills : ton cerveau peut aussi partager avec tes amis les skills qu'il apprend, ses "
                "déclencheurs et des compteurs techniques sans texte (jamais une skill écrite à la main sans accord, jamais "
                f"un secret). Propose-le une fois à l'utilisateur avec ce qui partirait (`{CMD} echange apercu`) ; s'il "
                f"accepte : `{CMD} echange oui` ; s'il refuse : `{CMD} echange non`.")
        if take(line):
            _edit(lambda d: d.update(propose_le=now_iso()))
            lines.append(line)
    if receiving(cfg):
        rows = received(cfg, build=False)
        seen = set(st.get("vues") or [])
        fresh = [r for r in rows if r["ref"] not in seen and r["etat"] in ("ok", "quarantaine")]
        if fresh:
            ok = [r for r in fresh if r["etat"] == "ok"]
            held = [r for r in fresh if r["etat"] == "quarantaine"]
            parts = []
            if ok:
                parts.append(f"{len(ok)} skill(s) reçue(s) de tes amis ("
                             + ", ".join(f"« {r['name']} » de {r['par']}" for r in ok[:4]) + ("…" if len(ok) > 4 else "")
                             + ") : soufflées quand un message colle, comme une méthode proposée")
            if held:
                parts.append(f"{len(held)} en quarantaine après contrôle (" + ", ".join(r["ref"] for r in held[:3])
                             + f") : inactives tant que l'utilisateur ne les adopte pas (`{CMD} echange voir <ami/nom>`)")
            waiting = [r["ref"] for r in ok if r["scripts"] and not r["scripts_ok"]]
            if waiting:
                parts.append(f"scripts en attente de son accord : {', '.join(waiting[:3])} (`{CMD} echange approuver <ami/nom>`)")
            line = ("🤝 Échange de skills — " + " · ".join(parts) + f". Détail : `{CMD} echange liste` ; ne plus en "
                    f"recevoir : `{CMD} echange recevoir non`. À dire à l'utilisateur en une phrase.")
            if take(line):
                _edit(lambda d: d.update(vues=sorted(seen | {r["ref"] for r in fresh})[-300:]))
                lines.append(line)
    if not PLUGIN or (cfg.get("publish") or {}).get("dir"):  # propriétaire du plugin : arbre de développement ou clone
        try:
            known = set(st.get("propositions_vues") or [])
            new = [r for r in proposals(cfg, build=False)
                   if r["ref"] not in known and r["ref"] not in (st.get("promues") or {})]
            if new:
                line = ("🧩 Pour le plugin : " + ", ".join(
                    f"« {r['name']} » de {r['par']}" + (" (proposée)" if r["propose"] else f" (suivie {r['suivies']}× par {r['membres']} membre(s))")
                    for r in new[:4]) + f" — à dire à l'utilisateur ; `{CMD} echange propositions`, puis "
                    f"`{CMD} echange promouvoir <ami/nom>` s'il veut la donner à tous.")
                if take(line):
                    _edit(lambda d: d.update(propositions_vues=sorted(known | {r["ref"] for r in new})[-300:]))
                    lines.append(line)
        except Exception as exc:
            log(f"échange (propositions) : {exc!r}")
    return "\n".join(lines)


def preview(cfg=None) -> str:
    """`brain echange apercu` : ce qui partirait (et ce qui reste privé, avec la raison)."""
    cfg = cfg or load_config()
    pl = plan(cfg)
    L = [f"🤝 Échange — ce qui partirait de ton cerveau vers tes amis : {len(pl['partent'])} skill(s)"]
    for name, (files, scripts, appris) in sorted(pl["partent"].items()):
        L.append(f"  + {name} ({'apprise par le cerveau' if appris else 'partagée par toi'}, {len(files)} fichier(s)"
                 + (f", {len(scripts)} script(s) : chez eux, en attente de leur accord" if scripts else "") + ")")
    for name, why in sorted(pl["avis"].items()):
        L.append(_held_line(name, why))
    for name, why in sorted(pl["privees"].items()):
        L.append(f"  · {name} reste privée — {why}")
    trig = shared_triggers(cfg, set(pl["partent"]))
    if trig:
        L.append("Déclencheurs : " + " · ".join(f"`{k}` {', '.join(f'« {p} »' for p in v[:3])}" for k, v in list(trig.items())[:6]))
    L.append("Retours techniques (compteurs seulement) : version, système, pannes et lenteurs des hooks, précision du "
             f"réflexe, délégation — `{CMD} apprendre retours` les montre.")
    L.append("Jamais : un secret, tes souvenirs (règles du cerveau commun inchangées), le texte de tes sessions, une skill "
             "écrite à la main sans ton accord. Coordonnées, chemins du PC, liens d'accès et prénom retirés du texte.")
    L.append({"oui": f"Envoi : accepté · arrêter : `{CMD} echange non`", "non": f"Envoi : refusé · accepter : `{CMD} echange oui`",
              None: f"Envoi : pas encore décidé → `{CMD} echange oui` (après l'accord de l'utilisateur) ou `{CMD} echange non`"}[sending(cfg)])
    return "\n".join(L)


def listing(cfg=None) -> str:
    from .echange_reception import quote, received
    cfg = cfg or load_config()
    if not me():
        return "· pas membre du cerveau commun : aucune skill reçue (`brain commun` pour voir)"
    rows = received(cfg)
    usage = state().get("usage") or {}
    L = [f"🧩 Skills reçues de tes amis ({len(rows)})" + ("" if receiving(cfg) else " — réception coupée")]
    for r in sorted(rows, key=lambda r: (r["etat"] != "ok", r["ref"])):
        u = usage.get(r["ref"]) or {}
        tag = {"ok": "✅", "quarantaine": "⏸", "masquee": "·"}[r["etat"]]
        L.append(f"- {tag} {r['ref']}" + (f" — {r['raison']}" if r["raison"] else "")
                 + (f" · scripts {'approuvés' if r['scripts_ok'] else 'en attente de ton accord'}" if r["scripts"] else "")
                 + f" · soufflée {u.get('soufflee', 0)}×, suivie {u.get('suivie', 0)}×")
        if r["resume"]:
            L.append(f"    son auteur la décrit ainsi : « {quote(r['resume'], 150)} »")
    pl = plan(cfg)
    L.append(f"Tes skills partagées ({len(pl['partent'])}) : " + (", ".join(sorted(pl["partent"])) or "aucune")
             + ("" if sending(cfg) == "oui" else " — envoi pas accepté, rien ne part"))
    L += [_held_line(name, why) for name, why in sorted(pl["avis"].items())]
    L.append(f"`{CMD} echange voir|adopter|approuver <ami/nom>` · `{CMD} echange partager|garder|proposer <nom>`")
    return "\n".join(L)


def status(cfg=None) -> str:
    from .echange_reception import received
    cfg = cfg or load_config()
    who = me()
    if not who:
        return ("🤝 Échange de skills : réservé aux membres du cerveau commun (`brain commun` pour le rejoindre). Les skills "
                f"apprises restent ici ; `{CMD} echange apercu` montre ce qui partirait.")
    rows = received(cfg)
    ok = sum(1 for r in rows if r["etat"] == "ok")
    held = sum(1 for r in rows if r["etat"] == "quarantaine")
    pl = plan(cfg)
    st = state()
    return "\n".join([
        f"🤝 Échange de skills — membre « {who} » · envoi : {sending(cfg) or 'pas encore décidé'} · réception : "
        f"{'oui' if receiving(cfg) else 'non'}",
        f"  reçues : {ok} active(s), {held} en quarantaine · partagées : {len(pl['partent'])} "
        f"({', '.join(sorted(pl['partent'])[:6]) or 'aucune'}) · dernière synchro : {fmt_date(st.get('sync_le'))} "
        f"{str(st.get('sync_le') or '')[11:16]}",
        f"  `{CMD} echange liste` (reçues et envoyées) · `apercu` (ce qui partirait) · `oui`/`non` (envoi) · `recevoir "
        "oui|non` · `partager|garder|proposer <nom>` · `voir|adopter|approuver <ami/nom>` · `propositions` · "
        "`promouvoir <ami/nom> --vers <dossier>` · `retours` · `sync`"])


# Noms déplacés par le découpage du 21/11/2026 : toujours accessibles ici (`echange.<nom>`,
# `from .echange import <nom>`), chargés à la demande depuis leur module.
_PARTS = {
    "echange_controle": frozenset("""
        CODE_ONLY LINT_MAX _BLOB _COMMANDS_SRC _INJECTION_SRC _INVISIBLE _NEG _PRUNED _SPAN _TABLES _code_parts
        _hidden_comment _read_capped _signature _table _walk collect lint_text public_files
    """.split()),
    "echange_reception": frozenset("""
        _author_triggers _blank _bump _check _content_reasons _friend_json _friends _index_sig _inside _json_obj
        _own_names _phrase_ok _request_index _scan _skill_dirs _strings _tree_sig _trigger_stats approved_dir
        find_received followed hint_line index quote received reflex
    """.split()),
}


def __getattr__(name):
    """Un nom déplacé est cherché dans son module la première fois, puis gardé ici ; un nom inconnu reste une
    AttributeError, comme avant."""
    for part, names in _PARTS.items():
        if name in names:
            import importlib
            value = globals()[name] = getattr(importlib.import_module(f".{part}", __package__), name)
            return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
