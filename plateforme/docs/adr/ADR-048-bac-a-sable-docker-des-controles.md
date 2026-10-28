# ADR-048 — Bac à sable Docker des contrôles de code (plugin `code_checks`)

- Statut : proposé (pytest seulement dans un environnement préparé, image construite par Lucas et
  plafonds validés par E3, E4 et E5 du complément de plan de P3)
- Date : 2026-10-22
- Phase : 6 (P3a, pack Code)

## Contexte
`run_checks` lance ruff check, ruff format --check et pytest sur un dépôt de la liste blanche
(ADR-047). Une suite de tests exécute le code du dépôt : ce code est non fiable (R5) et peut
chercher à lire des secrets (R6), à joindre le réseau, à écrire dans le dépôt ou sur le poste, ou
à épuiser la machine. E3 : ruff toujours, pytest seulement si Lucas a préparé l'environnement du
dépôt, jamais d'installation dans le conteneur. E4 : image `python:3.12-slim` avec ruff et pytest
figés, construite par Lucas, désignée par son condensé ou son ID (`A_DEFINIR`). E5 : 2 processeurs,
2 Go, 256 processus, 300 s.

Faits vérifiés le 2026-10-22 :
- `docker run` (docs.docker.com, référence de `docker container run`) documente `--network none`,
  `--read-only`, `--tmpfs`, `--user`, `--cap-drop`, `--security-opt no-new-privileges=true`,
  `--pids-limit`, `--memory`, `--memory-swap`, `--cpus`, `--pull never`, `--init`, `--mount
  type=bind,…,readonly`, `--entrypoint` ; ses propres codes de sortie sont 125 (erreur du démon ou
  de Docker), 126 (commande non exécutable) et 127 (commande introuvable) ;
- codes de sortie : pytest 0 à 5 (documentation de pytest, « Exit codes ») ; ruff check 0, 1, 2 ;
  ruff 0.17.1 écrit en JSON `code`, `filename` (absolu), `location`, `message`, etc., et `format
  --check` y signale chaque fichier avec le code `unformatted` ;
- un appel d'outil MCP dure 30 s au plus (`TOOL_TIMEOUT_S`, `core/mcp/adapter.py`) ;
- le démon Docker est arrêté sur le poste de Lucas : aucun conteneur réel n'a été lancé pour cet ADR.

## Options
1. **Conteneur Docker durci, copie jetable** : isolement réseau, système de fichiers et ressources
   par le moteur ; Docker Engine sous Apache-2.0, Docker Desktop gratuit pour un usage personnel
   (R14, `docs/licences.md`) ; aucune dépendance Python nouvelle.
2. **Sous-processus local** (ruff et pytest de l'environnement de CERVEAU) : simple, mais le code du
   dépôt lit le poste, les variables d'environnement et le réseau ; rejeté.
3. **Machine virtuelle ou WSL dédiée** : isolement plus fort, mais démarrage lent, au-delà du budget
   d'un appel d'outil, et installation lourde pour Lucas.
4. **Service distant ou CI du dépôt** : aucun code sur le poste, mais exige un jeton et un envoi de
   code hors du poste (E6 : aucun jeton) ; la lecture du statut CI est laissée à `code_ci`.

## Décision
Option 1, avec ces règles, toutes testées (`tests/test_code_sandbox.py`, `tests/test_code_process.py`,
`tests/test_code_checks.py`, `plugins/code_checks/tests/`) :
- **Copie depuis les objets git** (`copy_tree`) : les fichiers d'un commit, lus par `ls-tree` puis
  un seul `cat-file --batch`, écrits dans un dossier neuf `var/code/runs/<uuid>/`. Ni `checkout`,
  ni `archive` : aucun filtre du dépôt ne s'exécute (ADR-047). Fichiers sensibles jamais écrits,
  seulement nommés comme retenus ; liens symboliques, sous-modules, chemins non portables ou en
  collision de casse ignorés et nommés. Plafonds : 5 000 fichiers et 50 Mo, vérifiés avant toute
  écriture. La copie est supprimée à la fin de l'appel ; un échec de suppression est signalé
  (`removed: false`).
- **Commande** (`docker_command`, fonction pure) : `run --rm --name cerveau-check-<id> --pull never
  --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=65536k --user 65534:65534
  --cap-drop ALL --security-opt no-new-privileges=true --pids-limit N --memory Xm --memory-swap Xm
  --cpus C --init --mount type=bind,source=<copie>,target=/work,readonly --workdir /work
  --env HOME=/tmp --env PYTHONDONTWRITEBYTECODE=1 --entrypoint <programme> <image> <arguments>`.
  Lancée sans shell ; un chemin de copie contenant `,`, `=` ou `"` est refusé.
- **Image par contenu** : `config/code.yaml`, `checks.image` ; `A_DEFINIR` bloque l'outil (R7).
  Jamais téléchargée (`--pull never`) ni construite par CERVEAU. pytest tourne dans l'image propre
  au dépôt (`image` et `pytest: true` de son entrée), ruff dans l'image commune ; rien n'est
  installé dans le conteneur. Sans environnement préparé, pytest est `non_lance`.
- **Temps** : un budget de 25 s par appel, partagé par les conteneurs et compté dès le début de la
  copie, sous les 30 s de l'appel d'outil ; aucun conteneur n'est lancé avec moins de 2 s
  restantes. Les 300 s de E5 restent le plafond configurable, inatteignable aujourd'hui.
- **Sorties** : 4 Mo au plus par conteneur. Délai dépassé ou sortie tronquée : `docker kill` par
  nom (arrêter le client seul laisserait tourner le conteneur), statut `delai` ou `erreur`.
- **Environnement du client Docker** réduit à ce qu'il lui faut pour trouver son moteur (`PATH`,
  `SYSTEMROOT`, `TEMP`, `TMP`, `HOME`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `PROGRAMDATA`,
  `DOCKER_HOST`, `DOCKER_CONTEXT`, `DOCKER_CONFIG`) ; aucune variable n'entre dans le conteneur
  hors des deux ci-dessus.
- **Statuts** : `ok`, `echec`, `erreur`, `delai`, `non_lance`, `aucun_test` ; codes 125 à 127
  traduits ; sortie de ruff illisible ou incohérente avec son code de sortie = `erreur`. Comptes
  par code, 50 diagnostics et noms de tests au plus ; textes tronqués, secrets masqués, caractères
  invisibles montrés `⟨U+XXXX⟩`, tout reste une donnée (R5).
- **Autonomie** : un outil `CALCUL` (`readOnly`, `openWorld: false`), plafond N1, pack à N0.

## Conséquences
- L'outil reste bloqué tant que Lucas n'a pas construit l'image et rempli `checks.image` et
  `repositories`.
- `A_VERIFIER` (backlog) : image désignée par un ID local `sha256:` ; chemins Windows dans
  `--mount` ; lecture de la copie par l'utilisateur 65534 ; `pids.max` sous Docker Desktop ; code
  125 quand le démon est arrêté. `tests/test_code_checks_docker.py` contrôle tout cela depuis
  l'intérieur d'un vrai conteneur ; il est ignoré sans `CERVEAU_CHECKS_IMAGE` et se lance à la
  main après chaque construction de l'image ou mise à jour de Docker.
- Les résultats d'un dépôt hostile ne sont pas fiables (il peut fausser ruff ou pytest) ; seul le
  confinement l'est. Le mode exécutable des fichiers n'est pas conservé dans la copie.
- Réversible : le plugin est isolé ; retirer `code_checks` du pack suffit.
