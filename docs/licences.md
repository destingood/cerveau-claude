# Licences des composants — CERVEAU

- Relevé du 2026-10-17 (phase 0), mis à jour le 2026-10-18 (phases 1 et 2) ; à jour à chaque
  nouvelle dépendance (R14)
- Phases 1 et 2 : licences lues dans les métadonnées des paquets installés (`*.dist-info/METADATA`)
  et sur PyPI ; phase 2 : chaque version retenue a au moins 7 jours au 2026-10-18
- Sources : métadonnées PyPI et npm, fichiers `LICENSE` des dépôts, pages Docker Hub

## Dépendances Python directes (`pyproject.toml`)
| Composant | Version | Licence | Usage |
|---|---|---|---|
| pydantic | 2.14.1 | MIT | schémas de configuration |
| jsonschema | 4.26.0 | MIT | validation des manifestes (Annexe C.1) |
| PyYAML | 6.0.3 | MIT | lecture des `config/*.yaml` |
| Typer | 0.27.3 | MIT | CLI `cerveau` |
| langgraph | 1.2.16 | MIT | graphe de l'orchestrateur (phase 1) |
| langchain-core | 1.6.12 | MIT | messages, outils, modèles factices des tests |
| langchain-anthropic | 1.7.6 | MIT | appels aux modèles Claude |
| mcp | 2.3.0 | MIT | serveur et client MCP (stdio) |
| httpx | 0.28.1 | BSD-3-Clause | requêtes HTTP du plugin `web_research` |
| trafilatura | 2.3.1 | Apache-2.0 | extraction du texte des pages web |
| presidio-analyzer | 2.2.364 | MIT | détection des données personnelles |
| spaCy | 3.8.16 | MIT | moteur NLP de Presidio |
| fr_core_news_md | 3.8.0 | LGPL-LR | modèle spaCy français (personnes, lieux) |
| langfuse | 5.0.2 | MIT | traces optionnelles (serveur ≥ 4.59.0) |
| tldextract | 5.4.0 | BSD-3-Clause | domaine enregistrable (liste PSL embarquée, hors ligne) |
| numpy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | calcul matriciel (phase 2) ; 2.5.x exclu : `presidio-analyzer` 2.2.364 impose `numpy<2.5` |
| pandas | 3.0.6 | BSD-3-Clause | séries de cours et de positions (phase 2) |
| scipy | 1.18.1 | BSD-3-Clause | lois, optimisation, XIRR (phase 2) |
| arch | 8.0.0 | NCSA (University of Illinois/NCSA, permissive) | GARCH (phase 2) |
| skfolio | 1.8.1 | BSD-3-Clause | optimisation, shrinkage, recoupement des mesures (phase 2) ; 1.8.2 à 1.9.4 ont moins de 7 jours |
| exchange-calendars | 4.13.2 | Apache-2.0 | calendriers des places (phase 2) |

## Outils de développement (groupe `dev`, non distribués)
| Composant | Version | Licence | Usage |
|---|---|---|---|
| pytest / pytest-cov | 9.1.1 / 7.1.0 | MIT | tests |
| pytest-socket | 0.8.1 | MIT | blocage du réseau dans les tests |
| Hypothesis | 6.170.1 | MPL-2.0 | tests par propriétés |
| ruff | 0.17.1 | MIT | lint et formatage |
| pip-audit | 2.10.1 | Apache-2.0 | audit des vulnérabilités |
| pre-commit | 4.7.0 | MIT | hooks git |
| promptfoo (npx) | 0.124.1 | MIT | évals |
| gitleaks | 8.30.1 | MIT | détection de secrets |
| uv | 0.13.1 | Apache-2.0 ou MIT (au choix, selon son README) | Python et dépendances |
| GNU make | 4.4.1 | GPL-3.0 | outil local seulement, rien n'est lié |
| Node.js | v26 local, v24 LTS en CI | MIT | exécution de promptfoo |

