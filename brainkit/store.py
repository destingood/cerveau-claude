"""Graphe de mémoire : nœuds typés (profil, règles, projets, décisions…) + liens, stockés dans graph.json — ou, en
mode wiki (wikistore.py), dans les pages Markdown du wiki, dont graph.json n'est plus que le cache."""
from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import time

from .common import (BRAIN_DIR, GRAPH_FILE, STATE_DIR, FileLock, clean_label, commun_member, days_since, fold, jaccard,
                     log, norm_path, now_iso, path_within, read_json, slugify, tokenize, write_json)

TYPES = {
    "user": "Profil",
    "feedback": "Règle",
    "project": "Projet",
    "decision": "Décision",
    "fact": "Fait",
    "learning": "Apprentissage",
    "reference": "Référence",
    "entity": "Entité",
    "todo": "À faire",
    # pages de savoir du wiki (façon « LLM Wiki ») : écrites par Claude à partir des sources
    "source": "Source",
    "concept": "Concept",
    "topic": "Sujet",
    "analysis": "Analyse",
}
TYPE_ALIASES = {
    "u": "user", "profil": "user", "profile": "user", "moi": "user", "utilisateur": "user",
    "f": "feedback", "regle": "feedback", "rule": "feedback", "pref": "feedback", "preference": "feedback",
    "consigne": "feedback",
    "p": "project", "projet": "project",
    "d": "decision", "choix": "decision",
    "fait": "fact", "info": "fact", "note": "fact", "contexte": "fact", "etat": "fact", "state": "fact",
    "l": "learning", "apprentissage": "learning", "lesson": "learning", "lecon": "learning", "fix": "learning",
    "bug": "learning", "piege": "learning", "astuce": "learning", "tip": "learning",
    "r": "reference", "ref": "reference", "lien": "reference", "link": "reference", "doc": "reference",
    "ressource": "reference",
    "e": "entity", "entite": "entity", "outil": "entity", "tool": "entity", "personne": "entity",
    "contact": "entity",
    "t": "todo", "tache": "todo", "afaire": "todo", "task": "todo",
    "src": "source", "article": "source", "lecture": "source",
    "idee": "concept", "notion": "concept", "methode": "concept", "theme": "concept",
    "sujet": "topic", "synthese": "topic", "apercu": "topic", "these": "topic",
    "analyse": "analysis", "comparaison": "analysis", "comparatif": "analysis", "etude": "analysis",
}
RELATIONS = ("relates", "part_of", "depends_on", "uses", "fixes", "supersedes", "contradicts", "about")
LOCK_FILE = BRAIN_DIR / ".graph.lock"
_HELD = []  # non vide : ce processus tient LOCK_FILE (Brain.edit)
RECENT_NODES = 300  # souvenirs touchés par une écriture, au plus, notés dans history/recents.jsonl
# Compteurs de rappel (montré, utilisé) en attente : un petit fichier à part, que chaque lecture du graphe applique et
# que la prochaine écriture du graphe absorbe. Avant, chaque rappel réécrivait tout graph.json (−116 ms sur 387 à
# 10 000 souvenirs) et rendait périmés l'index BRAIN.md et la vue 3D.
COUNTERS_FILE = STATE_DIR / "compteurs.json"
COUNTERS_LOCK = STATE_DIR / "compteurs.lock"
WIKILINK = re.compile(r"\[\[([^\]|#\n]{1,80})(?:[|#][^\]\n]{0,300})?\]\]")  # cible ≤ 80, texte affiché libre
GLOBAL_REFS = ("none", "aucun", "global", "-")


def normalize_type(value) -> str:
    key = fold(value or "learning").strip()
    if key in TYPES:
        return key
    if key in TYPE_ALIASES:
        return TYPE_ALIASES[key]
    raise ValueError(f"type inconnu « {value} » — types : {', '.join(TYPES)}")


def clean_tags(tags) -> list:
    if isinstance(tags, str):
        tags = re.split(r"[,;]", tags)
    out = []
    for tag in tags or []:
        tag = slugify(tag, 30)
        if tag and tag != "n" and tag not in out:
            out.append(tag)
    return out[:12]


def clamp_importance(value) -> int:
    try:
        return max(1, min(5, int(value)))
    except (TypeError, ValueError):
        return 3


SOURCES = {"user": 0.9, "utilisateur": 0.9, "verifie": 0.95, "verified": 0.95, "obsidian": 0.9,
           "wiki": 0.8, "claude": 0.7, "mcp": 0.7, "import": 0.7, "auto": 0.6, "deduit": 0.5, "inference": 0.5}


def normalize_source(value) -> str:
    v = fold(value or "claude").strip()
    return {"user": "utilisateur", "dit": "utilisateur", "verified": "verifie", "verif": "verifie",
            "inference": "deduit", "suppose": "deduit"}.get(v, v or "claude")


