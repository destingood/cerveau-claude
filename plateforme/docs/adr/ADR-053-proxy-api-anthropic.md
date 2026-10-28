# ADR-053 — Proxy de l'API d'Anthropic pour l'agent de code

- Statut : **proposé** (F2 et F3 du complément de plan P3b, validés par Lucas le 22/10/2026)
- Date : 2026-10-22
- Phase : 6 (P3b)

## Contexte
L'agent de code (`code_agent`, ADR-054) fait tourner Claude Code dans un conteneur sans Internet.
Il lui faut l'API d'Anthropic, donc une clé (R6) et un plafond de dépense (F5 : 2 $ par tâche).
Faits vérifiés le 22/10/2026 :
- code.claude.com/docs/en/agent-sdk/secure-deployment : la clé doit rester hors de la frontière
  de l'agent ; avec `ANTHROPIC_BASE_URL`, un proxy reçoit les requêtes en clair et peut ajouter la
  clé ; avec `HTTPS_PROXY`, il ne voit qu'un tunnel chiffré ;
- code.claude.com/docs/en/agent-sdk/python : `max_budget_usd` est une estimation côté client, qui
  peut être dépassée ; code.claude.com/docs/en/env-vars : la clé part dans `X-Api-Key` ;
- platform.claude.com (Messages, streaming, mise en cache, tarifs) : flux SSE, usage dans
  `message_start` puis compteurs cumulés dans `message_delta` ; écritures de cache réparties en
  5 min et 1 h ; `server_tool_use`, `speed` (« fast » plus cher), `inference_geo` (« us » à
  1,1 ×) et `service_tier` changent le prix ; une source `url` ou `file`, un outil serveur,
  `container` ou `mcp_servers` font chercher ou exécuter quelque chose par l'API.

## Options
1. **Clé dans le conteneur de l'agent** : rien à écrire, mais la clé est lisible par `env`,
   recopiable dans un patch ou une requête, et aucun plafond ne tient hors du client.
2. **Envoy** (Apache-2.0) : injecte la clé et filtre les chemins, mais ne lit ni modèle, ni corps,
   ni jetons : pas de plafond de coût ; configuration lourde à relire.
3. **LiteLLM** : comptage des coûts, mais beaucoup de dépendances et une large surface pour un seul
   chemin ; licence non revue.
4. **Proxy de CERVEAU** (`core/code/llm_proxy.py`, bibliothèque standard seulement) : petit,
   testé hors ligne à 100 %, prix tirés de `config/pricing.yaml`.

## Décision
Option 4, un conteneur `cerveau-llm-proxy` par tâche (`infra/agent/llm-proxy.Dockerfile`).
- Réseau : l'agent le joint en HTTP sur un réseau Docker interne ; seul le proxy sort, en TLS
  vérifié, vers `api.anthropic.com:443`.
- Requêtes : `POST /v1/messages` seul (requête vide ou `beta=true`) ; modèle de la liste ; champs
  et valeurs listés (`speed` standard, `inference_geo` global) ; blocs `text`, `image`, `document`,
  `tool_use`, `tool_result`, réflexion ; sources `base64`, `text`, `content` ; outils `custom`
  seulement. Refusés : sources `url` et `file`, outils serveur, `container`, `mcp_servers`,
  `context_management`. L'API ne cherche et n'exécute donc rien pour l'agent.
- En-têtes : `content-type` JSON exigé ; `anthropic-version` et `anthropic-beta` vérifiés puis
  transmis ; tous les autres (clé de l'agent, `authorization`, cookies) retirés ; la vraie clé,
  lue dans l'environnement du proxy, est ajoutée. Réponse : 4 en-têtes transmis.
- Bornes : taille du corps (`Content-Length` exigé, pas de `chunked`), délai amont, 60 s par
  client, une requête à la fois.
- Coût : jetons lus dans la réponse (flux ou JSON), prix en `Decimal` comme
  `core/models/costs.py` (égalité vérifiée par Hypothesis), palier selon les jetons du prompt,
  arrondi au millionième supérieur. Un flux coupé compte `max_tokens` en sortie ; une écriture de
  cache sans répartition, le tarif 1 h. Prudence : coût inconnu (200 sans usage, prix hors liste,
  `iterations`, outil serveur, envoi sans réponse) → toute requête suivante est refusée (R7).
- Plafonds de la tâche en USD et en requêtes : atteints, le proxy refuse la suite.
- État : comptes seuls (requêtes, jetons, USD, raison d'arrêt), écrits de façon atomique ; ni
  contenu, ni clé. Une erreur interne tient en une ligne, sans détail.
- Image : le seul fichier du proxy, `python -I -B`, utilisateur 65534 ; condensé de
  `python:3.12-slim` `A_DEFINIR` (Lucas).

## Conséquences
- Le plafond ne dépend plus du client ; il est dépassé d'une requête au plus (verrou). `code_agent`
  choisit `max_tokens` et le plafond en conséquence.
- Recherche web, compaction côté serveur, mode rapide, inférence US et Files API sont indisponibles
  pour l'agent. Si le CLI en envoie par défaut, la tâche échoue au refus : à constater au premier
  test réel. Une hypothèse : une réponse d'erreur (statut ≠ 200) n'est pas facturée.
- `A_VERIFIER` au premier test réel (B286) : requêtes du CLI derrière `ANTHROPIC_BASE_URL`
  (champs, `?beta=true`, `count_tokens`, `context_management`, `Content-Length` ou `chunked`),
  modèle des tâches annexes du CLI (refusé s'il n'est pas listé), clé factice acceptée.
- Un nouveau champ d'usage ou de prix de l'API rend le coût inconnu : le proxy s'arrête (échec
  sûr) ; il se relit à chaque nouveau modèle ou version d'API.
- Le contenu des requêtes part chez Anthropic, comme pour toute utilisation de Claude ; la clé
  n'entre jamais dans le conteneur de l'agent.
- Réversible : le proxy est un fichier isolé ; le remplacer ne touche que `code_agent`.
