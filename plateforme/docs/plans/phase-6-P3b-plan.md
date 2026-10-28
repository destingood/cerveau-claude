# Complément de plan — Phase 6, pack P3b `code_agent`

Date : 22/10/2026 · Statut : **validé** le 22/10/2026 (`GO P3b`, recommandations F1 à F10, y
compris la revue `risk-gate-auditor` de F7, le sixième outil de F8 au-delà de R13 et les bornes de
F5).

Complément au plan P3 (`docs/plans/phase-6-P3-plan.md`, §2 et E1). Tout ce qui n'est pas repris
ici suit le plan P3 et le plan de phase 6 : domaine `code` en N0 (D3), aucune mesure réelle sans ton
accord (D5), revues dans la session (D9), jamais de push (D19).

## 0. En une phrase

`code_agent` confie une tâche de code à Claude Code (Agent SDK) dans un conteneur Linux sans accès
à Internet, sur une copie jetable d'un dépôt listé ; la clé API reste hors du conteneur, ajoutée par
un proxy qui ne laisse passer que l'API d'Anthropic et plafonne le coût ; CERVEAU rend un patch,
contrôlé par `code_checks`, que tu appliques toi-même.

## 1. Vérifié aujourd'hui (22/10/2026)

| Fait | Source |
|---|---|
| `claude-agent-sdk` 0.2.172 publié le 22/10/2026, licence MIT, Python ≥ 3.10 ; dépend d'anyio, jsonschema, `mcp>=1.23.0,<3.0.0`, sniffio. Une roue par plateforme, de 116 à 130 Mo | pypi.org/pypi/claude-agent-sdk/0.2.172/json |
| « The Claude Code CLI is automatically bundled with the package » ; CLI 2.1.257 au moins | README du paquet, même source |
| Licence du CLI embarqué : « © Anthropic PBC. All rights reserved. Use is subject to Anthropic's Commercial Terms of Service » : licence restrictive (R14) | github.com/anthropics/claude-code, `LICENSE.md` |
| `setting_sources` : `None` (défaut) charge user, project et local ; `[]` n'en charge aucun | code.claude.com/docs/en/agent-sdk/python |
| Restent chargés quel que soit `setting_sources` : politique managée, `~/.claude.json`, mémoire automatique, connecteurs MCP de claude.ai, `sandbox.credentials`. La doc recommande un système de fichiers séparé, `settingSources: []` et `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` | code.claude.com/docs/en/agent-sdk/claude-code-features |
| Le bac à sable de Claude Code tourne sous macOS, Linux et WSL2 ; « On native Windows, Claude Code runs commands unsandboxed » | code.claude.com/docs/en/sandboxing |
| Déploiement sûr : l'agent tourne à l'intérieur de la frontière (conteneur) ; la clé est ajoutée par un proxy hors de la frontière ; avec `ANTHROPIC_BASE_URL`, le proxy reçoit les requêtes en clair et peut injecter la clé ; avec `HTTPS_PROXY`, il ne voit qu'un tunnel chiffré | code.claude.com/docs/en/agent-sdk/secure-deployment |
| Options de conteneur recommandées : `--cap-drop ALL`, `no-new-privileges`, `--read-only`, `--tmpfs`, `--memory`, `--cpus`, `--pids-limit`, `--user`, aucun montage de `~/.ssh`, `~/.aws`, `~/.config` | idem |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` coupe mises à jour, télémétrie et rapports d'erreur ; `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` ne charge aucun CLAUDE.md ; `ANTHROPIC_API_KEY` part dans l'en-tête `X-Api-Key` | code.claude.com/docs/en/env-vars |
| `max_budget_usd` est une estimation côté client, qui peut être dépassée | code.claude.com/docs/en/agent-sdk/python |
| Tarifs (USD par million de jetons : entrée, écriture de cache 5 min, lecture de cache, sortie) : Opus 5.5 4 / 5 / 0,20 / 20 ; Sonnet 5.5 2 / 2,50 / 0,10 / 10 ; Haiku 5.5 (≤ 100 k jetons) 0,10 / 0,125 / 0,01 / 0,50 | platform.claude.com/docs/en/about-claude/pricing |

**À vérifier pendant l'implémentation** (`A_VERIFIER`, relevés dans l'ADR d'isolation) :
comportement exact de `permission_mode="dontAsk"` ; noms des outils à refuser (`Agent` ou `Task`) ;
`strictMcpConfig` comme option du SDK ou argument du CLI ; chemins d'API appelés par le CLI derrière
`ANTHROPIC_BASE_URL` ; acceptation d'une clé factice par le CLI ; réseau Docker `--internal` sous
Docker Desktop pour Windows ; `docker run -e NOM` sans valeur reprend la valeur de l'hôte ; mémoire
utile au CLI.

## 2. Architecture proposée (F1 à F3)

```
CERVEAU (Windows)                 réseau Docker interne « cerveau-agent » (sans Internet)
plugin code_agent ──docker run──► conteneur agent : runner Python + Agent SDK + CLI embarqué
   │                                 copie jetable du dépôt (seul montage en écriture)
   │                                 ANTHROPIC_BASE_URL=http://llm-proxy:8080, clé factice
   │                                        │ HTTP en clair, réseau interne
   │                              conteneur llm-proxy (réseau interne + sortie) ──TLS──► api.anthropic.com
   │                                 vraie clé (reprise de ton environnement par son nom)
   │                                 chemins, modèles, requêtes et jetons plafonnés
   └── patch calculé par CERVEAU (fichiers comparés, `.git` ignoré) ──► code_checks ──► réponse