def confidence(node) -> float:
    """Confiance (façon provenance) : selon la source, + quand un fait est redit, − quand il est contredit."""
    meta = node.get("meta") or {}
    if isinstance(meta.get("conf"), (int, float)):
        return max(0.05, min(1.0, float(meta["conf"])))
    return SOURCES.get(normalize_source(node.get("source")), 0.7)


def shown_since(node) -> int:
    """Affichages comptés depuis le début de la mesure d'usage (v6) : les rappels d'avant ne disent rien de l'usage."""
    return max(0, (node.get("hits", 0) or 0) - ((node.get("meta") or {}).get("hits0") or 0))


def usage(node) -> float:
    """Montré ≠ utilisé : (utilisé + 1) / (montré + 2), atténué si plus servi depuis longtemps (μ = 45 j)."""
    import math
    shown, used = shown_since(node), node.get("used", 0) or 0
    age = days_since(node.get("last_used") or node.get("updated"))
    return min(1.0, (used + 1) / (shown + 2)) * math.exp(-min(age, 3650) / 45)


def priority(node) -> float:
    """Ordre d'affichage : importance (pondérée par la confiance), usage réel (et pas seulement montré), fraîcheur."""
    p = node.get("importance", 3) * 10 * (0.85 + 0.15 * confidence(node))
    p += 20 * usage(node) + min(node.get("used", 0) or 0, 10)
    age = days_since(node.get("updated"))
    p += 8 if age < 3 else 5 if age < 14 else 2 if age < 60 else 0
    return p


_NO_ABS = ("feedback", "user")  # règles et profil : « demain », « dans 3 jours » y sont génériques


def _absolutize_new(old, new):
    """Dates relatives → absolues, seulement dans les lignes nouvelles (une vieille ligne garde sa date d'origine)."""
    from .dates import absolutize
    old_lines = set(str(old or "").splitlines())
    return "\n".join(line if line in old_lines else absolutize(line) for line in str(new).split("\n"))


def load_graph():
    """Lecture sûre de graph.json : réessaie si Windows le verrouille un instant (remplacement en cours), répare
    s'il est corrompu, et ne renvoie JAMAIS un graphe vide à la place d'un fichier existant mais illisible
    (sinon la prochaine écriture effacerait tout le cerveau).
    Mode wiki : les pages du wiki font foi, graph.json n'en est que le cache (reconstruit s'il est abîmé)."""
    return _load_graph()[0]


def _load_graph():
    """load_graph() → (données, empreinte du fichier lu : taille, date, n° de fichier et CRC de ses octets). L'empreinte
    dit à elle seule ce que contient le cerveau, tant qu'il n'est pas modifié en mémoire (voir Brain.stamp) : None
    quand les données ne sont pas graph.json lu tel quel (wiki, réparation, fichier absent)."""
    from . import wikistore
    mode, root = wikistore.resolve()
    if mode == "wiki":
        return wikistore.load(root), None
    if mode == "missing":
        return wikistore.load_missing(root), None
    if not GRAPH_FILE.exists():
        return None, None
    last = None
    for attempt in range(10):
        try:
            with open(GRAPH_FILE, "rb") as fh:
                raw = fh.read()
                st = os.fstat(fh.fileno())  # le fichier lu, même si un autre processus le remplace entre-temps
            data = json.loads(raw.decode("utf-8"))
            if not (isinstance(data, dict) and isinstance(data.get("nodes"), dict)):
                # JSON valide mais pas un cerveau ({"nodes": []}, null, []…) : réparé comme un fichier abîmé. Avant,
                # le cerveau repartait vide et la première écriture remplaçait le fichier, sans aucune copie.
                raise ValueError("graph.json n'a pas la forme d'un cerveau")
            if data.pop("wiki", None) is not None:
                log("wiki débranché (config wiki.path vide) : le cerveau repart en classique depuis son dernier cache")
                return data, None
            return data, _stamp(raw, st)
        except ValueError:  # JSON abîmé : réparé sans perdre ce qui est lisible (reparation.py), l'original gardé
            from . import reparation
            data = reparation.repair(raw)
            if data is None:
                raise RuntimeError("graph.json illisible, et ni instantané, ni sauvegarde, ni souvenir lisible dans le "
                                   "fichier pour le réparer")
            return data, None
        except OSError as exc:  # verrou passager
            last = exc
            time.sleep(0.03 * (attempt + 1))
    raise RuntimeError(f"graph.json inaccessible : {last!r}")


def _stamp(raw, st) -> str:
    """Empreinte d'un graph.json lu : taille, date, n° de fichier, et CRC de ses octets (deux écritures de même taille
    dans le même tic d'horloge du disque restent distinctes)."""
    import zlib
    return f"{len(raw)}:{st.st_mtime_ns}:{st.st_ino}:{zlib.crc32(raw):08x}"


