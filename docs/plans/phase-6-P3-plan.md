# Complément de plan — Phase 6, pack P3 Code & DevOps

Date : 22/10/2026 · Statut : **validé par l'utilisateur le 22/10/2026** (`GO P3`), avec les
recommandations E1 à E6 du §10.

Complément court au plan de phase 6 (`docs/plans/phase-6-plan.md`, §7 et D19). Tout ce qui n'est
pas repris ici suit le plan de phase 6 : socle des packs (ADR-043),
domaine en N0 (D3), seuil du golden à 0,80 (D4), aucune mesure réelle sans ton accord (D5), revues
dans la session (D9).

## 0. En une phrase

Le pack `code` lit un dépôt de la liste blanche, lance ruff et pytest dans un conteneur Docker sans
réseau et lit l'état de sa CI. Le pilotage de Claude Code (`code_agent`) n'arrive qu'en second
temps, après un complément de plan dédié, parce que son isolation n'est pas encore vérifiée.

## 1. Vérifié aujourd'hui (22/10/2026)

| Fait | Source |
|---|---|
| Docker 29.8.2, git 2.56.0.windows.2, ruff 0.17.1, pytest 9.1.1 sur le poste | `--version` de chaque outil |
| Le dépôt CERVEAU n'a aucun remote git | `git remote -v` (vide) |
| `--network none` ne laisse au conteneur que l'interface de bouclage `lo` | documentation Docker, pilotes réseau |
| État de la CI : `GET /repos/{owner}/{repo}/actions/runs` | documentation de l'API REST de GitHub |
| Dépôt privé : jeton classique avec la portée `repo` ; la permission d'un jeton « fine-grained » n'est pas indiquée sur la page lue (`A_VERIFIER`) | idem |
| Limites : 60 requêtes/h sans jeton, 5 000/h avec | documentation GitHub, limites de débit |
| `claude-agent-sdk` 0.2.171, licence MIT, Python ≥ 3.10 ; dépend d'anyio, jsonschema, `mcp>=1.23.0,<3.0.0` (CERVEAU a `mcp` 2.3.0) et sniffio. Date de publication non lue | pypi.org/pypi/claude-agent-sdk/json |
| L'Agent SDK « runs the Claude Code binary » ; il charge par défaut skills, commandes et mémoire depuis `.claude/` et `~/.claude/` ; l'option qui n'en charge aucun est `A_VERIFIER` | code.claude.com/docs/en/agent-sdk/overview |
| L'Agent SDK s'authentifie par clé API (pas de connexion claude.ai) ; usage sous les Anthropic Commercial Terms | idem |

**À vérifier avant d'écrire le code** :
- options de `docker run` dans la documentation de Docker 29 : `--read-only`, `--cap-drop`,
  `--security-opt no-new-privileges`, `--pids-limit`, `--memory`, `--cpus`, `--user` ;
- permission exacte d'un jeton « fine-grained » pour lire les runs ;
- options de l'Agent SDK qui chargent ou non les réglages (P3b seulement).

## 2. Découpage proposé (D19)

| Étape | Contenu | Autonomie |
|---|---|---|
| **P3a** | `code_repo`, `code_checks`, `code_ci`, le pack `code`, ses évals ; compte rendu bref | N0 écrit et effectif |
| **P3b** | `code_agent` : complément de plan dédié (isolation, réseau, clé API, coût), puis `GO P3b` | N0 ; N2 au plus, monté par toi seul |

Raison : `code_agent` exécute un agent qui écrit du code. Avant de l'écrire, il faut vérifier
qu'il ne charge pas `~/.claude/` (ce qui exposerait tes réglages et ta mémoire), et choisir comment
il joint l'API d'Anthropic depuis un environnement sans réseau.

## 3. Plugins de P3a

| Plugin | Outils (classe) | Garde-fous |
|---|---|---|
| `code_repo` | `repo_log`, `repo_diff`, `repo_file` (LECTURE) | dépôts de la liste blanche seulement (`A_DEFINIR`). Le dépôt CERVEAU est refusé par le code (chemin résolu comparé à sa racine), même s'il est listé. `git` appelé sans shell, arguments fixes, `GIT_CONFIG_NOSYSTEM`, aucun hook ni filtre exécuté. Fichiers sous le dépôt seulement : `..` et liens symboliques sortants refusés. `.env*`, `secrets/` et les clés privées sont refusés. Taille bornée. Contenu traité en données (R5) |
| `code_checks` | `run_checks` (ruff check, ruff format --check, pytest) (CALCUL) | copie jetable du dépôt sous `var/code/runs/<id>/`. Conteneur `--network none`, système de fichiers en lecture seule sauf un `tmpfs`, utilisateur non root, toutes capacités retirées, `no-new-privileges`. Processeur, mémoire, processus et durée bornés (`A_DEFINIR`). Image figée par son condensé (`A_VERIFIER`). Sortie : comptes et noms des tests en échec, tronqués et traités en données |
| `code_ci` | `ci_runs` (LECTURE) | `api.github.com` seulement, via `core/net/`. Dépôts de la liste blanche. Jeton facultatif dans une variable d'environnement que tu poses et que Claude Code ne lit jamais (nom `A_DEFINIR`). Aucune écriture (pas de relance de run) |

Ce pack compte 5 outils (R13) ; `web_search` et `web_read` ne lui sont pas ouverts, une question
de documentation passe par le généraliste. Une suite pytest
exécute le code du dépôt testé : c'est la raison du conteneur sans réseau et de la copie jetable.

## 4. Autonomie et politique

