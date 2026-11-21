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
| Vue 3D interactive (mémoire, concepts, chronologie, Maj+clic = chemin, cartes de projets) | `viz --open` → `cerveau.html`, hors ligne (`cerveau-2d.html` sans WebGL) |

Liens **déduits** = similarité du contenu (raison : mots communs ; confiance forte/moyenne/faible), jamais écrits
dans le graphe tant qu'ils ne sont pas confirmés par `link`. Analyse en cache (`state/analysis.json`), recalculée
seulement quand le savoir change.