Les dépendances transitives ne sont pas toutes listées ici ; `uv.lock` les fige, et leur relevé
automatique (par exemple `pip-licenses` en CI) est au backlog. Exception notable :
`cryptography` 50.0.2 (Apache-2.0 ou BSD-3-Clause), tirée par `pyjwt[crypto]` via `mcp`.
Transitives de la phase 2 (skfolio, arch, exchange-calendars) : cvxpy-base 1.9.3, clarabel 0.11.1,
qdldl 0.1.9.post1 et sparsediffpy 0.6.1 (Apache-2.0) ; scikit-learn 1.9.1, statsmodels 0.15.0,
joblib 1.6.0, threadpoolctl 3.7.0, patsy 1.0.3, cloudpickle 3.1.2 et toolz 1.2.0 (BSD) ; plotly
7.1.0, narwhals 2.27.1, formulaic 1.2.2, interface-meta 2.0.1, korean-lunar-calendar 0.4.0 et
pyluach 2.3.0 (MIT). Aucune n'est copyleft.
`presidio-anonymizer` 2.2.364 n'est **pas** retenu : il impose `cryptography<49`, version touchée
par PYSEC-2026-3554 et PYSEC-2026-3552 (correctifs en 49.0.0 et 50.0.0). La pseudonymisation est
faite dans `core/guardrails/` à partir des résultats de `presidio-analyzer` (ADR-010).

## Services Docker (`infra/docker-compose.yml`)
| Composant | Image | Licence | Usage |
|---|---|---|---|
| PostgreSQL + pgvector | `pgvector/pgvector:0.8.7-pg17-trixie` | PostgreSQL License | base `cerveau` et base `langfuse` |
| Langfuse web et worker | `docker.langfuse.com/langfuse/*:4.63.0` (D12) | MIT, sauf dossiers `ee/` (commercial) | observabilité |
| ClickHouse | `clickhouse/clickhouse-server:25.12` | Apache-2.0 | stockage des traces Langfuse |
| MinIO | `cgr.dev/chainguard/minio` | AGPL-3.0 (dépôt d'images Chainguard : Apache-2.0) | stockage objet Langfuse |
| Redis | `redis:7` (7.4.11) | RSALv2 / SSPLv1 | file d'attente Langfuse |
| Docker Desktop | — | gratuit pour un usage personnel | exécution locale |

## Licences restrictives ou à surveiller
- **Redis 7.4 (RSALv2 / SSPLv1, depuis le 2024-03-20)** : interdit surtout de revendre Redis comme
  service. Usage interne non modifié : sans effet. Alternative libre à évaluer : Valkey (backlog).
- **MinIO (AGPL-3.0)** : utilisé tel quel comme service local, non modifié, non exposé à des
  tiers : pas d'obligation de publication. Dépôt amont archivé depuis 2026-04 : remplacement au
  backlog (ADR à venir).
- **Langfuse `ee/`** : sous licence commerciale ; aucune fonction `ee` n'est activée (aucune clé de
  licence configurée).
- **Hypothesis (MPL-2.0)** : copyleft faible par fichier, outil de test non modifié ni distribué.
- **GNU make (GPL-3.0)** : outil de construction, sans lien avec le code de CERVEAU.
- **fr_core_news_md (LGPL-LR, licence LGPL pour ressources linguistiques)** : modèle de données
  chargé tel quel par spaCy, non modifié, non redistribué hors de `uv.lock` (téléchargé depuis
  les releases GitHub d'Explosion, empreinte figée). Une version modifiée du modèle devrait rester
  sous LGPL-LR.

## Points à trancher avant les phases suivantes (Annexe A)
Licences annoncées par l'Annexe A, à revérifier au moment de l'intégration :
- vectorbt : Apache-2.0 + Commons Clause, usage personnel uniquement (Annexe A, ligne 326) ;
- NautilusTrader : LGPL-3.0 (utilisé comme bibliothèque non modifiée, à confirmer) ;
- OpenBB : Apache-2.0 (openbb 5.0.0, openbb-mcp-server 2.0.1), mais l'extension
  `openbb-yfinance` est sous AGPL-3.0 ; OpenBB est reporté au backlog (ADR-013) ;
- Arize Phoenix : Elastic License 2.0, alternative non retenue (ADR-004) ;
- `openbq-org/OpenBB` : l'Annexe A indique « redirection vérifiée » depuis
  `OpenBB-finance/OpenBB`, mais le nom « openbq » ressemble à une faute de frappe ou à un dépôt
  homonyme. Avant tout clonage (phase 2), repartir de l'URL donnée par https://docs.openbb.co et
  vérifier la redirection (section 13).
