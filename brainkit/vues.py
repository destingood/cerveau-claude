"""Vues du cerveau refaites en arrière-plan : index injecté (BRAIN.md), export lisible (MEMOIRES.md), vues 3D et 2D
(cerveau.html, cerveau-2d.html, avec l'analyse du graphe), mots des souvenirs (mots.py), fiches de synthèse et index du
démarrage des derniers projets (index.prebuild). Les hooks la demandent aussi (fin de session, compaction, analyse
trouvée périmée) : eux ne calculent jamais l'analyse. Chaque vue n'est refaite que si ses sources ont changé depuis
qu'elle a été écrite (state/vues-sources.json) : une fin de session qui n'a rien changé ne refait au plus que BRAIN.md
(sa liste des projets suit leur dernière session).

Une écriture (`brain add`, `edit`, `rm`…) n'écrit plus que le graphe et demande ces vues (request) : une tâche détachée
les refait une fois les écritures calmées, si bien que plusieurs `add` à la suite ne coûtent qu'une régénération. Avant,
chaque `add` les réécrivait toutes lui-même : 2,1 s à 3 000 souvenirs, 11,5 s à 10 000 (9,5 Mo par vue).

- state/vues.json : demandes faites (`n`), dernière traitée (`fait`), heure de la dernière (`t`) ;
- state/vues.lock : tenu par qui écrit les vues (la tâche, `brain viz`, `brain export`), jamais deux à la fois ;
- `brain vues --attendre` attend qu'elles soient à jour (tests, commandes qui en ont besoin tout de suite)."""
from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path

from .common import BRAIN_DIR, GRAPH_FILE, INDEX_FILE, JOURNAL_FILE, STATE_DIR, FileLock, log, read_json, write_json

REQUEST = STATE_DIR / "vues.json"
REQUEST_LOCK = STATE_DIR / "vues-demande.lock"
LOCK = STATE_DIR / "vues.lock"
QUIET = 1.0  # s sans nouvelle demande avant de régénérer (une rafale d'écritures → une seule régénération)
MAX_WAIT = 8.0  # s au plus entre une demande et le début de sa régénération, même si les écritures continuent
STALE = 30.0  # s : verrou d'un processus mort repris (son détenteur vivant le rafraîchit)


def _state() -> dict:
    s = read_json(REQUEST, None)
    s = s if isinstance(s, dict) else {}
    out = {}
    for k in ("n", "fait", "t"):
        v = s.get(k)
        out[k] = v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0
    return {"n": int(out["n"]), "fait": int(out["fait"]), "t": float(out["t"])}


def _update(change) -> dict:
    with FileLock(REQUEST_LOCK, timeout=2.0, stale=10.0, strict=False):
        s = _state()
        change(s)
        write_json(REQUEST, s, indent=None)
    return s


def busy() -> bool:
    """Quelqu'un écrit-il les vues en ce moment ?"""
    try:
        return time.time() - os.path.getmtime(LOCK) < STALE
    except OSError:
        return False


def pending() -> bool:
    """Vues demandées pas encore refaites, ou en cours d'écriture ?"""
    s = _state()
    return s["n"] > s["fait"] or busy()


def _spawn() -> bool:
    from .hooks import spawn_background
    return spawn_background(["vues", "--fond"])


def request() -> bool:
    """Après une écriture du graphe : les vues seront refaites en arrière-plan. → False si aucune tâche ne peut s'en
    charger (lancement impossible) : à l'appelant de les refaire lui-même (run_now)."""
    _update(lambda s: s.update(n=s["n"] + 1, t=time.time()))
    return busy() or _spawn()  # une tâche au travail relit les demandes avant de rendre la main


def _sources_ns() -> int:
    """Date (ns) des sources de BRAIN.md lues pour le régénérer, au plus tôt minuit (index.ensure_index le refait chaque
    jour) : il prend cette date-là, si bien qu'une écriture arrivée pendant la régénération le laisse périmé aux yeux
    d'ensure_index au lieu de passer pour plus ancienne que lui."""
    import datetime as dt
    from . import index
    stamps = [int(time.mktime(dt.date.today().timetuple())) * 10 ** 9]
    for f in (GRAPH_FILE, JOURNAL_FILE, Path(index.__file__)):
        try:
            stamps.append(f.stat().st_mtime_ns)
        except OSError:
            pass
    return max(stamps)


# ------------------------------------------------------------------------------------------ sources de chaque vue
SOURCES = STATE_DIR / "vues-sources.json"  # {"v", "graphe": {token, content}, "items": {vue: {key, files}}}
SOURCES_V = 1
_META_SKIP = ("mapped", "stack")  # méta que le cartographe réécrit à chaque passage, et qu'aucune vue ne montre


def _stamp(path):
    try:
        st = os.stat(path)
        return [st.st_size, st.st_mtime_ns]
    except OSError:
        return None


def _code(*names) -> list:
    """Empreinte du code qui fait une vue (version + fichiers) : une mise à jour la fait refaire."""
    from . import __version__
    here = Path(__file__).resolve().parent
    return [__version__] + [[n, _stamp(here / n)] for n in names]


