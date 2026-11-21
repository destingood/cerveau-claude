# 🧠 Cerveau — la mémoire en détail

Toutes les commandes et options de la mémoire. Commande : `python "$HOME/.claude/brain/brain.py" <commande>`.

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
