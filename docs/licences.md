# Licences des composants — CERVEAU

- Relevé du 2026-10-17 (phase 0), mis à jour le 2026-10-18 (phases 1 et 2), le 2026-10-20
  (phase 3), le 2026-10-21 (phases 4 et 5) et le 2026-10-22 (phase 6) ; à jour à chaque nouvelle
  dépendance (R14)
- Phase 6, pack Code (P3a) : aucune nouvelle dépendance Python ; git, l'image des contrôles et
  l'API de GitHub, appelés hors du verrou, sont relevés dans leur propre section
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
| defusedxml | 0.7.1 | PSF-2.0 (métadonnées `License: PSFL` du paquet installé) | lecture sûre des flux XML (Atom d'arXiv, RSS et Atom du plugin `feeds`), DTD refusées (phase 6, ADR-044) ; déjà au verrou en transitive (`py-serializable`), devenue directe et figée le 2026-10-22 |
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

## Sources de données externes (pack `recherche`, phase 6)
Conditions lues le 2026-10-21 ; seules des métadonnées et des résumés sont lus, aucun PDF (D12).

| Source | Accès | Licence des données | Conséquence dans CERVEAU |
|---|---|---|---|
| arXiv, API `export.arxiv.org` | sans clé ; une requête toutes les 3 s et une seule connexion, toutes machines confondues ([conditions d'utilisation](https://info.arxiv.org/help/api/tou.html)) | métadonnées sous CC0 1.0 ; texte intégral sous la licence de chaque article, non redistribuable par l'API | plugin `scholarly` : limiteur partagé `var/net/arxiv.*` ; résumé coupé à 2 000 caractères ; texte intégral jamais lu (ADR-044) |
| Crossref, REST API `api.crossref.org` | pool public sans clé et sans `mailto` (D11) ; en-têtes du 2026-10-21 : 1 requête par seconde, 1 requête simultanée ([accès](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/)) | métadonnées bibliographiques libres de restriction ; **résumés sous le droit d'auteur** de leurs éditeurs ou auteurs ([licence des métadonnées](https://www.crossref.org/documentation/retrieve-metadata/rest-api/rest-api-metadata-license-information/)) | plugin `scholarly` : limiteur partagé `var/net/crossref.*` ; résumé coupé à 1 000 caractères, montré mais jamais stocké ni mis en cache (ADR-044) |
| Flux RSS et Atom, liste blanche `flux` de `domain_packs/recherche/knowledge/sources.yaml` | aucun flux au 2026-10-22 (D18) ; chaque flux est ajouté par Lucas après lecture des CGU du site, qui tiennent lieu de robots.txt (R15) | licence notée flux par flux (`licence`) ; `A_VERIFIER` ou `A_DEFINIR` bloque la lecture (R7) | plugin `feeds` : titre, lien, date et résumé coupé à 1 000 caractères ; contenus complets ignorés, liens jamais suivis (ADR-044) |

## Outils et services du pack `code` (phase 6, P3a)
git et Docker sont appelés en sous-processus, l'API de GitHub par `httpx`, déjà au verrou (plan
P3, §7). Conditions lues le 2026-10-22.

| Composant | Licence ou conditions | Usage dans CERVEAU |
|---|---|---|
| git (2.56.0.windows.2 sur le poste) | GPL-2.0-only (`LICENSE.txt` de Git for Windows) | `code_repo` et la copie jetable des contrôles l'appellent en sous-processus, sans lien ni redistribution : aucune obligation pour CERVEAU |
| Image des contrôles, `python:3.12-slim` avec ruff et pytest (E4) | Python : PSF-2.0 ; ruff et pytest : MIT (tableau des dépendances) ; paquets Debian de l'image sous leurs licences propres (`A_VERIFIER` à la construction) | construite par Lucas, jamais par CERVEAU (`--pull never`), non redistribuée |
| API REST de GitHub (Actions), `api.github.com` | [Conditions d'utilisation de GitHub](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service), section H « API Terms », en vigueur depuis le 2026-04-27 : des requêtes abusives ou trop fréquentes peuvent suspendre l'accès à l'API ; aucun partage de jeton pour dépasser les limites | `code_ci` : lecture seule sans jeton (E6), une requête à la fois, pause respectée après un refus 403 ou 429 ; 60 requêtes par heure suffisent à un usage personnel |

## Agent de code `code_agent` (phase 6, P3b)
L'agent tourne dans une image construite par Lucas : CERVEAU n'ajoute aucune dépendance
Python (plan P3b, §6). Faits relevés le 2026-10-22 (ADR-053, ADR-054, `infra/agent/README.md`).

| Composant | Licence ou conditions | Usage dans CERVEAU |
|---|---|---|
| `claude-agent-sdk` 0.2.172 (publié sur PyPI le 2026-10-22) | MIT | installé dans l'image `cerveau-agent` seulement, figé par version et par empreinte (`requirements.txt`, `--require-hashes`) ; jamais dans `uv.lock` |
| CLI de Claude Code, embarqué dans `claude-agent-sdk` (2.1.257 au moins) | « © Anthropic PBC. All rights reserved », usage soumis aux conditions commerciales d'Anthropic (`LICENSE.md` de `anthropics/claude-code`) : **licence restrictive** | lancé par le runner dans le conteneur de l'agent ; reste dans l'image, jamais copié dans le dépôt ni redistribué |
| Image `cerveau-agent` : `python:3.12-slim`, ruff 0.17.1, pytest 9.1.1 | Python : PSF-2.0 ; ruff et pytest : MIT ; paquets Debian de l'image sous leurs licences propres (`A_VERIFIER` à la construction) | construite par Lucas, jamais par CERVEAU (`--pull never`), non redistribuée |
| Image `cerveau-llm-proxy` : `python:3.12-slim` et `core/code/llm_proxy.py` | PSF-2.0 ; bibliothèque standard seulement | construite par Lucas, non redistribuée ; seul conteneur qui reçoit la clé et sort vers l'API (ADR-053) |
| API Messages d'Anthropic, `api.anthropic.com` (`POST /v1/messages`) | conditions commerciales d'Anthropic, celles des appels de CERVEAU depuis la phase 1 ; texte non relu le 2026-10-22 (`A_VERIFIER`) | appelée par le proxy de la tâche avec la clé de Lucas : `claude-sonnet-5-5` (F6), 2 $ au plus par tâche (F5) ; le contenu des requêtes part chez Anthropic, comme pour toute utilisation de Claude |

## Sources du pack `cyber` (phase 6, P4)
Aucune nouvelle dépendance : `httpx` et Pydantic lisent les API et le STIX en JSON, sans `stix2`
ni `mitreattack-python` (plan P4, §7). Conditions lues le 2026-10-22 et le 2026-10-27 (plan P4,
§2 ; `config/data_sources.yaml`). Les mentions sont écrites par le code sous chaque réponse qui
utilise la source (`core/orchestrator/notices.py`, G9) : aucun modèle ne peut les omettre.

| Source | Licence ou conditions | Usage dans CERVEAU |
|---|---|---|
| API 2.0 du NVD (NIST), `services.nvd.nist.gov` | [Conditions du NVD](https://nvd.nist.gov/developers/terms-of-use) : mention « This product uses the NVD API but is not endorsed or certified by the NVD. » affichée en évidence ; clé personnelle, jamais partagée ; un contenu modifié ne s'attribue pas au NVD | `cyber_cve` (`cve_lookup`, `cve_watch`) : lecture seule, débit et cache de `config/data_sources.yaml` ; clé facultative lue dans `NVD_API_KEY`, jamais journalisée (R6) ; mention reproduite mot pour mot |
| Descriptions du programme CVE, reprises par le NVD | [Conditions du programme CVE](https://www.cve.org/Legal/TermsOfUse) : page rendue en JavaScript, non lue ; forme exacte de la mention `A_VERIFIER` (backlog) | descriptions citées en données (R5), avec un renvoi aux conditions du programme |
| Catalogue KEV de la CISA, flux JSON | CC0 1.0 (`licenses/kev/license.txt` de la CISA) : ni le logo, ni un aval de la CISA ou du DHS | `cyber_cve` : catalogue lu en entier (10 Mo au plus) ; les champs `notes` et `forensicTriage` ne sont pas gardés ; mention « aucun aval » |
| EPSS de FIRST, `api.first.org/data/v1/epss` | Scores publiés librement ; « Attribution is requested » dans une publication ou un produit ([FAQ](https://www.first.org/epss/faq)) ; forme exacte non publiée (`A_VERIFIER`) ; aucun débit publié trouvé (`A_VERIFIER`) | `cyber_cve` : score et centile de chaque CVE lue ; attribution à FIRST et à l'EPSS SIG |
| MITRE ATT&CK Enterprise v20.0, `mitre-attack/attack-stix-data` | Licence propre à MITRE, non exclusive et gratuite ([conditions](https://attack.mitre.org/resources/legal-and-branding/terms-of-use/), `LICENSE.txt` du dépôt) : toute copie reproduit « © 2026 The MITRE Corporation. This work is reproduced and distributed with the permission of The MITRE Corporation. » et la licence ; ATT&CK est une marque déposée | bundle de 55 Mo téléchargé par Lucas seul (`cerveau cyber attack-fetch`, commit figé, SHA-256 consigné), index local sous `var/`, jamais dans git ; mention dans l'index, dans chaque résultat d'`attack_lookup` et sous la réponse |
| OWASP Top 10 for LLM Applications 2025 (LLM01 à LLM10), `genai.owasp.org` | CC BY-SA 4.0, « unless otherwise specified » : citation avec lien et mention ; une adaptation devrait garder la même licence | pages lues à la demande par `web_read` (`domain_packs/cyber/knowledge/sources.yaml`) ; aucun contenu adapté n'est stocké ; mention CC BY-SA sous la réponse |
| Guides de l'ANSSI, de la CISA et du NIST CSRC | ANSSI : Licence Ouverte 2.0 d'Etalab (source secondaire, `A_VERIFIER` guide par guide) ; CISA et NIST : non vérifiées | non utilisés en P4 : ajoutés aux guides une fois leur licence vérifiée (backlog) ; la plupart sont des PDF, que `web_read` ne lit pas |

## Sources du pack `juridique_fr` (phase 6, P5)
Aucune nouvelle dépendance : `httpx` et Pydantic lisent l'API Légifrance ; `pylegifrance` (MIT)
n'a servi qu'à lire la spécification et n'est pas ajouté (plan P5, §8). Conditions lues le
2026-10-27 (`config/data_sources.yaml`, `domain_packs/juridique_fr/knowledge/sources.yaml`). Les
mentions et l'avertissement « pas un conseil juridique » sont écrits par le code sous chaque
réponse qui utilise la source (`core/orchestrator/notices.py`, H7) : aucun modèle ne peut les
omettre.

| Source | Licence ou conditions | Usage dans CERVEAU |
|---|---|---|
| API Légifrance de la DILA, par PISTE | Licence Ouverte 2.0 (etalab-2.0) : citer « Légifrance (DILA) » et la date de dernière mise à jour, sans laisser croire à un aval officiel ; seules les publications du Journal officiel font foi (non-opposabilité) ; CGU de l'API Légifrance V1.1 du 04/08/2020 : jeton OAuth à chaque requête, API en bêta, clés réinitialisées et DILA prévenue en cas de compromission. Version des CGU en vigueur sur PISTE, durée de vie du jeton et quotas `A_VERIFIER` (lisibles seulement dans PISTE) | `legifrance` (`legi_search`, `legi_article`, ADR-059) : lecture seule, 1 requête par seconde (H10), cache sous `var/juridique/` (H9) ; identifiants `PISTE_CLIENT_ID` et `PISTE_CLIENT_SECRET` lus dans l'environnement de Lucas, jamais journalisés (R6) ; environnement PISTE `A_DEFINIR` ; mention datée par article (version applicable, jour de lecture) |
| `legifrance.gouv.fr` (pages) | Licence Ouverte 2.0 (etalab-2.0), même mention | pages lues à la demande par `web_read` (liste fermée, ADR-058) ; jamais stockées |
| `service-public.gouv.fr`, dont `entreprendre.service-public.gouv.fr` | Licence Ouverte 2.0 (etalab-2.0) : « Service Public / DILA » et date de mise à jour de la fiche ; logos et marques exclus de la licence | fiches lues à la demande par `web_read` ; mention avec la date lue sur la fiche ; aucun logo repris |
| `impots.gouv.fr` | Licence Ouverte 2.0 : source et date de publication ; pour le BOFiP, référence et date de la publication citée | pages lues à la demande ; les PDF ne sont pas lus (backlog) |
| `cnil.fr` | CC BY-ND 4.0 FR : source, lien et date, sans modification du contenu | pages citées, jamais adaptées ni stockées |
| `conseil-etat.fr` | Réutilisation libre sans altération, avec la source et la date | pages citées, jamais adaptées ni stockées ; la jurisprudence (Judilibre, décisions administratives) reste au backlog (H2) |

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
- **CLI de Claude Code (« All rights reserved », conditions commerciales d'Anthropic)** :
  embarqué dans `claude-agent-sdk` (MIT), il n'existe que dans l'image `cerveau-agent`,
  construite par Lucas et jamais redistribuée ; aucun de ses fichiers n'entre dans le dépôt
  ni dans `uv.lock`. Retirer `code_agent` du pack suffit à ne plus l'utiliser (ADR-054).
  Redistribuer l'image ou servir des tiers (R16) exigerait de relire ces conditions.
- **vectorbt (Apache-2.0 + Commons Clause v1.0)** : la clause interdit de « vendre » le
  logiciel, c'est-à-dire de fournir contre rémunération un produit ou un service dont la valeur
  vient substantiellement de vectorbt (conseil et hébergement compris). CERVEAU est un outil
  personnel (R16) : usage conforme. Isolé dans un groupe de dépendances (`research`) et un seul
  module, pour pouvoir le retirer sans toucher au reste (ADR-025). Tout usage commercial de
  CERVEAU exigerait de le retirer ou d'obtenir une licence de l'auteur.
- **NautilusTrader (LGPL-3.0-or-later)** : bibliothèque utilisée telle quelle, non modifiée, liée
  dynamiquement (import Python). Le code source de CERVEAU est publié (section suivante), mais
  aucune copie de NautilusTrader n'y figure : `uv.lock` ne fait que la référencer. Une version
  modifiée de NautilusTrader devrait être publiée sous LGPL.
- **portion (LGPL-3.0-or-later)** : dépendance de NautilusTrader, même régime : non modifiée,
  référencée par `uv.lock`, jamais copiée dans le dépôt.
- **fr_core_news_md (LGPL-LR, licence LGPL pour ressources linguistiques)** : modèle de données
  chargé tel quel par spaCy, non modifié, non redistribué hors de `uv.lock` (téléchargé depuis
  les releases GitHub d'Explosion, empreinte figée). Une version modifiée du modèle devrait rester
  sous LGPL-LR.

## Publication du code de CERVEAU
- **Depuis le 2026-10-28**, le code source et son historique sont publiés dans le dépôt GitHub
  **public** `destingood/cerveau-claude`, dossier `plateforme/` (PR 8, décision de Lucas). Le
  dépôt local garde la référence ; chaque phase y est reportée par une PR que Lucas fusionne.
- **Ce qui est publié** : le code, la configuration (valeurs sensibles en `A_DEFINIR`, R7), les
  ADR, le modèle de menaces, les évals et des données de test fictives. Aucun secret (gitleaks
  sur tout l'historique, R6), ni `var/`, ni image Docker, ni copie d'une dépendance : les
  bibliothèques ne sont que référencées par `uv.lock` et `package-lock.json`.
- **Licence de CERVEAU** : aucune n'est déclarée, donc tous droits réservés à Lucas par défaut ;
  les conditions de GitHub permettent seulement de voir et de copier le dépôt sur GitHub
  (`A_VERIFIER` : section D.5 des GitHub Terms of Service). Choisir une licence est une
  décision de Lucas (`A_DEFINIR`, backlog).
- **Conséquences** : ce qui précède reste valable tant que CERVEAU n'est ni vendu ni servi à des
  tiers (R16, vectorbt) et que les images restent locales (CLI de Claude Code). Le modèle de
  menaces public aide un attaquant à connaître les défenses ; elles ne reposent pas sur leur
  secret (clés hors dépôt, contrôles déterministes).

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