def _today() -> str:
    import datetime as dt
    return dt.date.today().isoformat()


def _key(*parts) -> str:
    import hashlib
    import json
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]


def _load_sources() -> dict:
    s = read_json(SOURCES, None)
    if not (isinstance(s, dict) and s.get("v") == SOURCES_V and isinstance(s.get("items"), dict)):
        return {"v": SOURCES_V, "graphe": {}, "items": {}}
    if not isinstance(s.get("graphe"), dict):
        s["graphe"] = {}
    return s


class _Sources:
    """Empreintes des sources d'un passage de la tâche des vues, calculées au plus une fois chacune."""

    def __init__(self, brain, saved):
        self.b, self.saved, self._content, self.graphe = brain, saved, None, saved.get("graphe") or {}

    def content(self) -> str:
        """Ce que l'export et les vues 3D montrent des souvenirs et des liens (compteurs de rappel compris, date de la
        carte non) : repris du passage précédent quand graph.json et les compteurs en attente sont les mêmes fichiers
        (Brain.stamp : rien de relu ni de recalculé), recalculé sinon — graph.json réécrit par le cartographe ou pour y
        ranger les compteurs n'en change pas l'empreinte."""
        if self._content is None:
            from .store import COUNTERS_FILE
            stamp = getattr(self.b, "stamp", None)
            token = [stamp, _stamp(COUNTERS_FILE)] if stamp else None
            if token and self.graphe.get("token") == token and isinstance(self.graphe.get("content"), str):
                self._content = self.graphe["content"]
            else:
                nodes = [[i, {k: v for k, v in n.items() if k != "meta"},
                          {k: v for k, v in (n.get("meta") or {}).items() if k not in _META_SKIP}]
                         for i, n in sorted(self.b.nodes.items())]
                edges = sorted([e.get("from"), e.get("to"), e.get("rel")] for e in self.b.edges)
                self._content = _key(nodes, edges, (self.b.data.get("wiki") or {}).get("files"))
            self.graphe = {"token": token, "content": self._content}
        return self._content

    def words(self) -> str:
        """Ce que mots.bin et termes.bin retiennent : le texte de chaque souvenir actif (empreinte mots.digest)."""
        from . import mots
        return _key(mots.TAG, [[n["id"], n["type"], mots.digest(n)] for n in self.b.active()])

    def around_viz(self) -> list:
        """Sources de la vue 3D hors du graphe : cartes des projets, skills métier, boutiques suivies, wiki."""
        from .common import PLUGIN, PROJECTS_DIR
        from .install import skill_sources
        from . import wikistore
        maps = [[p["id"], _stamp(PROJECTS_DIR / p["id"] / "map.json")] for p in self.b.projects()]
        skills = []
        for name, src in sorted(skill_sources().items()):
            files = [src / "SKILL.md", *sorted((src / "references").glob("*.md")),
                     *sorted((src / "scripts").glob("*.py"))]
            skills.append([name, [[f.name, _stamp(f)] for f in files]])
        shops = [[f.name, _stamp(f)] for f in sorted((BRAIN_DIR / "boutiques").glob("*.json"))]
        return [maps, skills, shops, str(wikistore.root() or ""), PLUGIN]


