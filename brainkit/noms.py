"""Index nom → souvenirs (plan, étape 14, point 5 ; d'après mem0 `main.py`) : les noms propres et codes de chaque
souvenir (reconcile.entities) et leurs formes réunies (reconcile.names : « Mondial Relay » = « MondialRelay »), gardés
d'une commande à l'autre au lieu de relire tout le cerveau à chaque question.

Avant, `brain q` (et l'outil MCP `memory_search`) relisait le texte de chaque souvenir pour le deuxième saut de la
recherche fusionnée : 1,0 s sur 1,4 s à 10 000 souvenirs. `brain add` faisait de même pour les noms rares du titre.

Dérivé seulement, jamais la source : state/noms.bin, refait quand il manque, est abîmé ou d'une autre version, et
repris tel quel tant que graph.json est le même fichier, octet pour octet (Brain.stamp) ; sinon chaque souvenir est
comparé à l'empreinte de son texte (mots.digest), et seuls ceux qui ont changé sont relus. Aucune migration : le
graphe n'en sait rien."""
from __future__ import annotations

import marshal
import os
import sys

from .common import STATE_DIR
from .mots import digest

TAG = f"noms1:{sys.version_info[0]}.{sys.version_info[1]}"  # (marshal : format propre à chaque version de Python)
FILE = "noms.bin"
NONE = (None, (), ())  # souvenir absent de la table (jamais : elle couvre tout le cerveau) : aucun nom
_LOADED = {}  # déjà lu dans ce processus (serveur MCP) : {fichier: (empreinte de graph.json, table)}


def _text(n) -> str:
    return f"{n.get('title', '')}\n{n.get('body', '')}"


def _parse(text) -> tuple:
    """(reconcile.entities(text), reconcile.names(text)), triés ; les noms repérés une seule fois."""
    from .reconcile import _entity_spans, names_of
    spans = _entity_spans(text)
    return tuple(sorted({f for _, _, f in spans})), tuple(sorted(names_of(text, spans)))


def table(brain, use_cache=True) -> dict:
    """{id: (empreinte, noms propres et codes, noms réunis)} de chaque souvenir du cerveau (archivés compris), les noms
    triés. `use_cache` faux (cerveau d'une autre date, monde d'essai du banc) : calculé sur place, rien n'est lu ni
    écrit."""
    if not use_cache:
        return {nid: (None, *_parse(_text(n))) for nid, n in brain.nodes.items()}
    path = STATE_DIR / FILE
    stamp = getattr(brain, "stamp", None)
    hit = _LOADED.get(str(path))
    if stamp and hit and hit[0] == stamp:
        return hit[1]
    try:
        with open(path, "rb") as fh:
            disk = marshal.loads(fh.read())
        if not (isinstance(disk, dict) and disk.get("tag") == TAG and isinstance(disk.get("nodes"), dict)):
            disk = None
    except Exception:
        disk = None
    if stamp and disk and disk.get("stamp") == stamp and len(disk["nodes"]) == len(brain.nodes):
        _LOADED[str(path)] = (stamp, disk["nodes"])
        return disk["nodes"]
    old = disk["nodes"] if disk else {}
    rows, changed = {}, len(old) != len(brain.nodes)
    for nid, n in brain.nodes.items():
        fp = digest(n)  # (empreinte de mots.py : CRC-32 et longueurs du titre, du contenu, des étiquettes)
        got = old.get(nid)
        if isinstance(got, tuple) and len(got) == 3 and got[0] == fp:
            rows[nid] = got
        else:
            rows[nid] = (fp, *_parse(_text(n)))
            changed = True
    # Écrit pour la commande suivante, sauf depuis un cerveau modifié en mémoire et pas enregistré (monde d'essai)
    if (changed or (stamp and disk and disk.get("stamp") != stamp)) and (stamp or not getattr(brain, "dirty", False)):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
            with open(tmp, "wb") as fh:
                fh.write(marshal.dumps({"tag": TAG, "stamp": stamp, "nodes": rows}))
            os.replace(tmp, path)
        except Exception:
            pass
    if stamp:
        _LOADED[str(path)] = (stamp, rows)
    return rows