def graph_stamp():
    """Empreinte de graph.json tel qu'il est sur le disque, comme Brain.stamp, sans analyser le JSON (quelques ms au lieu
    de 15 à 60) ; None hors cerveau classique (wiki : les pages font foi) ou s'il est illisible."""
    from . import wikistore
    if wikistore.resolve()[0] != "classic":
        return None
    try:
        with open(GRAPH_FILE, "rb") as fh:
            return _stamp(fh.read(), os.fstat(fh.fileno()))
    except OSError:
        return None


class ReadOnly(RuntimeError):
    """Page d'un ami (cerveau commun) : lecture seule."""


def _may_reach(a: set, b: set, threshold: float) -> bool:
    """Faux seulement si jaccard(a, b) est sûrement sous le seuil (borne des tailles) : aucune paire ne se perd."""
    if not a or not b:
        return False
    small, big = (len(a), len(b)) if len(a) <= len(b) else (len(b), len(a))
    return small >= threshold * big


def _foreign(nid) -> bool:
    return str(nid or "").startswith("c--")


def replace_all(data):
    """Le cerveau entier devient `data` (restauration d'un instantané ou d'une sauvegarde), sous verrou. Mode wiki :
    les pages sont réécrites, déplacées ou retirées pour correspondre (git garde l'état d'avant)."""
    from . import wikistore
    mode, root = wikistore.resolve()
    with FileLock(LOCK_FILE, timeout=6.0):
        if mode == "classic":
            from . import history
            write_json(GRAPH_FILE, data)
            history.restart()  # la réparation repartira de cet état, pas de celui qu'on vient de quitter
        elif mode == "missing":
            raise wikistore.WikiMissing(f"wiki introuvable : {root}")
        else:
            wikistore.replace_all(data)