def regenerate(force=False) -> list:
    """Les vues, d'après le graphe tel qu'il est maintenant, chacune à part (l'une qui échoue n'empêche pas les
    autres), et seulement celles dont les sources ont changé depuis qu'elles ont été écrites (state/vues-sources.json) :
    une fin de session qui n'a rien changé ne refait plus l'export, les vues 3D et 2D, les mots ni les fiches (quelques
    secondes de calcul à 10 000 souvenirs). BRAIN.md suit ses propres règles (index.refresh : refait aussi chaque jour,
    et quand la dernière session d'un projet change) ; l'index du démarrage des derniers projets, les siennes
    (index.prebuild). Une vue absente ou réécrite par quelqu'un d'autre est refaite. `force` : toutes, quoi qu'il en
    soit (`brain vues`, réparation). Le cerveau lu n'est pas modifié : ses voisins sont indexés une fois pour l'export.
    → noms des vues refaites."""
    from . import fiches, graph, index, mots, viz
    from .common import EXPORT_FILE, VIZ2D_FILE, VIZ_FILE
    from .store import Brain
    stamp = _sources_ns()
    try:
        b = Brain.load()
    except Exception as exc:  # graphe illisible et rien pour le réparer : la prochaine écriture redemandera les vues
        log(f"vues : lecture du graphe : {exc!r}")
        return []
    b.freeze_neighbors()
    saved = _load_sources()
    src = _Sources(b, saved)
    done = []

    def brain_md():
        made = index.refresh(b) if not force else bool(index.rebuild(b))
        if stamp < time.time_ns():
            os.utime(INDEX_FILE, ns=(stamp, stamp))
        return made

    # (vue, fichiers écrits, fichiers dérivés lus après coup, empreinte des sources avant, étape)
    steps = (
        ("index", None, None, None, brain_md),
        ("mots", [mots.MOTS_FILE, mots.TERMES_FILE], [],
         lambda: [_code("mots.py", "graph.py", "common.py"), src.words()], lambda: mots.rebuild(b)),
        ("export", [EXPORT_FILE], [], lambda: [_code("index.py", "store.py", "common.py"), _today(), src.content()],
         lambda: index.export(b)),  # (sa date, et l'ordre des souvenirs, qui dépend de leur âge : refait chaque jour)
        ("vue 3D", [VIZ_FILE, VIZ2D_FILE], [graph.ANALYSIS_FILE],  # (avec l'analyse du graphe, refaite si besoin)
         lambda: [_code("viz.py", "viz3d.py", "graph.py", "boutique.py"), src.content(), src.around_viz()],
         lambda: viz.render(b)),
        ("fiches", [], [graph.ANALYSIS_FILE, fiches.FICHES_FILE],  # fiches de synthèse : jamais faites dans un rappel
         lambda: [_code("fiches.py", "graph.py"), src.content()], lambda: fiches.ensure(b)),
        ("démarrage", None, None, None, lambda: index.prebuild(b)),  # index des derniers projets, analyse à jour
    )
    for name, outputs, derived, sources, step in steps:
        if not BRAIN_DIR.is_dir():  # cerveau effacé entre-temps (dossier de test) : surtout ne pas le recréer
            return done
        try:
            if sources is None:  # vue qui a ses propres règles (index.py)
                if step() is not False:
                    done.append(name)
                continue
            key = _key(sources())
            prev = saved["items"].get(name) or {}
            files = outputs + derived
            if not force and prev.get("key") == key and all(f.exists() for f in outputs) \
                    and prev.get("files") == [_stamp(f) for f in files]:
                continue
            saved["items"].pop(name, None)  # (une étape qui échoue sera refaite au passage suivant)
            step()
            saved["items"][name] = {"key": key, "files": [_stamp(f) for f in files]}
            done.append(name)
        except Exception as exc:
            log(f"vues : {name} : {exc!r}")
    if BRAIN_DIR.is_dir():
        saved["graphe"] = src.graphe
        try:
            write_json(SOURCES, saved, indent=None)
        except OSError as exc:
            log(f"vues : sources : {exc!r}")
    return done


def _drain(quiet=True) -> None:
    """Sous le verrou des vues : régénère tant qu'il reste des demandes. quiet=True (tâche de fond) : d'abord, attendre
    que les écritures se calment (QUIET s sans demande, au plus MAX_WAIT s)."""
    start = time.time()
    while BRAIN_DIR.is_dir():
        s = _state()
        if s["n"] <= s["fait"]:
            return
        while quiet:
            left = min(QUIET - (time.time() - s["t"]), MAX_WAIT - (time.time() - start))
            if left <= 0:
                break
            time.sleep(min(left, 0.25))
            s = _state()
        if not BRAIN_DIR.is_dir():
            return
        target = s["n"]  # demandes faites jusqu'ici : le graphe lu ensuite contient leurs écritures
        regenerate()
        _update(lambda st: st.update(fait=max(st["fait"], target)))
        start = time.time()


def background() -> None:
    """`brain vues --fond` (tâche détachée) : refait les vues demandées, puis rend la main. Une autre tâche déjà au
    travail verra les demandes : on s'arrête."""
    while BRAIN_DIR.is_dir():
        try:
            with FileLock(LOCK, timeout=0, stale=STALE):
                _drain()
        except TimeoutError:
            return
        s = _state()  # une demande arrivée pendant qu'on rendait le verrou n'a vu personne au travail : on la prend
        if s["n"] <= s["fait"]:
            return


@contextlib.contextmanager
def lock(timeout=120.0):
    """Écriture de vues hors de la tâche (`brain viz`, `brain export`) : après celle en cours, jamais en même temps
    (la plus lente, partie d'un graphe plus ancien, écraserait l'autre). Les demandes restées en attente sont relancées
    à la sortie."""
    with FileLock(LOCK, timeout=timeout, stale=STALE, strict=False):
        yield
    s = _state()
    if s["n"] > s["fait"] and not busy():
        _spawn()


def run_now(timeout=120.0, force=False) -> list:
    """Les vues tout de suite, sous le verrou (lancement en arrière-plan impossible) ; `force` : toutes, même celles
    dont rien n'a changé (`brain vues`, réparation). → noms des vues refaites."""
    with lock(timeout):
        target = _state()["n"]
        done = regenerate(force=force)
        _update(lambda st: st.update(fait=max(st["fait"], target)))
    return done


def wait(timeout=120.0) -> bool:
    """Attend que les vues demandées soient refaites. Si personne ne s'en charge (tâche pas encore partie, ou arrêtée),
    les refait ici. → True si elles sont à jour."""
    end = time.time() + timeout
    while True:
        s = _state()
        if s["n"] <= s["fait"] and not busy():
            return True
        if time.time() >= end:
            return False
        try:
            with FileLock(LOCK, timeout=0, stale=STALE):
                _drain(quiet=False)
        except TimeoutError:
            time.sleep(0.1)  # une tâche est au travail : on attend qu'elle ait fini
