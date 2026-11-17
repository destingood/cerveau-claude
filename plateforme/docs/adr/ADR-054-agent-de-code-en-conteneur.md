# ADR-054 — Agent de code : Claude Code dans un conteneur Linux, patch calculé par CERVEAU

- Statut : **proposé** (F1, F4, F5, F6, F8 et F9 du complément de plan P3b, validés par l'utilisateur le
  22/10/2026)
- Date : 2026-10-22
- Phase : 6 (P3b)

## Contexte
Le pack Code (P3a) lit les dépôts et lance des contrôles ; P3b lui ajoute `code_agent`, qui confie
une tâche de code à Claude Code. L'agent lit et modifie des fichiers et lance des commandes : il
lui faut une frontière (R2, R5, R6), des bornes (F5) et un résultat que l'utilisateur relit (N0, F9).
Faits vérifiés le 22/10/2026 sur code.claude.com/docs/en/agent-sdk/python :
- `permission_mode` : `default`, `acceptEdits`, `plan`, `dontAsk`, `bypassPermissions`, `auto` ;
  `dontAsk` refuse tout ce qui n'est pas pré-approuvé, sans rien demander ;
- `tools` fixe les outils de base ; `allowed_tools` les approuve sans restreindre ; un nom nu dans
  `disallowed_tools` retire l'outil du contexte ; l'outil des sous-agents est `Agent` (alias
  `Task`) ;
- `setting_sources=[]` n'ouvre aucun réglage (utilisateur, projet, local) ; `strict_mcp_config`
  n'utilise que les serveurs de `mcp_servers` ; `env` s'ajoute à l'environnement hérité ;
- `max_budget_usd` est une estimation côté client, qui peut être dépassée ; `ResultError` hérite
  de `ProcessError` (SDK ≥ 0.2.140) ;
