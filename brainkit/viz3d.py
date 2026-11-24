"""Vue 3D (cerveau.html) — style futuriste et animé : 3d-force-graph (three.js), données intégrées, effets (bloom, champ
d'étoiles scintillant, nébuleuses, grille holographique, influx neuronaux le long des liens, nœuds qui respirent,
réticule de sélection, onde de choc au clic, démarrage où les nœuds se matérialisent en vague, rotation au repos) —
coupables d'un clic (✨), réduits si le système demande moins d'animations. Depuis l'étape 17 : flèches sur les liens
typés et, au survol d'un lien, son type et ses dates ; un nœud lâché reste où on le pose (bouton ou double-clic sur le
fond pour tout libérer) ; orbite de la caméra pour une vidéo ; animation en pause quand l'onglet est caché.

Tout est dans la page, sans aucun site extérieur (avant la 8.31.0, les bibliothèques venaient de trois sites, sans
contrôle d'intégrité, et la vue ne marchait pas hors ligne) : le gabarit est vue3d/page.html, les bibliothèques
vue3d/3d-force-graph.min.js et vue3d/three-fx.js (versions, empreintes : vue3d/sources.json ; licences :
vue3d/LICENCES.md ; fabriquées par vue3d/fabriquer.py). Elles sont intégrées à la page, qui marche donc ouverte
depuis le disque, copiée ailleurs ou sans connexion. Sans WebGL, la page renvoie vers cerveau-2d.html et la vue
tableau."""
from __future__ import annotations

import re
from pathlib import Path

DIR = Path(__file__).resolve().parent / "vue3d"
PAGE = DIR / "page.html"
LIBS = {"LIB_3D": DIR / "3d-force-graph.min.js", "LIB_FX": DIR / "three-fx.js"}
# fichiers qui font la vue (relatifs à brainkit/) : une mise à jour de l'un d'eux la fait refaire (vues.py)
FILES = ("viz3d.py", "vue3d/page.html", "vue3d/3d-force-graph.min.js", "vue3d/three-fx.js")
_HOLE = re.compile(r"__(DATA|LIB_3D|LIB_FX)__")
_CLOSE = re.compile(r"</script|<!--|<script", re.I)


def _lib(path: Path) -> str:
    """Une bibliothèque à intégrer ; absente ou abîmée (installation incomplète) : rien, et la page le dit."""
    from .common import log
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        log(f"vue 3D : bibliothèque {path.name} illisible ({exc!r}) — `brain doctor`")
        return ""
    if _CLOSE.search(text):  # ne pourrait pas tenir dans un <script> de la page
        log(f"vue 3D : bibliothèque {path.name} refusée (contient une balise <script>)")
        return ""
    return text


def page(payload: str) -> str:
    """cerveau.html : le gabarit, les données (JSON déjà échappé pour un <script>) et les deux bibliothèques, en une
    seule passe (rien de ce qui est inséré n'est relu comme un trou du gabarit)."""
    parts = {"DATA": payload, **{k: _lib(p) for k, p in LIBS.items()}}
    return _HOLE.sub(lambda m: parts[m.group(1)], PAGE.read_text(encoding="utf-8"))
