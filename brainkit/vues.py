"""Vues du cerveau refaites en arrière-plan : index injecté (BRAIN.md), export lisible (MEMOIRES.md), vues 3D et 2D
(cerveau.html, cerveau-2d.html, avec l'analyse du graphe), mots des souvenirs (mots.py), fiches de synthèse et index du
démarrage des derniers projets (index.prebuild). Les hooks la demandent aussi (fin de session, compaction, analyse
trouvée périmée) : eux ne calculent jamais l'analyse.

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


def regenerate() -> None:
    """Toutes les vues, d'après le graphe tel qu'il est maintenant, chacune à part (l'une qui échoue n'empêche pas les
    autres). Le cerveau lu n'est pas modifié : ses voisins sont indexés une fois pour l'export."""
    from . import fiches, index, mots, viz
    from .store import Brain
    stamp = _sources_ns()
    try:
        b = Brain.load()
    except Exception as exc:  # graphe illisible et rien pour le réparer : la prochaine écriture redemandera les vues
        log(f"vues : lecture du graphe : {exc!r}")
        return
    b.freeze_neighbors()

    def brain_md():
        index.rebuild(b)
        if stamp < time.time_ns():
            os.utime(INDEX_FILE, ns=(stamp, stamp))

    for name, step in (("index", brain_md), ("mots", lambda: mots.rebuild(b)), ("export", lambda: index.export(b)),
                       ("vue 3D", lambda: viz.render(b)),  # (avec l'analyse du graphe, refaite si besoin)
                       ("fiches", lambda: fiches.ensure(b)),  # fiches de synthèse : jamais faites dans un rappel
                       ("démarrage", lambda: index.prebuild(b))):  # index des derniers projets, analyse à jour
        if not BRAIN_DIR.is_dir():  # cerveau effacé entre-temps (dossier de test) : surtout ne pas le recréer
            return
        try:
            step()
        except Exception as exc:
            log(f"vues : {name} : {exc!r}")


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


def run_now(timeout=120.0) -> None:
    """Toutes les vues tout de suite, sous le verrou (réparation, lancement en arrière-plan impossible)."""
    with lock(timeout):
        target = _state()["n"]
        regenerate()
        _update(lambda st: st.update(fait=max(st["fait"], target)))


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
