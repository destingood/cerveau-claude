---
name: brain
description: Cerveau persistant de Claude : mémoire en graphe datée (souvenirs, concepts, liens), cartes de projets, à-faire, historique, coffre Obsidian, MCP, vue 3D. Pour retrouver ou mémoriser un souvenir, trouver un fichier ou un symbole sans explorer, reprendre une session, ou quand l'utilisateur dit « souviens-toi », « retiens », « cerveau », « /brain ».
---

# 🧠 Cerveau — référence

Commande : `python "$HOME/.claude/brain/brain.py" <commande>` (fonctionne dans Bash et PowerShell). Sortie compacte, pensée pour économiser les tokens.

## Ce qui se passe tout seul (hooks)
- **Démarrage de session** : index du cerveau + fiche du projet courant (souvenirs, 3 dernières sessions, fin de la
  dernière session, résumé de carte) injectés ; dans un projet, l'index global se resserre sur ce qui s'y rapporte ;
  les à-faire dont l'échéance approche (ou est dépassée) passent en tête (« ⏰ Échéances »). Dossier de projet inconnu → enregistré et cartographié en arrière-plan.
- **Chaque message** : rappel automatique des souvenirs/fichiers vraiment liés (filtre anti-bruit, jamais deux fois) ;
  la recherche tolère fautes, écriture phonétique et synonymes FR/EN (« boutik », « shopfy », « rdv » → agenda).
