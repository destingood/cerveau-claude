# Backlog — CERVEAU

Tout ce qui sort du périmètre de la phase en cours (« Méthode de travail imposée »). Chaque élément indique
son origine et la phase visée ; « ? » signifie « à décider par Lucas ».

## Sécurité et gouvernance
| # | Élément | Origine | Phase |
|---|---|---|---|
| B1 | Chargeur : refuser `live.enabled: true` si `config/live.yaml` n'appartient pas aux Administrateurs (Windows) ou à root (VPS) | ADR-003, limite de l'ACL | 1 |
| B2 | Étendre l'ACL de `protect-live.ps1` à `governance/approvals/` | R3 | 1 |
| B3 | Décider s'il faut protéger `.claude/settings.json` et `.claude/hooks/` contre Claude | threat-model §5.8 | ? |
| B4 | Garde-fou shell : analyser les scripts lancés (`bash x.sh`, `pwsh -File`, `python x.py`) et les extractions d'archives | threat-model §5.1, §5.4 | 1 |
| B5 | Garde-fou shell : refuser `git stash`, `git pull`, `git checkout <branche>` quand `live.yaml` diffère entre les états | threat-model §5.3 | 1 |
| B6 | Garde-fou shell : refuser `docker compose config` sans `--quiet`, `docker inspect`, `docker compose exec … env` | threat-model §5.6 | 1 |
| B7 | Contrôle des outils MCP dans les hooks dès le premier serveur MCP (outils web de la phase 1) | threat-model §5.7 | 1 |
| B8 | Copie du journal d'audit hors machine et ancre externe du dernier hash | R11, section 13 | déploiement |
| B9 | Durcissement du VPS : SSH par clé, pare-feu, mises à jour automatiques, réseau privé (`A_DEFINIR`), sauvegardes chiffrées, restauration testée | section 13 | déploiement |

## Chaîne de livraison
| # | Élément | Origine | Phase |
|---|---|---|---|
| B10 | Épingler les actions GitHub par SHA ; Dependabot ou Renovate | T6 | 1 |
| B11 | Épingler les images Docker par digest | T6, ADR-004 | 1 |
| B12 | Version de promptfoo définie à un seul endroit (Makefile et CI) | phase 0 | 1 |
| B13 | Audit npm de promptfoo ; relevé automatique des licences transitives (ex. `pip-licenses`) | ADR-001, R14 | 1 |
| B14 | Vérifier le passage de la CI sur `ubuntu-latest` au premier push (non exécutée en local) | phase 0 | 1 |

## Infrastructure
| # | Élément | Origine | Phase |
|---|---|---|---|
| B15 | Remplacer MinIO (dépôt archivé depuis 2026-04) : ADR comparant les stockages objet compatibles S3 | ADR-004 | 1 |
| B16 | Évaluer Valkey à la place de Redis 7.4 (RSALv2 / SSPLv1) | licences | 1 |
| B17 | Fermer les inscriptions Langfuse après le premier compte ; initialisation sans interface (variables à vérifier dans la doc Langfuse) | ADR-004 | 1 |
| B18 | Mesurer la RAM et le temps de démarrage du profil `observability` | ADR-004 | 1 |
| B19 | Montée vers PostgreSQL 18 : ADR (nouvel emplacement des données dans l'image) | ADR-001 | ? |

## Fonctionnel
| # | Élément | Origine | Phase |
|---|---|---|---|
| B20 | Évaluer le Claude Agent SDK comme plugin du pack Code | ADR-002 | pack Code |
| B21 | Vérifier le dépôt OpenBB depuis https://docs.openbb.co (nom `openbq-org` suspect) | Annexe A, licences | 2 |
| B22 | `web_read` : cache de `robots.txt` entre deux lectures (durée de vie bornée, RFC 9309 §2.4 : 24 h au plus) | ADR-006, plugin `web_research` | 2 |
| B23 | `web_read` : encodages `br` et `deflate` (aujourd'hui refusés ; seul `gzip` est décodé, avec garde anti-bombe) | plugin `web_research` | ? |
| B24 | `web_read` : limiter les ports joignables (80 et 443 seulement ?) | plugin `web_research`, anti-SSRF | ? |
| B25 | `web_search` : confirmer dans la doc Brave le champ `age` et la longueur maximale de requête (400 caractères retenus, `A_VERIFIER`) | plugin `web_research` | 1 |
| B26 | Déclarer dans le manifeste C.1 le démarrage d'un plugin (module, variables d'environnement, outils payants) ; aujourd'hui constante `RUNTIMES` de `core/mcp/adapter.py` | ADR-007, annexe C.1 | 2 |
| B27 | Client MCP : transport HTTP (Streamable HTTP) pour un plugin distant ; seul stdio est couvert | ADR-007 | ? |
| B28 | Coût Brave : ne compter une recherche que si elle a atteint Brave (aujourd'hui comptée dès l'envoi au serveur, même sans clé : prudence) | ADR-005, `core/mcp` | 3 |
| B29 | Pseudonymisation : recognizers SIREN / SIRET (clé de Luhn) et plaques d'immatriculation | ADR-010, section 13 | 2 |
| B30 | Revenir à `presidio-anonymizer` quand sa borne `cryptography<49` sera levée | ADR-010 | 3 |
| B31 | URL fournies : remplacer l'URL par un jeton `<URL_n>` côté LLM (une URL peut contenir un nom) | ADR-010, R5 | 3 |
| B32 | Mesurer rappel et précision de la NER `fr_core_news_md` sur un corpus français annoté avant de passer au modèle `lg` | ADR-010, D10 | 2 |
