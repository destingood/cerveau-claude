# Licences des composants — CERVEAU

- Relevé du 2026-10-17 (phase 0), mis à jour le 2026-10-18 (phases 1 et 2), le 2026-10-20
  (phase 3) et le 2026-10-21 (phases 4 et 5) ; à jour à chaque nouvelle dépendance (R14)
- Phase 5 : licences lues dans les métadonnées des paquets installés (`License-Expression`) ;
  `pip-audit` sans vulnérabilité connue au 2026-10-21 ; bot Discord : licences lues dans
  `interfaces/discord_bot/package-lock.json`, `npm audit` sans vulnérabilité au 2026-10-21
- Phase 4 : aucune nouvelle dépendance directe ni transitive (plan de phase 4, section 13) ; seule
  la transitive certifi passe en 2026.10.19 (PYSEC-2026-4320), licence MPL-2.0 inchangée
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
| nautilus-trader | 1.231.0 | LGPL-3.0-or-later | adaptateur de backtest, seul import dans `core/finance/research/nautilus.py` (phase 3, ADR-024) |
| fastapi | 0.156.8 | MIT | API interne locale (phase 5, ADR-037) ; le plan citait 0.156.7, 0.156.8 est la dernière publiée au 2026-10-21 ; aucune nouvelle transitive : annotated-doc 0.0.5 (MIT), starlette 1.8.0 (BSD-3-Clause), opentelemetry-api 1.45.1 (Apache-2.0) et typing-inspection 0.4.4 (MIT) étaient déjà au verrou |
| uvicorn | 0.54.0 | BSD-3-Clause | serveur de l'API interne, lié à 127.0.0.1 (phase 5, ADR-037) ; déjà au verrou en transitive |
| jinja2 | 3.1.6 | BSD-3-Clause | gabarits du dashboard en lecture seule, échappement automatique (phase 5, ADR-041) ; déjà au verrou en transitive, comme MarkupSafe 3.0.4 (BSD-3-Clause, métadonnées du paquet) ; licence de Jinja2 vérifiée le 2026-10-21 (ADR-041 ; classifieur « BSD License » du paquet installé) |

## Recherche (groupe `research`, usage personnel uniquement)
| Composant | Version | Licence | Usage |
|---|---|---|---|
| vectorbt | 1.1.2 | Apache-2.0 + Commons Clause v1.0 (fichier `LICENSE` du paquet ; métadonnées PyPI vides) | criblage, seul import dans `core/finance/research/screening.py` (phase 3, ADR-025) |

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
| Node.js | v26 local, v24 LTS en CI | MIT | exécution de promptfoo et du bot Discord |

## Bot Discord (`interfaces/discord_bot/`, npm)
| Composant | Version | Licence | Usage |
|---|---|---|---|
| discord.js | 14.27.0 | Apache-2.0 | bot Discord mince : commandes, boutons, fenêtre du code (phase 5, ADR-037) ; seule dépendance directe, version exacte |

Transitives figées par `package-lock.json` (25 paquets avec discord.js, aucun copyleft) :
- Apache-2.0 : @discordjs/builders 1.14.1, @discordjs/collection 1.5.3 et 2.1.1 (deux copies),
  @discordjs/formatters 0.6.2, @discordjs/rest 2.6.3, @discordjs/util 1.2.0, @discordjs/ws 1.2.3 ;
- MIT : @sapphire/async-queue 1.5.5, @sapphire/shapeshift 4.0.0, @sapphire/snowflake 3.5.5,
  @types/node 26.6.5, @types/ws 8.18.2, @vladfrangu/async_event_emitter 2.4.7, discord-api-types
  0.38.57, fast-deep-equal 3.1.3, lodash 4.18.1, lodash.snakecase 4.1.1, magic-bytes.js 1.13.1,
  ts-mixer 6.0.4, undici 6.29.1, undici-types 8.9.0, ws 8.22.0 ;
- 0BSD : tslib 2.8.1.

Les dépendances transitives ne sont pas toutes listées ici ; `uv.lock` les fige, et leur relevé
automatique (par exemple `pip-licenses` en CI) est au backlog. Exception notable :
`cryptography` 50.0.2 (Apache-2.0 ou BSD-3-Clause), tirée par `pyjwt[crypto]` via `mcp`.
Transitives de la phase 2 (skfolio, arch, exchange-calendars) : cvxpy-base 1.9.3, clarabel 0.11.1,
qdldl 0.1.9.post1 et sparsediffpy 0.6.1 (Apache-2.0) ; scikit-learn 1.9.1, statsmodels 0.15.0,
joblib 1.6.0, threadpoolctl 3.7.0, patsy 1.0.3, cloudpickle 3.1.2 et toolz 1.2.0 (BSD) ; plotly
7.1.0, narwhals 2.27.1, formulaic 1.2.2, interface-meta 2.0.1, korean-lunar-calendar 0.4.0 et
pyluach 2.3.0 (MIT). Aucune n'est copyleft.
Transitives de la phase 3, lues dans les métadonnées installées le 2026-10-20 :
- NautilusTrader : msgspec 0.22.0 (BSD-3-Clause), pyarrow 26.0.0 (Apache-2.0), fsspec 2026.9.0
  (BSD-3-Clause) et **portion 2.6.3 (LGPL-3.0-or-later)** ; sous Linux et macOS seulement,
  uvloop 0.22.1 (MIT ou Apache-2.0).