- **Fin de tâche importante** : rappel unique de noter 3 à 5 **observations datées** de la session (`obs "🔴 …" "🟡 …"`)
  et de mémoriser l'essentiel, avec les phrases de l'utilisateur qui ressemblent à une préférence ou une décision
  (« Candidats repérés… ») : juger, puis `add` ce qui est durable. Après une **compaction** du contexte, le Stop suivant
  demande les observations de la session (le détail n'est plus que résumé).
- **Usage réel** : un souvenir montré dont les termes ou les chiffres reviennent dans ta réponse ou tes commandes
  compte comme *utilisé* (montré ≠ utilisé) ; le classement de l'index en tient compte.
- **Fin de session** : journal, vue 3D, et une fois par jour consolidation prudente (doublons évidents, souvenirs
  remplacés via `supersedes`, secrets) puis **rêve** (dates relatives rendues absolues, observations de plus de 7 jours
  condensées en un résumé par semaine et par projet, dossier `REVE.md` des points à trancher ; s'il y en a assez, une
  ligne 🌙 au démarrage propose de le confier à un sous-agent en arrière-plan :
  `dream` → appliquer ce qui est sûr → `dream --done`), avec instantané pris avant, et sauvegarde hors du disque système
  (`D:\Sauvegardes-cerveau-Claude` par défaut : une réinstallation de Windows n'efface plus le cerveau).
- **Auto-réparation** : si graph.json est illisible, le cerveau repart du dernier instantané valide (ou de la
  dernière sauvegarde) et garde le fichier abîmé à côté ; jamais d'écrasement par un graphe vide.
- **Sécurité** : clés, jetons et mots de passe sont masqués automatiquement à l'écriture ; chaque modification
  peut être annulée (`history` / `restore`).
- La mémoire native de Claude Code (`~/.claude/projects/*/memory`) est importée automatiquement.

## Mémoire
| But | Commande |
|---|---|
| Chercher (souvenirs + voisins du graphe + sessions passées + fichiers du projet) | `q "mots clés" [-p projet] [-t type] [--only] [--no-graph]` — comprend les dates (« hier », « le 12/11 », « il y a 3 semaines ») et le deuxième saut (« ← lien (sato) » : souvenir relié par un nom propre) ; « ≈ à vérifier » = confiance basse |
| Mémoriser | `add -t <type> -T "titre court" -b "fait + pourquoi + comment appliquer" [--tags a,b] [-i 1-5] [-p .\|none\|id] [--link id] [--due 10/11] [--replaces id] [--keys "synonymes, questions"] [--src utilisateur\|verifie\|deduit]` (étiquettes auto si absentes, liens suggérés affichés ; « hier », « dans 2 semaines » deviennent des dates réelles) |
| Question large (« où en est la boutique ? », « le point sur… ») | `q` place d'abord la **fiche de synthèse** de la communauté dominante (phrases les plus centrales de ses souvenirs, à-faire, ids), puis les souvenirs qu'elle ne cite pas · `fiche` liste les fiches · `fiche <n°\|mot\|id>` |
| Observations datées de la session (mémoire épisodique, façon Mastra) | `obs "🔴 décision, blocage" "🟡 avancée" "🟢 détail"` (« 14:20 » en tête au besoin ; « hier » devient une date) · `obs` les dernières · `obs -p projet --days 7` — retrouvées par `q` (texte ou date : « on a fait quoi hier ? »), condensées par le rêve après 7 jours ; jamais injectées au démarrage |
| Fait qui change (façon Zep / mem0) | `add … --replaces <ancien>` ou `supersede <nouveau> <ancien>` : l'ancien est archivé avec sa date de fin, la chaîne reste visible dans `show`. Un `add` sur le même sujet remplace tout seul l'ancien si une valeur change (chiffre, négation, « désormais », autre nom propre) ; jamais quand le titre vise une autre entité ou une autre date ; « ↻ remplace peut-être » = à confirmer |
| Voyage dans le temps | `q "sujet" --at 15/10\|hier\|"il y a 3 jours"` (le cerveau tel qu'il était) · `show <id> --history` (versions successives) · `history --diff <n°\|date>` (ce qui a changé depuis) |
| À-faire et échéances | `todo` (triés par échéance) · `done <id>` · `edit <id> --due "10/11"\|"demain"\|"dans 2 semaines"\|none` |
| Corriger / compléter | `edit <id> [-T …] [-b …] [-a "ajout"] [-i 4] [--add-tags x]` |
| Voir / lister | `show <id>` · `ls [-t type] [-p projet]` |
| Lier | `link <a> <b> [-r relates\|depends_on\|fixes\|supersedes\|contradicts]` (ou `[[id]]` dans un contenu) · `link --suggest` liens déduits à confirmer |
| Archiver | `rm <id>` (réversible : `edit <id> --unarchive`) · `--purge` = définitif (instantané pris avant) |
| Historique / annuler | `history` (instantanés) · `restore <n°>` (l'état courant est sauvegardé d'abord) |
| Sauvegardes (autre disque) | `backup` · `backup --list` · `backup --restore <archive.zip>` · `backup --to <dossier>` |

Types : `user` (qui est l'utilisateur), `feedback` (règle/préférence/correction), `project` (un dossier), `decision`,
`fact` (état/fait sur un travail en cours), `learning` (piège, solution, astuce), `reference` (lien, doc, ressource),
`entity` (outil, service, contact pro), `todo`.
Projet par défaut = projet du dossier courant (sauf `user`/`feedback`, globaux) ; `-p none` force le global.
Anti-doublon intégré : un `add` quasi identique complète le souvenir existant au lieu d'en créer un autre.

**Bon souvenir** : précis, actionnable, daté si utile. Ex. `add -t learning -T "Stats Shopify polluées par robots" -b "92 %
des sessions sont des bots US : filtrer session_country='France' avant tout calcul de conversion."`
**À ne pas stocker** : secrets, données sensibles ou de tiers, ce que le code/git disent déjà, l'éphémère.

## Ailleurs que dans l'onglet Code
| But | Commande |
|---|---|
| Coffre Obsidian / Markdown, synchronisé dans les deux sens (une note par souvenir, propriétés, liens `[[ ]]`) | `export --vault <dossier>` (dossier retenu ensuite : `export --vault`) — notes modifiées rapatriées champ par champ, nouvelle note dans « À trier » = nouveau souvenir, note supprimée = souvenir archivé, conflit = version Obsidian gardée dans « Conflits » · `--push` écrase le coffre |
| Serveur MCP (chat Claude, Cowork, tout client MCP) : outils memory_search / memory_add / memory_show / memory_todo / memory_context | `mcp` (stdio) · `install --mcp` l'enregistre dans l'app Claude (`--uninstall` le retire) |

## Graphe (façon graphify)
| But | Commande |
|---|---|
| Rapport : communautés, nœuds clés, liens surprenants, liens suggérés, doublons, trous, questions | `report [--print]` (→ `RAPPORT.md`) |
| Chemin entre deux souvenirs (liens explicites d'abord, puis déduits) | `path <id_a> <id_b>` |
| Communauté, centralité, concepts et liens déduits d'un souvenir | `show <id>` |
| Fiche de synthèse d'une communauté (extractive, régénérée seulement quand un membre change) | `fiche [n°\|mot\|id]` |
| Concepts repérés (outils, sujets, sigles, domaines, produits) et souvenirs liés | `concept [nom]` |
| Vue 3D interactive (mémoire, concepts, chronologie, Maj+clic = chemin, cartes de projets) | `viz --open` → `cerveau.html` (`cerveau-2d.html` hors ligne) |

Liens **déduits** = similarité du contenu (raison : mots communs ; confiance forte/moyenne/faible), jamais écrits
dans le graphe tant qu'ils ne sont pas confirmés par `link`. Analyse en cache (`state/analysis.json`), recalculée
seulement quand le savoir change.

## Projets (façon graphify)
| But | Commande |
|---|---|
| Cartographier / mettre à jour (incrémental) | `map [dossier] [--full] [--bg]` |
| Fichiers liés à un sujet | `files "paiement panier"` |
| Où est défini X (fonction, classe, variable d'env, route) | `where X` |
| Fiche d'un fichier ou symbole | `explain <fichier\|symbole>` |
| Dépendances | `deps <fichier>` · chemin entre deux fichiers : `path <a> <b>` |
| Projets connus | `proj` · `proj add <dossier> -T "Nom" -b "description"` |

Carte complète : `~/.claude/brain/projects/<id>/MAP.md` (structure, fichiers clés par centralité, modules, routes,
variables d'env, documents, cycles, TODO, fichiers sensibles jamais lus).

## Entretien
`journal [-p projet]` sessions passées · `journal -s "mots"` chercher dans leur texte · `context` ce qui est injecté ici · `recall "message"` tester le rappel ·
`consolidate [--dry-run]` fusion doublons/obsolètes · `dream` rêve (entretien : conflits, doublons, corrections entendues ; `--done`) · `stats` · `doctor` diagnostic (`doctor --fix` répare tout) ·
`bench` banc d'essai (qualité du rappel, faux rappels, tokens par démarrage, vitesse des hooks) · `tokens [--hours 48]` où partent les tokens (contexte relu, habitudes coûteuses, mesuré sur les transcripts) · `report` rapport du graphe ·
`pc` état du PC (RAM/CPU/GPU) et ce qu'on peut libérer (sessions inactives, serveurs MCP) · `pc --clean` ferme les serveurs MCP orphelins (parent mort) · `pc --history [h]` mesures de la veille ·
`viz --open` vue 3D (`~/.claude/brain/cerveau.html`, régénérée en fin de session) · `export` (MEMOIRES.md lisible) ·
`config recall.enabled false` · `install` réparer.