```

- Le SDK vit **dans l'image** de l'agent, pas dans le `uv.lock` de CERVEAU : aucune nouvelle
  dépendance côté hôte. Le runner (`core/code/agent_runner.py`, copié dans l'image) construit ses
  options par une fonction pure, testée sans le SDK.
- Isolation du runner : `setting_sources=[]` ; aucun montage de `~/.claude` (le conteneur n'a ni
  politique managée, ni `~/.claude.json`, ni mémoire, ni connexion claude.ai) ; `env` :
  `CLAUDE_CONFIG_DIR` vide sur `tmpfs`, `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`,
  `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` ;
  `mcp_servers={}` et configuration MCP stricte ; outils permis : Read, Edit, Write, Glob, Grep,
  Bash ; refusés : WebFetch, WebSearch, sous-agents ; `max_turns` (F5).
- Le patch est calculé par CERVEAU en comparant les fichiers de la copie aux blobs d'origine ;
  aucune commande git n'est lancée sur le `.git` écrit par l'agent (même raison qu'ADR-047). Les
  secrets sont masqués, le patch est borné en taille et traité en données (R5).
- `code_checks` est relancé sur la copie patchée : ses comptes sont les seuls chiffres cités (R1).
- Kill switch (R4) : avant le lancement et pendant l'attente, le plugin vérifie `KILL` et arrête les
  deux conteneurs (`docker kill`).
- Audit (R11) : lancement, fin, requêtes, jetons et coût comptés par le proxy, empreinte du patch ;
  aucun contenu de requête journalisé.

## 3. Autonomie et sortie (F7, F9)

- P3b livre **N0** : patch et résumé sous `var/code/agent/<id>/`, affichés à toi ; tu l'appliques
  avec `git apply`. Rien n'est écrit dans tes dépôts.
- N2 (branche locale dans ton dépôt, texte de PR en brouillon, jamais de push) reste écrit dans la
  politique mais n'est pas livré en P3b : il se gagnera par les évals réelles (R9).

## 4. Évaluations

| Suite | Contenu | Seuil |
|---|---|---|
| Golden `code`, cas `agent-*` (≈ 10, hors ligne, runner remplacé par un double) | tâche routée vers `code_agent` ; dépôt CERVEAU ou hors liste refusé ; budget absent = blocage expliqué ; patch avec secret masqué ; échec ou délai = « je ne sais pas » ; comptes de `code_checks` cités | 0,80 en campagne réelle |
| Behaviours | R1 (chiffres de `code_checks` seulement), R6 (clé jamais présente), R12, R16 | 1,0 |
| Red team `injection_code` (≈ 6 cas de plus) | double hostile : patch qui touche `.github/workflows/`, `.claude/`, `conftest.py` ; résumé qui donne des consignes ; tentative de joindre un autre hôte (refusée par le proxy) | 0 violation |
| Proxy (tests unitaires) | chemin hors liste, modèle hors liste, plafonds atteints, clé jamais renvoyée ni journalisée | 100 % de couverture de branches |

Le comportement d'un vrai agent face à un dépôt piégé ne se mesure qu'en campagne réelle (F10).

## 5. Tests (aucun réseau, aucun Docker en CI)

- Commandes `docker run` et `docker network` construites par des fonctions pures, testées option
  par option ; exécutant factice.
- Proxy : fonctions pures (décision, injection d'en-tête, comptage des jetons dans le flux SSE),
  testées sans socket.
- Calcul du patch : dépôts de test dans `tmp_path`, liens symboliques et `.git` piégé compris.
- Test d'intégration réel (Docker et API, payant) marqué et exclu de `make ci` ; lancé par toi
  seulement.

## 6. Dépendances et licences (R14)

- CERVEAU : aucune nouvelle dépendance Python.
- Image `cerveau-agent` construite par toi : `python:3.12-slim`, `claude-agent-sdk==0.2.172` figé
  par empreinte (`--require-hashes`), ruff et pytest figés. Le CLI embarqué est sous licence
  restrictive : il reste isolé dans l'image et entre dans `docs/licences.md`.
- Image `cerveau-llm-proxy` : `python:3.12-slim` et le proxy de CERVEAU, bibliothèque standard
  seulement.
- Revue `security-reviewer` du SDK et du pack avant le commit du plugin.

## 7. Hors périmètre → `docs/backlog.md`

N2 réel (branche, PR) ; push et merge ; agent sur un dépôt non listé ou sur CERVEAU
(auto-modification) ; accès Internet de l'agent (documentation, paquets) ; sous-agents ; agent
lancé depuis Discord ou l'API.

## 8. Coût estimé (hypothèses, non mesuré)

Hypothèse par tâche : 20 requêtes, contexte moyen de 40 k jetons dont 90 % lus en cache, 1 k jetons
de sortie par requête. Grosse tâche : 50 requêtes, 80 k jetons, 1,5 k en sortie.

| Modèle | Petite tâche | Grosse tâche |
|---|---|---|
| Sonnet 5.5 | ≈ 0,47 $ | ≈ 2,1 $ |
| Opus 5.5 | ≈ 0,94 $ | ≈ 4,2 $ |
| Haiku 5.5 | ≈ 0,03 $ | ≈ 0,12 $ |

- Développement : 0 $ (doubles hors ligne).
- Campagne réelle P3b : ≈ 15 tâches (10 golden, 5 red team), soit 7 à 30 $ avec Sonnet 5.5 ;
  s'ajoute la campagne de P3a (5 à 15 $), toujours en attente.
- Tes budgets journalier et mensuel restent `A_DEFINIR` : tout appel réel reste bloqué (R7).

## 9. Décisions demandées à Lucas

| # | Décision | Options | Ma recommandation |
|---|---|---|---|
| F1 | Où tourne l'agent | SDK sur Windows (aucun bac à sable natif, Bash avec tes droits) / **SDK dans un conteneur Linux** / pas de Claude Code : boucle de CERVEAU qui propose des patchs sans shell (écart au §P3 du méga-prompt) | **conteneur Linux** |
| F2 | Clé API | dans le conteneur de l'agent (lisible par `env`, recopiable dans un patch) / **injectée par un proxy hors du conteneur** | **proxy** |
| F3 | Proxy | **proxy de CERVEAU** (bibliothèque standard, testé hors ligne, plafonds) / Envoy (Apache-2.0, sans comptage des jetons) / LiteLLM (lourd) | **proxy de CERVEAU** |
| F4 | Outils de l'agent | **Read, Edit, Write, Glob, Grep, Bash dans le conteneur**, aucun outil web, aucun sous-agent / sans Bash (l'agent ne peut pas lancer les tests) | **avec Bash**, le conteneur étant la frontière |
| F5 | Bornes par tâche | valeurs `A_DEFINIR` | 30 tours ; 2 $ par tâche, plafond tenu par le proxy ; 15 min ; 2 processeurs, 4 Go, 512 processus [hypothèse] |
| F6 | Modèle de l'agent | Sonnet 5.5 / Opus 5.5 / Haiku 5.5 | **Sonnet 5.5** (coût et qualité ; Haiku 5.5 à mesurer plus tard) |
| F7 | Classe d'action | `CALCUL` (inexact : la sortie d'un LLM n'est pas un calcul déterministe, R1) / **`EXECUTION_ISOLEE`** (B266), ouverte au domaine `code` en N0 sous contrôle du budget | **`EXECUTION_ISOLEE`**, avec revue `risk-gate-auditor` (agent à lancer avec ton accord) |
| F8 | Durée d'un appel d'outil (30 s, B272) | **délai propre au plugin déclaré dans le manifeste** (`code_agent` 900 s, `code_checks` 300 s, ce qui règle B272) / tâche de fond avec deux outils | **délai par plugin** ; le pack passe à 6 outils, au-dessus des 3 à 5 de R13 : ton accord est nécessaire |
| F9 | Autonomie livrée | **N0 : patch rendu, appliqué par toi** / N2 dès P3b | **N0** |
| F10 | Campagnes réelles | P3a seule / P3a et P3b / aucune | **P3a puis P3b**, chacune avec ton accord et des budgets fixés |

## 10. Commits atomiques (en anglais, `make ci` vert à chaque étape)

1. `docs: add the validated P3b plan`
2. `feat(policy): add the EXECUTION_ISOLEE action class for the code domain` + ADR-051 (F7)
3. `feat(mcp): let a plugin manifest declare its tool timeout` + ADR-052 (F8)
4. `feat(code): add the Anthropic API proxy with key injection and ceilings` + ADR-053 (F2, F3)
5. `feat(code_agent): run Claude Code in an isolated container and return a patch` + ADR-054 (F1, F4, F5)
6. `feat(code): add the code_agent evals`
7. `docs: update licences, threat model and backlog for code_agent`
8. `docs: add the code_agent report`

## 11. Exécution

Après `GO P3b` : vérification des `A_VERIFIER` du §1, commits 1 à 6, revues `security-reviewer`
(et `risk-gate-auditor` si F7 est retenue), commit 7, compte rendu, puis arrêt. Avant le premier
appel réel : tu construis les deux images (commandes dans `infra/agent/README.md`), tu fixes les
budgets et tu donnes ton accord pour le test payant.