- vectorbt : numba 0.68.0 (BSD-2-Clause), llvmlite 0.50.0 (BSD-2-Clause AND Apache-2.0 WITH
  LLVM-exception), matplotlib 3.11.2 (licence matplotlib, de type PSF, permissive), contourpy
  1.4.0, cycler 0.12.1, kiwisolver 1.5.1, dill 0.4.1, imageio 2.38.1, psutil 7.2.2 et
  ipython-pygments-lexers 1.1.1 (BSD) ; pillow 13.0.0 (MIT-CMU) ; fonttools 4.67.0, schedule
  1.2.2 et mypy-extensions 1.1.0 (MIT).
- Pile Jupyter tirée par vectorbt (`anywidget`, `ipywidgets`), jamais importée par CERVEAU :
  ipython 9.17.1, ipywidgets 8.1.9, comm 0.2.3, traitlets 5.16.1, matplotlib-inline 0.2.2,
  jupyterlab-widgets 3.0.17, widgetsnbextension 4.0.16, prompt-toolkit 3.0.53 et psygnal 0.16.1
  (BSD) ; anywidget 0.11.0, jedi 0.20.1, parso 0.8.7, executing 2.3.0, pure-eval 0.2.4,
  stack-data 0.6.3 et wcwidth 0.9.2 (MIT) ; asttokens 3.0.2 (Apache-2.0) ; sous Linux et macOS
  seulement, pexpect 4.9.0 et ptyprocess 0.7.0 (ISC).

Seul `portion` est copyleft (faible) parmi ces transitives.
**fsspec** : NautilusTrader 1.231.0 fixe `fsspec==2026.2.0`, touchée par PYSEC-2026-4217
(CVE-2026-104851, exécution de code par les gabarits de `ReferenceFileSystem`, corrigée en
2026.6.0). `pyproject.toml` la remplace par 2026.9.0 (`override-dependencies` de uv). Voir
l'ADR-024 ; cet écart à une contrainte amont est soumis à Lucas.
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
- **vectorbt (Apache-2.0 + Commons Clause v1.0)** : la clause interdit de « vendre » le
  logiciel, c'est-à-dire de fournir contre rémunération un produit ou un service dont la valeur
  vient substantiellement de vectorbt (conseil et hébergement compris). CERVEAU est un outil
  personnel (R16) : usage conforme. Isolé dans un groupe de dépendances (`research`) et un seul
  module, pour pouvoir le retirer sans toucher au reste (ADR-025). Tout usage commercial de
  CERVEAU exigerait de le retirer ou d'obtenir une licence de l'auteur.
- **NautilusTrader (LGPL-3.0-or-later)** : bibliothèque utilisée telle quelle, non modifiée, liée
  dynamiquement (import Python) ; CERVEAU n'est pas redistribué. Une version modifiée de
  NautilusTrader devrait être publiée sous LGPL.
- **portion (LGPL-3.0-or-later)** : dépendance de NautilusTrader, même régime : non modifiée, non
  redistribuée.
- **fr_core_news_md (LGPL-LR, licence LGPL pour ressources linguistiques)** : modèle de données
  chargé tel quel par spaCy, non modifié, non redistribué hors de `uv.lock` (téléchargé depuis
  les releases GitHub d'Explosion, empreinte figée). Une version modifiée du modèle devrait rester
  sous LGPL-LR.

## Points à trancher avant les phases suivantes (Annexe A)
Licences annoncées par l'Annexe A, à revérifier au moment de l'intégration (vectorbt et
NautilusTrader sont vérifiées et listées plus haut depuis la phase 3) :
- OpenBB : Apache-2.0 (openbb 5.0.0, openbb-mcp-server 2.0.1), mais l'extension
  `openbb-yfinance` est sous AGPL-3.0 ; OpenBB est reporté au backlog (ADR-013) ;
- Arize Phoenix : Elastic License 2.0, alternative non retenue (ADR-004) ;
- `openbq-org/OpenBB` : l'Annexe A indique « redirection vérifiée » depuis
  `OpenBB-finance/OpenBB`, mais le nom « openbq » ressemble à une faute de frappe ou à un dépôt
  homonyme. Avant tout clonage (phase 2), repartir de l'URL donnée par https://docs.openbb.co et
  vérifier la redirection (section 13).
