# 🧠 Cerveau — projets et graphe

Cartes de projets, analyse du graphe, fiches, concepts, vue 3D. Commande : `python "$HOME/.claude/brain/brain.py" <commande>`.

## Projets (façon graphify)
| But | Commande |
|---|---|
| Cartographier / mettre à jour (incrémental) | `map [dossier] [--full] [--bg]` |
| Fichiers liés à un sujet | `files "paiement panier"` |
| Où est défini X (fonction, classe, variable d'env, route) | `where X` |
| Fiche d'un fichier ou symbole | `explain <fichier\|symbole>` |
| Ce qui dépend d'un fichier ou d'une fonction (avant de modifier) | `impact <fichier\|symbole>` |
| Dépendances | `deps <fichier>` · chemin entre deux fichiers : `path <a> <b>` |
| Projets connus | `proj` · `proj add <dossier> -T "Nom" -b "description"` |

Carte complète : `~/.claude/brain/projects/<id>/MAP.md` (structure, fichiers clés par centralité, modules, routes,
variables d'env, documents, cycles, TODO, fichiers sensibles jamais lus).

## Graphe (façon graphify)
| But | Commande |
|---|---|
| Rapport : communautés, nœuds clés, liens surprenants, liens suggérés, doublons, trous, questions | `report [--print]` (→ `RAPPORT.md`) |
| Chemin entre deux souvenirs (liens explicites d'abord, puis déduits) | `path <id_a> <id_b>` |
| Communauté, centralité, concepts et liens déduits d'un souvenir | `show <id>` |
| Fiche de synthèse d'une communauté (extractive, régénérée seulement quand un membre change) | `fiche [n°\|mot\|id]` |
| Concepts repérés (outils, sujets, sigles, domaines, produits) et souvenirs liés | `concept [nom]` |
| Vue 3D interactive (mémoire, concepts, chronologie, Maj+clic = chemin, cartes de projets) | `viz --open` → `cerveau.html`, hors ligne (`cerveau-2d.html` sans WebGL) · le curseur ▶ rejoue le cerveau tel qu'il était à chaque date : souvenirs remplacés et liens retirés réapparaissent à leur époque, un remplacement passe en impulsion de l'ancien au nouveau ; curseur à droite, la vue d'aujourd'hui · couleurs « domaine » et « chaleur » (dernier usage) · ☷ couches : vision en haut, détail en bas · le panneau d'un souvenir donne sa validité et sa lignée · flèches sur les liens typés ; au survol d'un lien, son type et ses dates · un nœud glissé reste posé (⚲, L ou double-clic sur le fond pour libérer) · ◎ orbite de la caméra pour une vidéo (O) · pause quand l'onglet est caché · ⊞ amas par projet, actif à l'ouverture (G pour la disposition libre, choix gardé) |

Liens **déduits** = similarité du contenu (raison : mots communs ; confiance forte/moyenne/faible), jamais écrits
dans le graphe tant qu'ils ne sont pas confirmés par `link`. Analyse en cache (`state/analysis.json`), recalculée
seulement quand le savoir change.