class Brain:
    def __init__(self, data=None):
        loaded = data is None
        stamp = None
        if loaded:
            data, stamp = _load_graph()
        if not isinstance(data, dict) or not isinstance(data.get("nodes"), dict):
            data, stamp = {"version": 1, "created": now_iso(), "nodes": {}, "edges": []}, None
        data.setdefault("edges", [])
        self.data = data
        self.dirty = False
        self._sim_cache = None
        self._adj = None
        self._counted = None
        if loaded:  # compteurs de rappel en attente : chaque lecteur voit les mêmes nombres qu'avant
            try:
                self._counted = _fold_counters(self.data)
            except Exception as exc:
                log(f"compteurs : {exc!r}")
        if loaded and commun_member():  # cerveau commun : les pages des amis entrent dans le graphe, en lecture seule
            from . import commun
            try:
                commun.merge_foreign(self.data)
            except Exception as exc:
                from .common import log as _log
                _log(f"commun : pages des amis : {exc!r}")
        else:  # (non-membre : commun.py n'est pas chargé)
            self.stamp = stamp
        # Ce que la prochaine écriture note dans history/recents.jsonl : souvenirs touchés depuis cet instant, liens
        # ajoutés après les _e0 premiers, suppressions définitives.
        self._t0, self._e0, self._purged = now_iso(), len(self.edges), set()

    # Empreinte de graph.json tel qu'il a été lu (_load_graph), tant que ce cerveau n'est pas modifié : l'index des
    # souvenirs (search.memory_index) et le projet d'un dossier (hooks.project_of) s'en servent pour ne pas tout relire
    # à chaque message. Toute modification passe par `dirty = True` (méthodes ci-dessous, et le code qui touche aux
    # nœuds directement, pour qu'ils soient enregistrés) : l'empreinte et ce qui en découle tombent alors. None : rien à
    # reprendre (cerveau construit en mémoire, wiki, pages d'amis, modifié). Les compteurs de rappel en attente
    # (compteurs.json, appliqués à la lecture) n'y entrent pas : ni l'index ni les projets n'en dépendent.
    # _memsig : l'empreinte du savoir, calculée une fois pour ce cerveau.
    stamp = _memsig = None

    @property
    def dirty(self) -> bool:
        return self._dirty

    @dirty.setter
    def dirty(self, value):
        self._dirty = value
        if value:
            self.stamp = self._memsig = None

    @classmethod
    def load(cls):
        return cls()

    @classmethod
    @contextlib.contextmanager
    def edit(cls, timeout=6.0):
        """Lecture-modification-écriture sous verrou (plusieurs sessions peuvent tourner en parallèle)."""
        with FileLock(LOCK_FILE, timeout=timeout):
            _HELD.append(1)  # une réparation faite pendant la lecture n'attend pas le verrou qu'on tient déjà
            try:
                brain = cls()
            finally:
                _HELD.pop()
            yield brain
            if brain.dirty:
                brain.save()

    def save(self):
        from . import history
        history.snapshot("auto")  # état d'avant la modification (au plus un toutes les 30 min)
        self.data["updated"] = now_iso()
        counted = self._counted
        if counted and counted[2]:  # compteurs en attente appliqués à la lecture : ce graphe les contient désormais
            self.data["compteurs"] = {"id": counted[0], "n": counted[1]}
        data = self._own_data()
        if data.get("wiki"):  # mode wiki : les pages qui changent, puis le cache
            from . import wikistore
            wikistore.save(data)
            self.data["wiki"] = data["wiki"]
            self._stems = None
        else:
            self._note_writes(data, history)
            history.keep_previous()
            write_json(GRAPH_FILE, data)
        self.dirty = False
        if counted:  # … et quittent le fichier d'attente (un arrêt entre les deux ne compte rien deux fois)
            self._counted = None
            _settle_counters(counted[0], counted[1])
        if self.data.get("commun"):  # membre du cerveau commun : ma part publique part en arrière-plan si elle change
            from . import commun
            commun.after_save(data)

    def _note_writes(self, data, history):
        """Souvenirs touchés depuis la lecture (ou la dernière écriture) → history/recents.jsonl, pour qu'un graph.json
        abîmé se répare sans les perdre (reparation.py). 1 à 2 ms à 10 000 souvenirs. Au-delà de RECENT_NODES (import,
        consolidation : précédés d'un instantané forcé), seules les suppressions sont notées."""
        since, stamp = getattr(self, "_t0", ""), data["updated"]
        fresh = {k: n for k, n in data["nodes"].items() if isinstance(n, dict) and str(n.get("updated") or "") >= since}
        if len(fresh) > RECENT_NODES:
            fresh = {}
        e0 = getattr(self, "_e0", len(self.edges))
        edges = [e for e in self.edges[e0:] if isinstance(e, dict) and not _foreign(e.get("from"))
                 and not _foreign(e.get("to"))] if len(self.edges) >= e0 else []
        history.record(stamp, fresh, getattr(self, "_purged", ()), edges)
        self._t0, self._e0, self._purged = stamp, len(self.edges), set()

    def _own_data(self) -> dict:
        """Ce qui s'enregistre : mes souvenirs, sans les pages des amis (ni les liens qui les touchent)."""
        if not self.data.get("commun"):
            return self.data
        out = {k: v for k, v in self.data.items() if k not in ("nodes", "edges", "commun")}
        out["nodes"] = {k: v for k, v in self.nodes.items() if not _foreign(k)}
        out["edges"] = [e for e in self.edges if not _foreign(e["from"]) and not _foreign(e["to"])]
        return out

    def _writable(self, nid):
        if _foreign(nid):
            who = ((self.nodes.get(nid) or {}).get("meta") or {}).get("commun_par") or "un ami"
            raise ReadOnly(f"page de {who} (cerveau commun) : lecture seule — écris ta propre page en la citant")

    def _guard(self, text):
        """Garde anti-secrets : masque clés, jetons et mots de passe avant toute écriture."""
        from .privacy import mask
        text, found = mask(text)
        if found:
            self.masked = sorted(set(getattr(self, "masked", [])) | set(found))
            sys.stderr.write(f"🔒 secret masqué avant enregistrement : {', '.join(sorted(set(found)))} "
                             "(le cerveau ne garde jamais de clé, jeton ni mot de passe)\n")
        return text

    @property
    def nodes(self) -> dict:
        return self.data["nodes"]

    @property
    def edges(self) -> list:
        return self.data["edges"]

    # ------------------------------------------------------------------------------ lecture
    def active(self, types=None, own=False):
        """Souvenirs actifs (own=True : sans les pages des amis du cerveau commun)."""
        for n in self.nodes.values():
            if n.get("status", "active") != "active":
                continue
            if types and n["type"] not in types:
                continue
            if own and _foreign(n["id"]):
                continue
            yield n

    def stem_map(self) -> dict:
        """Mode wiki : nom de page (fichier, en minuscules) → id. Vide en mode classique."""
        if getattr(self, "_stems", None) is None:
            files = (self.data.get("wiki") or {}).get("files") or {}
            self._stems = {str(v.get("path", "")).rsplit("/", 1)[-1][:-3].lower(): k for k, v in files.items()}
        return self._stems

    def get(self, ref):
        if not ref:
            return None
        ref = str(ref).strip().strip("`")
        if ref in self.nodes:
            return self.nodes[ref]
        if self.data.get("wiki"):  # [[Nom de la page]] (Obsidian) ou chemin d'une page du wiki
            name = ref.replace("\\", "/").rsplit("/", 1)[-1]
            name = name[:-3] if name.lower().endswith(".md") else name
            hit = self.stem_map().get(name.lower())
            if hit in self.nodes:
                return self.nodes[hit]
        slug = slugify(ref)
        if slug in self.nodes:
            return self.nodes[slug]
        cands = [n for k, n in self.nodes.items() if k.startswith(slug)]
        if len(cands) > 1:  # cerveau commun : ma page passe avant celle d'un ami
            cands = [n for n in cands if not _foreign(n["id"])] or cands
        if len(cands) == 1:
            return cands[0]
        folded = fold(ref)
        cands = [n for n in self.nodes.values() if fold(n["title"]) == folded]
        if len(cands) > 1:
            cands = [n for n in cands if not _foreign(n["id"])] or cands
        return cands[0] if len(cands) == 1 else None

    def neighbors(self, nid):
        if self._adj is not None:  # cerveau en lecture seule (vues en arrière-plan) : voisins indexés une fois
            return [(self.nodes[i], rel, d) for i, rel, d in self._adj.get(nid, ())]
        out = []
        for e in self.edges:
            if e["from"] == nid and e["to"] in self.nodes:
                out.append((self.nodes[e["to"]], e["rel"], "→"))
            elif e["to"] == nid and e["from"] in self.nodes:
                out.append((self.nodes[e["from"]], e["rel"], "←"))
        return out

    def freeze_neighbors(self):
        """Pour un cerveau qu'on ne modifie plus (vues régénérées en arrière-plan) : les voisins de chaque souvenir
        indexés une fois, dans le même ordre que neighbors(). L'export MEMOIRES.md ne parcourt plus tous les liens pour
        chacun des souvenirs (O(N × liens) : 0,7 s à 3 000 souvenirs)."""
        adj = {}
        for e in self.edges:
            a, b = e["from"], e["to"]
            if b in self.nodes:
                adj.setdefault(a, []).append((b, e["rel"], "→"))
            if a != b and a in self.nodes:
                adj.setdefault(b, []).append((a, e["rel"], "←"))
        self._adj = adj

    def project_members(self, pid, include_archived=False):
        return [n for n in self.nodes.values()
                if n.get("project") == pid and n["type"] != "project"
                and (include_archived or n.get("status", "active") == "active")]

    def similar(self, title, body="", ntype=None, limit=3, threshold=0.45, exclude=None, whole=False):
        """Souvenirs proches (anti-doublons) : similarité de Jaccard sur titre et titre+contenu.
        whole=True : titre+contenu seulement (deux souvenirs de même titre mais de contenus différents ne sont pas des
        doublons : « Objectif du mois » de la boutique et celui de la chaîne YouTube)."""
        tt = set(tokenize(title))
        bt = set(tokenize(f"{title} {body}"))
        cache = self._words()
        out = []
        for n in self.active(own=True):  # jamais une page d'ami : rien de privé ne doit y fusionner
            if n["type"] == "project" or n["id"] == exclude:
                continue
            if ntype and n["type"] != ntype:
                continue
            text = (n["title"], n.get("body", ""))
            hit = cache.get(n["id"])
            if hit is None or hit[0] != text:
                hit = (text, set(tokenize(text[0])), set(tokenize(f"{text[0]} {text[1]}")))
                cache[n["id"]] = hit
            nt, nb = hit[1], hit[2]
            # Borne exacte : jaccard(a, b) <= min(|a|, |b|) / max(|a|, |b|). Rien à calculer quand les tailles seules
            # interdisent d'atteindre le seuil (le gros du temps d'une consolidation sur un grand cerveau).
            if (whole or not _may_reach(tt, nt, threshold)) and not _may_reach(bt, nb, threshold):
                continue
            score = jaccard(bt, nb) if whole else max(jaccard(tt, nt), jaccard(bt, nb))
            if score >= threshold:
                out.append((round(score, 2), n))
        out.sort(key=lambda x: -x[0])
        return out[:limit]

    def _words(self) -> dict:
        """Mots de chaque souvenir pour similar() ({id: ((titre, contenu), mots du titre, mots du tout)}) : gardés d'un
        appel à l'autre (chaque entrée porte le texte dont elle vient : un souvenir modifié est redécoupé), et repris
        au premier appel de state/mots.bin pour les souvenirs inchangés depuis (mots.py) — `brain add` ne redécoupe plus
        tout le cerveau pour chercher ses doublons."""
        if self._sim_cache is None:
            try:
                from . import mots
                self._sim_cache = mots.prime(self)
            except Exception as exc:
                log(f"mots : {exc!r}")
                self._sim_cache = {}
        return self._sim_cache

    def cache_similar(self):
        """Série d'appels à similar() (consolidation, rêve, optimisation) : chaque souvenir n'est découpé qu'une fois.
        (Toujours vrai désormais : gardé pour les appelants.)"""
        self._words()

    # ------------------------------------------------------------------------------ projets
    def projects(self):
        return list(self.active(("project",), own=True))

    def project_for_path(self, path):
        """Projet connu le plus spécifique contenant ce chemin."""
        if not path:
            return None
        best, best_len = None, -1
        for n in self.projects():
            meta = n.get("meta") or {}
            for p in [meta.get("path")] + list(meta.get("aliases") or []):
                if p and path_within(path, p):
                    length = len(norm_path(p))
                    if length > best_len:
                        best, best_len = n, length
        return best

    def resolve_project(self, ref, cwd=None):
        if ref is None:
            return None
        ref = str(ref).strip()
        if ref.lower() in GLOBAL_REFS:
            return None
        if ref in (".", "ici", "here"):
            return self.project_for_path(cwd or os.getcwd())
        n = self.get(ref)
        if n and n["type"] == "project":
            return n
        if os.path.isdir(ref):
            return self.project_for_path(ref)
        folded = fold(ref)
        for n in self.projects():
            if folded in fold(n["title"]) or folded in n["id"]:
                return n
        return None

    def ensure_project(self, path, title=None, body="", source="auto"):
        target = norm_path(path)
        for n in self.projects():
            if norm_path((n.get("meta") or {}).get("path", "")) == target:
                return n, False
        abspath = os.path.abspath(str(path))
        name = title or os.path.basename(abspath.rstrip("\\/")) or abspath
        node = self.add("project", name, body, source=source, meta={"path": abspath}, nid=slugify(name, 32))
        return node, True

    # ------------------------------------------------------------------------------ écriture
    def unique_id(self, base) -> str:
        base = slugify(base, 40)
        nid, i = base, 2
        while nid in self.nodes:
            nid = f"{base}-{i}"
            i += 1
        return nid

    def add(self, ntype, title, body="", tags=(), project=None, importance=3, source="claude",
            meta=None, nid=None):
        ntype = normalize_type(ntype)
        title = clean_label(self._guard(title))
        body = self._guard(body)
        if ntype not in _NO_ABS:
            title, body = _absolutize_new("", title), _absolutize_new("", body)
        if not title:
            raise ValueError("titre vide")
        nid = self.unique_id(nid or title)
        ts = now_iso()
        node = {
            "id": nid, "type": ntype, "title": title, "body": str(body or "").strip(),
            "tags": clean_tags(tags), "project": project or None,
            "importance": clamp_importance(importance), "created": ts, "updated": ts,
            "hits": 0, "last_hit": None, "source": normalize_source(source), "status": "active",
            "meta": dict(meta or {}),
        }
        self.nodes[nid] = node
        self.sync_wikilinks(nid)
        self.dirty = True
        return node

    def update(self, nid, **fields):
        self._writable(nid)
        n = self.nodes[nid]
        for key, val in fields.items():
            if key == "project":
                if val is not None:
                    n["project"] = val or None
                continue
            if val is None:
                continue
            if key in ("title", "body"):
                val = self._guard(val)
                if n["type"] not in _NO_ABS and val != (n.get(key) or ""):
                    val = _absolutize_new(n.get(key), val)
                if key == "title":
                    val = clean_label(val)
            if key == "type":
                val = normalize_type(val)
            elif key == "tags":
                val = clean_tags(val)
            elif key == "importance":
                val = clamp_importance(val)
            n[key] = val
        n["updated"] = now_iso()
        self.sync_wikilinks(nid)
        self.dirty = True
        return n

    def link(self, a, b, rel="relates") -> bool:
        if a == b or a not in self.nodes or b not in self.nodes or _foreign(a) or _foreign(b):
            return False  # pas de lien enregistré vers une page d'ami : la citer dans le texte suffit
        for e in self.edges:
            if e["from"] == a and e["to"] == b and e["rel"] == rel:
                return False
        self.edges.append({"from": a, "to": b, "rel": rel, "created": now_iso()[:10]})
        if rel == "contradicts":  # un fait contredit perd de la confiance (il reste consultable)
            self.adjust_confidence(b, -0.2)
        self.dirty = True
        return True

    def unlink(self, a, b, rel=None) -> int:
        before = len(self.edges)
        self.data["edges"] = [e for e in self.edges
                              if not ({e["from"], e["to"]} == {a, b} and (rel is None or e["rel"] == rel))]
        removed = before - len(self.edges)
        if removed:
            self.dirty = True
        return removed

    def adjust_confidence(self, nid, delta):
        n = self.nodes.get(nid)
        if not n or _foreign(nid):
            return
        meta = dict(n.get("meta") or {})
        meta["conf"] = round(max(0.05, min(1.0, confidence(n) + delta)), 2)
        n["meta"] = meta
        self.dirty = True

    def supersede(self, new_id, old_id) -> bool:
        """« new remplace old » (façon mem0 / Zep) : lien supersedes, old archivé avec sa fin de validité.
        Rien n'est effacé : l'ancien fait reste consultable (`show`) et datable (`q --at`)."""
        if new_id == old_id or new_id not in self.nodes or old_id not in self.nodes:
            return False
        self._writable(new_id)
        self._writable(old_id)
        self.link(new_id, old_id, "supersedes")
        old = self.nodes[old_id]
        meta = dict(old.get("meta") or {})
        meta["valid_to"] = now_iso()[:10]
        meta["superseded_by"] = new_id
        old["meta"] = meta
        old["status"] = "archived"
        old["updated"] = now_iso()
        self.dirty = True
        return True

    def merge(self, keep_id, drop_id):
        """Doublon : `drop` fondu dans `keep` (consolidation, `brain regroupe`). Rien ne se perd : le texte de `drop`
        s'ajoute s'il dit autre chose, son titre devient un mot-clé de `keep` (la recherche le retrouve sous ses deux
        formulations), étiquettes, importance, compteurs de rappel et dates des deux sont gardés, ses liens passent à
        `keep` ; `drop` est archivé (meta.merged_into), consultable. → keep"""
        if keep_id == drop_id or keep_id not in self.nodes or drop_id not in self.nodes:
            raise ValueError(f"fusion impossible : {keep_id} ← {drop_id}")
        self._writable(keep_id)
        self._writable(drop_id)
        keep, drop = self.nodes[keep_id], self.nodes[drop_id]
        if drop.get("body") and fold(drop["body"]) not in fold(keep.get("body", "")):
            keep["body"] = f"{keep.get('body', '')}\n{drop['body']}".strip()
        if fold(drop.get("title", "")) != fold(keep.get("title", "")):
            meta = dict(keep.get("meta") or {})
            keys = str(meta.get("keys") or "")
            if fold(drop["title"]) not in fold(keys):
                meta["keys"] = f"{keys} · {drop['title']}" if keys else drop["title"]
            keep["meta"] = meta
        keep["tags"] = clean_tags((keep.get("tags") or []) + (drop.get("tags") or []))
        keep["importance"] = max(keep.get("importance", 3), drop.get("importance", 3))
        for k in ("hits", "used"):
            total = (keep.get(k) or 0) + (drop.get(k) or 0)
            if total or k in keep:
                keep[k] = total
        for k in ("last_hit", "last_used"):
            dates = [d for d in (keep.get(k), drop.get(k)) if d]
            if dates:
                keep[k] = max(dates)
        created = [d for d in (keep.get("created"), drop.get("created")) if d]
        if created:
            keep["created"] = min(created)
        seen = set()
        for e in self.edges:
            if e["from"] == drop_id:
                e["from"] = keep_id
            if e["to"] == drop_id:
                e["to"] = keep_id
        clean = []
        for e in self.edges:  # liens devenus une boucle ou un doublon : retirés
            key = (e["from"], e["to"], e["rel"])
            if e["from"] == e["to"] or key in seen:
                continue
            seen.add(key)
            clean.append(e)
        self.data["edges"] = clean
        ts = now_iso()
        drop["status"] = "archived"
        drop.setdefault("meta", {})["merged_into"] = keep_id
        drop["updated"] = keep["updated"] = ts
        self._adj = None
        self.dirty = True
        return keep

    def remove(self, nid, purge=False):
        self._writable(nid)
        if purge:
            self.nodes.pop(nid, None)
            # noté dans les écritures récentes, et effacé des lignes plus anciennes : une réparation ne le ramène pas
            self.__dict__.setdefault("_purged", set()).add(nid)
            self.data["edges"] = [e for e in self.edges if nid not in (e["from"], e["to"])]
            for n in self.nodes.values():
                if n.get("project") == nid:
                    n["project"] = None
        else:
            self.nodes[nid]["status"] = "archived"
            self.nodes[nid]["updated"] = now_iso()
        self.dirty = True

    def sync_wikilinks(self, nid):
        """[[id]] dans un contenu = lien automatique vers ce souvenir."""
        n = self.nodes.get(nid)
        if not n:
            return
        for m in WIKILINK.finditer(n.get("body", "")):
            target = self.get(m.group(1).split("|")[0].split("#")[0])  # [[id|texte]], [[id#titre]]
            if target and target["id"] != nid:
                self.link(nid, target["id"], "relates")

    def absorb_counters(self):
        """Compteurs de rappel en attente écrits dans graph.json à la fin de cette modification, même si rien d'autre
        ne change (entretien du jour : le fichier d'attente ne grossit pas sans fin)."""
        if self._counted and self._counted[2]:
            self.dirty = True
        elif self._counted:  # lignes déjà contenues dans graph.json (arrêt avant le ménage) : seulement le ménage
            _settle_counters(self._counted[0], self._counted[1])
            self._counted = None

    def touch(self, ids):
        ts = now_iso()
        for i in ids:
            n = self.nodes.get(i)
            if n and not _foreign(i):  # les compteurs d'une page d'ami ne s'enregistrent pas
                n["hits"] = n.get("hits", 0) + 1
                n["last_hit"] = ts
                self.dirty = True