- le paquet `claude-agent-sdk` (MIT, 0.2.172 publiée sur PyPI le 22/10/2026, jamais installée dans
  l'environnement de CERVEAU) embarque le CLI de Claude Code, sous les conditions commerciales
  d'Anthropic (« All rights reserved ») : R14.

## Options
1. **SDK sous Windows, sur l'hôte** : rien à construire, mais Bash tourne avec les droits de
   l'utilisateur, voit ses fichiers et Internet ; aucune frontière que CERVEAU contrôle (F1).
2. **SDK dans un conteneur Linux** : une image de plus à construire (l'utilisateur), Docker requis ; la
   frontière est le conteneur, testée commande par commande.
3. **Boucle de CERVEAU sans shell** : le modèle propose des patchs avec des outils de lecture ;
   pas de Claude Code ni de tests lancés par l'agent, écart au §P3 du méga-prompt.

## Décision
Option 2 (`core/code/agent.py`, `core/code/agent_runner.py`, `core/code/patch.py`,
`plugins/code_agent`, `infra/agent/agent.Dockerfile`).
- Deux conteneurs par tâche sur un réseau Docker `--internal` créé pour elle : l'agent et le proxy
  de l'API (ADR-053), seul à recevoir la clé, par son nom, et seul à sortir, par un second réseau
  propre à la tâche (`cerveau-agent-out-<id>`, ICC désactivé), jamais par le `bridge` partagé.
- Conteneur de l'agent : la copie jetable d'un commit (fichiers lus dans les objets git, sans les
  fichiers sensibles) comme seul montage en écriture, `tmpfs` de 512 Mo, racine en lecture seule,
  utilisateur 65534, `--cap-drop ALL`, `no-new-privileges`, `--init`, 2 processeurs, 4096 Mo sans
  swap, 512 processus, 100 Mio par fichier (`--ulimit fsize`) (F5) ; image désignée par son
  identifiant `sha256`, `--pull never`. La copie est surveillée pendant le travail : au-delà de
  50 000 entrées ou 500 Mo, les deux conteneurs sont arrêtés.
- Durée de vie propre à chaque conteneur, même si CERVEAU meurt : le runner s'arrête seul
  (`signal.alarm`) 30 s après la durée de l'agent ; le proxy s'arrête au reste du budget de
  l'appel et dès que `governance/kill_switch/KILL` existe (dossier monté en lecture seule, R4).
  Les deux portent l'étiquette `cerveau.code_agent=1`.
- Runner : ni réglages, ni `CLAUDE.md`, ni mémoire, ni serveur MCP ; outils Read, Edit, Write,
  Glob, Grep et Bash (F4) ; `Agent`, `Task`, WebFetch, WebSearch et `mcp__*` refusés ; `dontAsk` ;
  `claude-sonnet-5-5` (F6), 30 tours ; clé factice et `ANTHROPIC_BASE_URL` vers le proxy, qui tient
  le vrai plafond de 2 $ (F5). Consigne cadrée, 8 000 caractères au plus. Sortie : une ligne JSON,
  traitée comme donnée non fiable (une commande de l'agent peut l'écrire).
- Durée : 900 s par appel (F8) ; l'agent reçoit au plus 750 s (30 s gardées pour arrêter les
  conteneurs, 120 s pour le patch et les contrôles). Kill switch relu chaque seconde (R4).
- Patch : calculé par CERVEAU en comparant la copie aux blobs du commit, sans commande git sur le
  `.git` de la copie ; liens, jonctions et fichiers spéciaux listés et écartés, jamais suivis ;
  fichier sensible jamais lu (R6) ; chemins à risque (CI, hooks, `conftest.py`…) signalés ;
  secrets masqués ; bornes de lecture et de taille. Calculé seulement après que `docker ps` (par
  étiquette et nom) a montré les deux conteneurs arrêtés ; sinon, aucun patch. Écrit sous
  `var/code/agent/<id>/`, puis `code_checks` relancé sur la copie modifiée, kill switch surveillé :
  ses comptes sont les seuls cités (R1). Ils sont marqués non probants (`conclusive: false`) si
  le patch touche un fichier qui règle les contrôles (`conftest.py`, `pyproject.toml`,
  `ruff.toml`, `pytest.ini`, `setup.cfg`, `.coveragerc`, `sitecustomize.py`, `*.pth`…), écarte
  des fichiers ou masque un secret : la copie contrôlée n'est alors pas ce que le patch redonne.
- Dépense : l'état du proxy, lu une fois les conteneurs arrêtés ; illisible ou arrêt non
  confirmé, le plafond de la tâche est imputé (R7). Ses jetons comptés entrent dans `max_tokens`
  (`per_code_agent`) ; un plafond imputé n'en compte aucun : une requête confie donc une tâche au
  plus (`MAX_TASKS_PER_REQUEST`, revue `risk-gate-auditor`), la deuxième est refusée avant tout
  conteneur et journalisée. N0 : l'utilisateur applique le patch lui-même (`git apply`) ; rien n'est écrit
  dans ses dépôts.

## Conséquences
- La clé n'entre jamais dans le conteneur de l'agent ; une sortie réseau, un réglage ou un outil
  non listé exigent de changer le code testé, pas un fichier de la copie.
- Les options du SDK (outils, `dontAsk`, réglages, MCP) ne sont pas une frontière : par Bash,
  l'agent peut relancer le CLI avec d'autres options. Seuls le conteneur (aucune sortie, aucun
  secret, copie jetable) et le proxy (chemin, modèles, plafond) en sont une.
- Limites assumées : l'image n'a ni git ni les dépendances du dépôt (l'agent ne lance que ruff et
  le pytest de l'image) ; un changement de mode d'un fichier n'est pas vu ; après un délai ou un
  kill switch, aucun patch n'est calculé et le travail est perdu (B289) ; un échec précoce impute
  le plafond. Les deux réseaux de la tâche sont toujours retirés, même après une création ratée.
- L'alarme du runner n'est pas une frontière : un processus de l'agent, du même utilisateur, peut
  la neutraliser (`ptrace`, signal). Restent la durée de vie et le plafond du proxy, l'arrêt par
  CERVEAU et l'étiquette, qui retrouve les restes après un arrêt brutal (`infra/agent/README.md`).
- `A_VERIFIER` au premier test réel (B287, avec B286) : réseau `--internal` sans sortie sous
  Docker Desktop, ni résolution DNS externe ni accès à `host.docker.internal` ; clé factice
  acceptée et seul `POST /v1/messages` appelé par le CLI ; écriture de 65534 dans la copie montée
  (hôte Linux) ; mémoire du CLI dans 4096 Mo ; démarrage du proxy en 15 s ; lien créé par l'agent
  sur un montage Windows, vu comme lien ; `KILL` créé après le démarrage, visible dans le dossier
  monté et lisible par 65534 (Docker Desktop) ; unité de `--ulimit fsize` (octets attendus).
- Le mode `--restricted` du CLI (v2.1.248 ou plus) retire les outils qui lancent des commandes,
  donc Bash, contraire à F4 : à réévaluer pour une variante sans Bash (B288).
- Une nouvelle version du SDK ou du CLI passe par une revue `security-reviewer` et les évals (R9).
- Réversible : `code_agent` est un plugin isolé du pack Code ; l'enlever du pack le désactive.