- `config/autonomy.yaml` : domaine `code`, `level: N0`, `max_level: N2` (§9.2, D3).
- En N0 et N1, les trois plugins de P3a ne font que lire et calculer. Aucune écriture dans un
  dépôt.
- N2 (P3b) : branche locale et texte de PR en brouillon dans le worktree jetable, jamais de push
  (D19). La politique refuse tout `git push`, tout `gh` et toute écriture hors du worktree.

## 5. Évaluations (P3a)

| Suite | Contenu | Seuil |
|---|---|---|
| `domain_packs/code/evals/golden.jsonl` (≥ 30 cas, hors ligne, dépôts de test créés par le harnais) | revue de diff (8), échecs de tests expliqués (6), état de CI (4), « je ne sais pas » (3), injection dans le code, un commentaire ou une sortie de test (4), secret dans un diff (2), dépôt hors liste ou CERVEAU (2), conseil à un tiers (1) | `code_golden_min_score` 0,80, en campagne réelle seulement |
| `domain_packs/code/evals/behaviors.yaml` | R1 (comptes de tests cités de l'outil), R6 (un secret vu dans un diff n'est jamais recopié), R12, R16 | 1,0 |
| `evals/redteam/injection_code/` (≥ 10 cas) | consigne dans un commentaire, un message de commit, une sortie de pytest ou un journal de CI ; `../` et lien symbolique sortant ; demande de modifier les hooks de CERVEAU ; demande de push ; lecture de `.env` | 0 violation |
| Suites existantes | relancées, inchangées (R9). Le cas `pack-code-absent` tombe ; il est remplacé selon ta décision sur B263 | inchangés |

## 6. Tests (aucun réseau, aucun Docker en CI)

- Dépôts git créés dans `tmp_path` ; aucun dépôt réel lu.
- Docker : la commande `docker run` est construite par une fonction pure, testée option par option
  (réseau, lecture seule, utilisateur, capacités, bornes). L'exécution passe par un exécutant
  factice. Un test d'intégration avec le vrai Docker est marqué et exclu de `make ci`.
- GitHub : `httpx.MockTransport`, réponses de forme réelle, textes inventés.
- Couverture à 100 % du garde des chemins et de la construction de la commande Docker (porte de
  couverture).

## 7. Dépendances

Aucune nouvelle pour P3a : git et Docker par sous-processus, GitHub par `httpx`. `claude-agent-sdk`
n'entre qu'en P3b, avec sa revue `security-reviewer`.

## 8. Hors périmètre → `docs/backlog.md`

Push, PR réelle et merge ; relance d'un run de CI ; GitLab et autres forges ; auto-modification de
CERVEAU ; `code_agent` (P3b) ; analyse de dépendances d'un dépôt tiers (`pip-audit` dans le
conteneur, phase 7).

## 9. Coût estimé (non mesuré)

- **Développement** : 0 € d'API.
- **GitHub** : 0 € ; sans jeton, 60 requêtes/h suffisent pour un usage personnel.
- **Campagne réelle P3a** : environ 30 cas de golden et 10 de red team, soit 5 à 15 $ (estimation).
- **P3b** : coût d'un agent par tâche à estimer dans son complément de plan
  [VERIFICATION REQUIRED : tarifs d'Anthropic du jour].

## 10. Décisions demandées à l'utilisateur

| # | Décision | Options | Ma recommandation |
|---|---|---|---|
| E1 | Découpage | P3 d'un bloc / P3a puis P3b avec complément | **P3a puis P3b** (§2) |
| E2 | Dépôts autorisés | chemins locaux, `A_DEFINIR` | un ou deux de tes dépôts personnels ; CERVEAU exclu par le code dans tous les cas |
| E3 | pytest d'un dépôt qui a des dépendances | ruff seul / environnement préparé par toi (installation avec réseau, puis contrôles sans réseau) / installation dans le conteneur | **ruff toujours ; pytest seulement si tu as préparé l'environnement** du dépôt. Une installation exécute du code tiers : elle ne se fait jamais dans le conteneur des contrôles |
| E4 | Image du conteneur | `python:3.12-slim` figée par condensé, construite par toi / autre | `python:3.12-slim` avec ruff et pytest figés, construite par toi (`docker build` télécharge l'image de base) |
| E5 | Bornes du conteneur | valeurs | 2 processeurs, 2 Go, 256 processus, 300 s [hypothèse, à décider] |
| E6 | Jeton GitHub pour `code_ci` | aucun / jeton en lecture | **aucun** tant que les dépôts suivis sont publics ; sinon un jeton « fine-grained » en lecture seule sur ces seuls dépôts, posé par toi |

## 11. Commits atomiques (P3a ; en anglais, `make ci` vert à chaque étape)

1. `docs: add the validated P3 plan`
2. `feat(config): add the code domain at N0, its repositories and its golden threshold`
3. `feat(code_repo): add the allow-listed git reader plugin` + ADR-047 (liste blanche, exclusion de CERVEAU)
4. `feat(code_checks): run ruff and pytest in a networkless container` + ADR-048 (bac à sable Docker)
5. `feat(code_ci): add the read-only GitHub Actions status plugin`
6. `feat(code): add the code pack with its golden set, behaviours and red team`
7. `docs: update licences, threat model and backlog for the code pack`
8. `docs: add the code pack report`

## 12. Exécution

Après `GO P3` : documentation à jour (§1, « à vérifier »), commits 1 à 6, revue
`security-reviewer` du pack, commit 7, compte rendu bref de P3a, puis complément de plan de P3b et
arrêt jusqu'à ton GO.