def ensure_usage_baseline() -> bool:
    """Une seule fois : fige les compteurs de rappel existants comme point de départ de la mesure d'usage."""
    try:
        with Brain.edit(timeout=3) as b:
            if b.data.get("usage_since"):
                return False
            for n in b.nodes.values():
                if n.get("hits"):
                    n.setdefault("meta", {})["hits0"] = n["hits"]
            b.data["usage_since"] = now_iso()
            b.dirty = True
            return True
    except Exception:
        return False


def _counters():
    """Compteurs en attente : {"id": époque du fichier, "n": dernier numéro, "rows": [[n, "h"|"u", date, [ids]]]}.
    None s'il n'y en a pas (ou fichier illisible)."""
    c = read_json(COUNTERS_FILE, None)
    if isinstance(c, dict) and c.get("id") and isinstance(c.get("n"), int) and isinstance(c.get("rows"), list):
        return c
    return None


def _bump(kind, ids):
    """Une ligne de plus dans le fichier d'attente, sous son propre verrou : un rappel n'attend plus le verrou du graphe
    (tenu des secondes par une consolidation, et le compte se perdait) et ne réécrit plus graph.json."""
    ids = [str(i) for i in ids or () if i and not _foreign(i)]  # les compteurs d'une page d'ami ne s'enregistrent pas
    if not ids:
        return
    with FileLock(COUNTERS_LOCK, timeout=1.0, stale=10.0):
        c = _counters() or {"id": f"{time.time_ns():x}-{os.getpid():x}", "n": 0, "rows": []}
        c["n"] += 1
        c["rows"].append([c["n"], kind, now_iso(), ids])
        write_json(COUNTERS_FILE, c, indent=None)


