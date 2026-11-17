# ADR-003 — Garde-fous Claude Code en Python et ACL Windows pour `config/live.yaml`

- Statut : accepté (l'utilisateur, 2026-10-18, décision D13 du plan de phase 1)
- Date : 2026-10-17
- Phase : 0

## Contexte
R3 impose trois niveaux de protection de `config/live.yaml` : règle de permission Claude Code, hook
bloquant, droits du système. La section 16.5 décrit des hooks en bash + jq (`protect-paths.sh`,
`guard-bash.sh`) et des droits Unix (propriétaire dédié, lecture seule). Or le développement se
fait sous Windows 11, où Claude Code exécute des commandes Bash (Git Bash) et PowerShell, et où
`jq` n'est pas installé. Les hooks doivent être testés (section 16.5) et échouer fermé.

## Options
1. **bash + jq, comme dans la spécification** : dépend de Git Bash et de jq ; ne voit pas l'outil
   PowerShell ; analyse de commandes fragile en shell ; tests difficiles.
2. **Hooks Python, bibliothèque standard seule** : un code pour Windows et Linux ; analyse
   structurée des commandes Bash et PowerShell ; tests pytest ; exige `python` dans le PATH.
3. **Hooks PowerShell** : natifs sous Windows, inutilisables tels quels sur le VPS Debian.

## Décision
Option 2, et pour le niveau 3 une ACL Windows sur le poste de l'utilisateur :
- `.claude/hooks/protect_paths.py` (matcher `Edit|Write|NotebookEdit`) et `guard_shell.py`
  (matcher `Bash|PowerShell`) refusent par le code 2 ; une erreur interne refuse aussi
  (`onFailure: "block"`) ; chaque refus est inscrit au journal d'audit chaîné (R11) ;
- `quick_checks.py` (PostToolUse) relance `cerveau config check` et la validation des manifestes ;
- 270 tests dans `tests/hooks/`, dont un rejeu de bout en bout du message réel de Claude Code ;
- `infra/windows/protect-live.ps1`, lancé à la main par l'utilisateur en administrateur : propriétaire
  Administrateurs, héritage coupé, lecture seule pour son compte ; modes `-Check` et `-Unprotect` ;
- sur le VPS (phase de déploiement) : propriétaire dédié et `chmod 444`, comme prévu en 16.5.

## Conséquences
- Plus simple : un seul garde-fou testé pour les deux shells et les deux systèmes.
- Plus difficile : sans `python` dans le PATH, toute commande et toute écriture est refusée
  (échec fermé voulu, mais bloquant) ; l'analyse de commandes ne couvre pas tout (variables,
  scripts lancés, archives) : liste dans `docs/threat-model.md`. Les hooks restent un confort ;
  la protection effective est l'ACL.
- Limite de l'ACL : le compte de l'utilisateur garde le contrôle du dossier `config/`, donc peut supprimer
  ou renommer le fichier puis le recréer. Parade au backlog : le chargeur refusera
  `enabled: true` si `live.yaml` n'appartient pas aux Administrateurs (ou à root).
- Réversible : oui (`protect-live.ps1 -Unprotect`, hooks retirables par l'utilisateur).