def _fold_counters(data):
    """Compteurs en attente appliqués aux souvenirs lus, comme l'aurait fait chaque rappel en réécrivant graph.json.
    graph.json note jusqu'où il les contient déjà (« compteurs » : époque et numéro) : rien n'est compté deux fois.
    → (époque, numéro jusqu'où ce graphe les contient, lignes appliquées), ou None si rien n'est en attente."""
    c = _counters()
    if not c or not c["rows"]:
        return None
    mark = data.get("compteurs") if isinstance(data.get("compteurs"), dict) else {}
    since = mark.get("n", 0) if mark.get("id") == c["id"] and isinstance(mark.get("n"), int) else 0
    nodes, last, applied = data["nodes"], since, 0
    for row in c["rows"]:
        if not (isinstance(row, list) and len(row) == 4 and isinstance(row[0], int)) or row[0] <= since:
            continue  # (déjà dans graph.json : arrêt entre son écriture et le ménage du fichier d'attente)
        num, kind, ts, ids = row
        for i in ids if isinstance(ids, list) else ():
            n = nodes.get(i)
            if not isinstance(n, dict) or _foreign(i):
                continue
            if kind == "h":
                n["hits"] = (n.get("hits", 0) or 0) + 1
                n["last_hit"] = ts
            elif kind == "u":
                n["used"] = (n.get("used", 0) or 0) + 1
                n["last_used"] = ts
        last, applied = max(last, num), applied + 1
    return c["id"], last, applied


def _settle_counters(epoch, num):
    """Après l'écriture du graphe : les lignes qu'il contient désormais quittent le fichier d'attente (les plus
    récentes, arrivées pendant l'écriture, restent pour la suivante)."""
    try:
        with FileLock(COUNTERS_LOCK, timeout=2.0, stale=10.0):
            c = _counters()
            if not c or c["id"] != epoch:
                return
            rows = [r for r in c["rows"] if isinstance(r, list) and r and isinstance(r[0], int) and r[0] > num]
            if len(rows) != len(c["rows"]):
                c["rows"] = rows
                write_json(COUNTERS_FILE, c, indent=None)
    except Exception as exc:
        log(f"compteurs : {exc!r}")


def bump_used(ids):
    """Montré ≠ utilisé : compte les souvenirs réellement repris par Claude (réponse, commande, fichier écrit) — au
    mieux, jamais bloquant."""
    if not ids:
        return
    try:
        _bump("u", ids)
    except Exception as exc:
        log(f"compteurs (utilisés) : {exc!r}")


def bump_hits(ids):
    """Compte les rappels (sert au classement de l'index) — au mieux, jamais bloquant."""
    if not ids:
        return
    try:
        _bump("h", ids)
    except Exception as exc:
        log(f"compteurs (rappels) : {exc!r}")
