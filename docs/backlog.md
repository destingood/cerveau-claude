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
| B7 | ~~Contrôle des outils MCP dans les hooks dès le premier serveur MCP~~ : fait en phase 1 (`.claude/hooks/guard_mcp.py`, liste d'autorisation à relire par Lucas) | threat-model §5.7 | 1 |
| B37 | Garde-fou pour `WebFetch` et `WebSearch` (outils intégrés, hors matchers) : une URL construite peut faire sortir des données | threat-model §5.7 | ? |
| B38 | Détection de consignes : couvrir les formulations polies (« note à l'IA »), les autres verbes d'ajout de lien (« lis », « écris », « recopie… dans l'URL »), le leet speak et les lettres espacées | `evals/redteam`, faille 1, R5 | 2 |
| B39 | Texte caché : retirer avant extraction le texte en police nulle, blanc sur blanc, `hidden` ou hors écran, que trafilatura garde ; idem pour `display:none`, `visibility:hidden`, `aria-hidden` et `noscript` dans son repli des pages courtes | `evals/redteam`, faille 2, R5 | 2 |
| B40 | Liens HTML (`<a>`, `<img>`, `<iframe>`…) vers un hôte tiers : les compter dans `links_removed` et les signaler à Lucas, comme les liens Markdown | `evals/redteam`, faille 3, R5 | 2 |
| B41 | Requête `web_search` : contrôler ce qu'un planificateur manipulé peut y glisser (longueur, recouvrement avec la conversation, motifs d'exfiltration) | `evals/redteam`, faille 4, R5 | 2 |
| B42 | Classifieur d'injection dédié (option 3 de l'ADR-008), seulement si les mesures réelles le justifient | ADR-008, R13 | ? |
| B43 | Pseudonymiser aussi le texte des pages lues avant le lecteur (données de tiers des pages publiques) ; aujourd'hui seuls la question et l'adresse finale le sont | section 13, R6 | 2 |
| B64 | Liste d'autorisation MCP (`.claude/hooks/guard_mcp.py`) : retirer `Claude_Browser__navigate` ou contrôler son URL (liste blanche de domaines, refus du loopback et des adresses privées) ; `navigate`, `read_page` et `get_page_text` donnent à Claude Code un GET vers n'importe quelle URL (fuite par l'URL, Langfuse local, contenu non fiable devant un agent qui a Bash et Edit) | revue de sécurité phase 1 (M3), B37, R5 | ? |
| B65 | ~~Vérifier en session réelle que Claude Code déclenche le hook MCP avec le matcher `^mcp__` (les tests appellent le script directement)~~ : fait en phase 2 (refus d'un outil MCP non listé par `guard_mcp.py` en session réelle ; plan de phase 2, §1) | revue de sécurité phase 1 (M3) | 2 |
| B66 | ~~`web_read` : ne pas recopier `Content-Type` ni `Content-Encoding` (contrôlés par la page) dans les erreurs, ou n'en garder que `[a-z0-9/+.-]{0,40}`~~ : fait en phase 2 (`guard.shown` : jeton court en minuscules, sinon « non standard » ; aussi pour le schéma d'une redirection) | `plugins/web_research/fetcher.py`, revue (F2), R5 | 2 |
| B67 | ~~`web_read` : message d'erreur générique sans l'hôte de l'URL (il part en clair au modèle et à Langfuse, ce qui contourne la pseudonymisation de l'URL)~~ : fait en phase 2 (messages de `pin` et de `robots.txt` sans l'hôte ni l'adresse résolue) | `plugins/web_research/guard.py`, revue (F3), R6 | 2 |
| B68 | ~~URL des résultats de recherche montrées au planificateur : passer `injection_signals` sur l'URL, ou n'afficher que le domaine et le rang (le chemin peut porter une consigne)~~ : fait en phase 2 (`injection_signals` sur l'URL décodée, telle quelle et séparateurs en espaces : l'adresse est masquée, non lisible, comptée dans `masked_urls` et signalée) | `core/orchestrator/planner.py`, revue (F5), R5 | 2 |
| B69 | Lecteur : le texte `affirmation` n'est pas ancré dans la page, seule l'heuristique le filtre ; exiger une citation présente dans la page | `core/orchestrator/reader.py`, revue (info 2), R5 | 2 |
| B70 | ~~Kill switch : le vérifier avant chaque appel de modèle (`Run.invoke`) ; aujourd'hui seul `policy_node` refuse, à la fin de la requête~~ : fait en phase 2 (`Run.invoke` lève `KillSwitchEngaged`, `Orchestrator.ask` répond par un refus et journalise la décision avec `halted: kill_switch`) | `core/orchestrator/runtime.py`, revue (F6), R4 | 2 |
| B95 | Données du portefeuille vues par le modèle : les sorties des outils Finance (positions, montants, plus-values) arrivent au planificateur en clair ; décider d'une vue réduite ou pseudonymisée (identifiants de titres, montants arrondis) sans casser la traçabilité R1 | `core/orchestrator/planner.py` (`_compute`), R6 | ? |
| B101 | Détection de consignes : homoglyphes (« ignоre the previous rules » écrit avec un о cyrillique passe) ; ramener le texte à son squelette de confusables (Unicode TS #39) avant les motifs et ajouter les cas au red team | `core/guardrails/injection.py`, revue de sécurité phase 2 (F1), R5 | 3 |
| B102 | Nom du fichier importé jamais validé : il atteint le planificateur dans le texte d'une erreur d'outil, que le détecteur ne lit pas, et la colonne `origine` de l'export des plus-values (neutralisée pour le tableur en phase 2) ; le passer par `plain_text` avec une liste de caractères permis et lire les erreurs d'outil avec `injection_signals` | `core/finance/portfolio.py`, `core/orchestrator/planner.py`, revue phase 2 (F2), R5 | 3 |
| B103 | `--store` et `--journal` des commandes `cerveau finance` acceptent tout chemin et créent les dossiers parents : les limiter à `var/` sauf option explicite | `core/finance/store.py`, `interfaces/cli/finance.py`, revue phase 2 (F4) | 3 |
| B104 | Refus d'une recherche web qui reprend les données du portefeuille (M2) : un identifiant collé à un nombre (« FICT-GLOBEX-21-59 »), un montant arrondi, écrit en lettres ou de moins de 4 chiffres significatifs passent ; normaliser les séparateurs et envisager de fermer le web dans une requête Finance qui n'en a pas besoin | `core/orchestrator/planner.py` (`repeats_tool_data`), revue phase 2 (M2), R6 | 3 |
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
| B71 | promptfoo : passer l'environnement en liste blanche (PATH, SYSTEMROOT, TEMP, APPDATA, `CERVEAU_*`, `PROMPTFOO_*`, et les deux clés en mode réel seulement) et installer promptfoo par `package.json`, `package-lock.json` et `npm ci` (`npx -y` ne fige que le paquet de tête) | `interfaces/cli/evaluate.py`, revue (M2), B13, R6 | 2 |

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
| B21 | ~~Vérifier le dépôt OpenBB depuis https://docs.openbb.co (nom `openbq-org` suspect)~~ : fait en phase 2 (redirection GitHub de `OpenBB-finance/OpenBB`, licence Apache-2.0 ; plan de phase 2, §1) | Annexe A, licences | 2 |
| B22 | ~~`web_read` : cache de `robots.txt` entre deux lectures (durée de vie bornée, RFC 9309 §2.4 : 24 h au plus)~~ : fait en phase 2 (cache par origine sur le `WebReader`, 1 h, 256 origines ; seules les réponses du site sont gardées, un 429, un 5xx ou une erreur réseau sont redemandés ; le serveur MCP vit une requête, donc le cache aussi) | ADR-006, plugin `web_research` | 2 |
| B23 | `web_read` : encodages `br` et `deflate` (aujourd'hui refusés ; seul `gzip` est décodé, avec garde anti-bombe) | plugin `web_research` | ? |
| B24 | ~~`web_read` : limiter les ports joignables à 80 et 443 ; un autre port d'une adresse publique peut atteindre l'administration de la box par sa propre IP publique (NAT en boucle)~~ : fait en phase 2 (`pin` refuse tout autre port à chaque saut, après les contrôles d'adresse) | plugin `web_research`, anti-SSRF, revue de sécurité phase 1 (F1) | 2 |
| B25 | `web_search` : confirmer dans la doc Brave le champ `age` et la longueur maximale de requête (400 caractères retenus, `A_VERIFIER`) | plugin `web_research` | 1 |
| B26 | ~~Déclarer dans le manifeste C.1 le démarrage d'un plugin (module, variables d'environnement, outils payants)~~ : fait en phase 2 (bloc `runtime` du manifeste, validé par le registre, ADR-015) | ADR-007, annexe C.1 | 2 |
| B27 | Client MCP : transport HTTP (Streamable HTTP) pour un plugin distant ; seul stdio est couvert | ADR-007 | ? |
| B28 | Coût Brave : ne compter une recherche que si elle a atteint Brave (aujourd'hui comptée dès l'envoi au serveur, même sans clé : prudence) | ADR-005, `core/mcp` | 3 |
| B29 | Pseudonymisation : recognizers SIREN / SIRET (clé de Luhn) et plaques d'immatriculation | ADR-010, section 13 | 2 |
| B30 | Revenir à `presidio-anonymizer` quand sa borne `cryptography<49` sera levée | ADR-010 | 3 |
| B31 | URL fournies : remplacer l'URL par un jeton `<URL_n>` côté LLM (une URL peut contenir un nom) | ADR-010, R5 | 3 |
| B32 | Mesurer rappel et précision de la NER `fr_core_news_md` sur un corpus français annoté avant de passer au modèle `lg` | ADR-010, D10 | 2 |
| B33 | ~~Vérification des chiffres : contrôler aussi les dates, les heures et les petits entiers nus (≤ 10), ignorés aujourd'hui~~ : fait en phase 2 (`core/verification/dates.py`, `trace.py` ; le prompt écrit en lettres les dénombrements propres à la réponse) | `core/verification`, R1 | 2 |
| B34 | Vérification des chiffres : lire les nombres écrits en lettres (« douze pour cent ») ; le prompt système impose les chiffres en attendant | `core/verification`, R1 | 3 |
| B35 | ~~Vérification des chiffres : comparer le signe (hausse / baisse) au lieu de le laisser au contrôle des affirmations~~ : fait en phase 2 (signe écrit ou mot de sens, B92 pour la limite restante) | `core/verification`, R1 | 2 |
| B36 | Liens : liste blanche par URL exacte plutôt que par domaine (un lien vers un domaine autorisé peut encore porter des données dans sa requête) ; retirer aussi les adresses e-mail nues. Fait en partie en phase 1 : un lien qui porte un pseudonyme doit être exactement une URL autorisée (revue, E1) | `core/verification`, R5 | 2 |
| B72 | ~~`web_read` : extraction trafilatura dans `asyncio.to_thread` avec un délai (elle est synchrone et hors du délai de 15 s)~~ : fait en phase 2 (extraction dans `asyncio.to_thread`, sous le même délai de 15 s ; un fil qui déborde ne s'arrête pas, il finit seul et son résultat est jeté) | `plugins/web_research/fetcher.py`, revue (F7) | 2 |
| B44 | Budgets : actions `downgrade_to_fast_or_local` et `stop_non_critical_tasks` de `on_exceeded` ; seul le refus existe (D9) | `core/budget/gate.py`, ADR-005 | ? |
| B45 | Grand livre des coûts : index au lieu de relire tout le journal d'audit à chaque contrôle | ADR-005 | si besoin |
| B46 | Alertes ntfy des seuils de budget (50, 80, 100 %) ; aujourd'hui CLI et journal | plan phase 1 §5 et §13 | ? |
| B47 | Tier local Ollama (`langchain-ollama`) ; modèle `A_DEFINIR` | plan phase 1 §5 et §13 | ? |
| B48 | Plugin CALCUL : les calculs simples du golden set restent sans outil déterministe (R1) en phase 1 | R1, R13 | 2 |
| B49 | Pseudonymisation : la NER masque des lieux et des noms publics de la question, ce qui appauvrit la requête de recherche ; décider s'il faut ré-identifier les arguments d'outil (aujourd'hui jamais) | ADR-010, D10 | ? |
| B50 | Pages rendues en JavaScript : outil web fetch d'Anthropic ou navigateur sans interface | ADR-006, plan phase 1 §13 | ? |
| B51 | Compteur de phrases de la synthèse : abréviations et nombres décimaux faussent le compte (« M. », « 3.5 ») | `core/orchestrator/planner.py` | 3 |
| B52 | `clean_title` : la coupe à `MAX_TITLE_CHARS` peut laisser une espace finale | `core/orchestrator/answer.py` | 3 |
| B53 | Optimisation fine du cache de prompt, une fois son gain mesuré (`A_VERIFIER`) | ADR-005, plan phase 1 §13 | ? |
| B54 | `cerveau status`, `cerveau kill` et `cerveau report` | plan phase 1 §13 | ? |
| B55 | Mode Comité | section 7, plan phase 1 §13 | 3 |
| B56 | Bot Discord et approbations | plan phase 1 §13 | 5 |
| B57 | Autres packs de domaine et RAG (`knowledge/sources.yaml` vide pour le pack Généraliste) | section 9, plan phase 1 §13 | ? |
| B58 | Mémoire (section 11) : la spécification ne la place dans aucune phase ; en phase 1 le nœud 8 journalise et la mémoire est désactivée | plan phase 1 §13 | ? |
| B85 | Contrôles de qualité des séries de change et de taux (calendrier TARGET de la BCE) ; en phase 2 ils ne portent que sur les cours | ADR-016, D12 | 3 |
| B86 | Reconnaître un grand mouvement vérifié comme réel (une annonce, une faillite) pour que le sous-score « opérations sur titres » ne reste pas à 0 sur toute la fenêtre | ADR-016 | 3 |
| B87 | Courbe des taux de la BCE (`yield_curve`) : Lucas lit ses conditions propres, plus restrictives, avant de la remettre dans `data_sources.yaml` (D22) | ADR-017 | 3 |
| B88 | Confirmer sur une vraie réponse de la BCE les colonnes `csvdata` (KEY, CURRENCY, CURRENCY_DENOM, TIME_PERIOD, OBS_VALUE) et le sens de TIME_PERIOD pour l'€STR (`A_VERIFIER`) | ADR-017 | 2 |
| B89 | Rapprocher les identifiants d'un courtier (ISIN, code interne) du référentiel par `map_source_id`, avec l'adaptateur de son export (D4) | ADR-012, ADR-017 | 2 |
| B90 | Plus-values : confirmer avec leur source les règles de l'article 150-0 D du CGI que l'export n'applique pas (PMP par compte ou tous comptes de même nature, change du jour d'achat pour le prix de revient, régime du PEA) ; `compliance.fiscal.regime_plus_values` reste `A_VERIFIER` | plan §7 F9, ADR-020 | ? |
| B91 | Plus-values : cessions nées d'une opération sur titres (fusion, échange, rachat) et gains de change sur les liquidités en devises, absents de l'export | plan §7 F9, ADR-020 | ? |
| B92 | Sens des nombres : « le TWR a baissé de 8,80 % » face à un chiffre positif est accepté, le mot de sens d'un texte pouvant décrire autre chose que le chiffre (un coût, un écart) ; seul le signe écrit (« -8,80 % ») contredit un chiffre d'outil. À lever par une lecture de la phrase ou par le contrôle des affirmations | `core/verification/numbers.py`, B35, R1 | 3 |
| B93 | Dates : aucune conversion de fuseau (une heure UTC d'un outil réécrite en heure de Paris n'est pas retrouvée) ; dates sans chiffres (« le premier mars ») non lues ; une durée « 2 h » est lue comme une heure et signalée si aucune source ne la donne | `core/verification/dates.py`, B33, R1 | 3 |
| B94 | Chiffres d'outil : seules les devises et le % sont comparés (« 3 options » est retrouvé dans « 3 séances ») ; le signe de « -€3 » (symbole entre le signe et le nombre) n'est pas lu | `core/verification`, R1 | 3 |
| B96 | Sortie d'outil trop longue (plus de 64 000 caractères en vue compacte) : le planificateur reçoit un refus et doit restreindre sa demande ; envisager une pagination ou un résumé déterministe par l'outil | `core/orchestrator/planner.py` (`MAX_VIEW_CHARS`) | 3 |
| B97 | Kill switch au milieu d'une requête : l'entrée `DECISION` reprend l'état reçu par le nœud interrompu, pas ce qu'il avait déjà produit (les appels d'outil restent journalisés un par un par l'adaptateur) | `core/orchestrator/graph.py` (`halted_state`), R4, R11 | 3 |
| B98 | Pack Finance : cinq plugins (six avec le web) ouverts côte à côte à chaque requête, un sous-processus chacun ; mesurer la latence de démarrage et, si besoin, n'ouvrir un plugin qu'à l'appel de son premier outil (schémas tirés du manifeste) | `core/orchestrator/runtime.py` (`open_tools`), `A_VERIFIER` | 3 |
| B99 | Détection de consignes : un ordre de bourse en clair (« achète 500 actions Acme », « vends toute la ligne », « sell all shares »), sans tournure d'instruction, n'est pas signalé et passe comme un fait cité ; ajouter un motif « ordre » (verbe d'achat ou de vente à l'impératif suivi d'une quantité ou d'une ligne) mesuré contre les faux positifs des pages d'actualité | `core/guardrails/injection.py`, `evals/redteam/README.md`, B38, R5 | 3 |
| B100 | Import CSV : un nom d'instrument ou un libellé sans tournure d'instruction qui cite un hôte ou une adresse (« positions publiées sur collecte.evil.example ») est accepté et atteint les sorties des outils ; seul le retrait des liens hors sources protège la réponse. Envisager de refuser à l'import tout hôte, adresse ou URL dans un nom, un secteur ou un libellé, mesuré contre les relevés réels de Lucas | `core/finance` (import), `evals/redteam/injection_finance/fichiers_importes.yaml`, B99, R5 | 3 |
| B105 | Fraîcheur d'une série : un score de qualité enregistré vaut à partir de sa date (`_quality`), donc la fraîcheur est jugée à la date du score et non à `as_of` ; la recalculer à `as_of` | `core/finance/views.py`, ADR-016, R10 | 3 |
| B106 | `performance_report` ne porte ni `quality_check` ni `data_quality` (D12), alors que `risk_report` et `rebalance_proposal` les portent ; ajouter le contrôle des titres détenus sur la période | `core/finance/performance_report.py`, revue quantitative phase 2 (6) | 3 |
| B107 | Commande `cerveau promotion check finance N1` : vérifier la règle D16 sur un rapport réel (identifiant du run, campagne, mode live, empreinte de config, score du golden set, 0 violation R1–R5) avant que Lucas signe | `config/autonomy.yaml`, D16, revue risk-gate phase 2 | 3 |
| B108 | Niveau N1 : la case `FINANCIERE` vaut `proposition`, que le moteur de politique refuse encore faute de composant qui rédige une intention structurée ; promouvoir la finance en N1 n'ouvre donc rien de plus tant que ce composant n'existe pas (le rééquilibrage s'affiche alors « proposition non exécutée ») | `core/policy/engine.py`, `core/finance/rebalance.py`, D16, revue risk-gate phase 2 | 3 |
| B109 | Variation de VaR : les expositions « après » intègrent la baisse des cours, comptée dans l'effet positions ; séparer trois effets : opérations (quantités), réévaluation (anciennes quantités aux nouveaux cours) et moments | `core/finance/risk.py`, `risk_report.py`, revue quantitative phase 2 (3) | 3 |
| B110 | `poids_actuel` du rééquilibrage est calculé sur la part investie et non sur le total (9,96 % contre 7,67 % dans `portfolio_snapshot`) : renommer l'identifiant, le décrire dans le schéma et ajouter le poids sur le total | `core/finance/rebalance.py`, revue quantitative phase 2 (4) | 3 |
| B111 | Identifiant `{iid}/cloture/{date}` identique quel que soit l'ajustement (brut, split, rendement total) : y mettre l'ajustement (`{iid}/cloture/{adjust}/{date}`) | `core/finance/views.py`, revue quantitative phase 2 (5), R1 | 3 |
| B112 | VaR paramétrique sur h séances : √h s'applique aussi à la moyenne (4,025 % contre 3,715 % en i.i.d. normal exact à 10 séances) ; appliquer √h à σ et h à μ, ou fixer μ = 0, par une ADR puisque le golden set fige la valeur actuelle (R9) | `core/finance/risk.py`, revue quantitative phase 2 (7) | 3 |
| B113 | Rééquilibrage : frais et glissement n'entrent ni dans l'objectif, ni dans les poids cibles, ni dans le « risque après » (rotation de 124 % en variance minimale) ; afficher un coût estimé depuis la rotation ou dire que la cible est brute de frais (R10) | `core/finance/rebalance.py`, revue quantitative phase 2 (8), D13 | 3 |
| B114 | Stress : la classe `etf` reçoit le choc actions entier, même pour un ETF obligataire ; ajouter la classe sous-jacente au référentiel | `core/finance/risk_report.py`, revue quantitative phase 2 (9) | 3 |
| B115 | Annualisation sur 252 séances alors que le calendrier TARGET en compte environ 254,6 : volatilité, Sharpe et Sortino sous-estimés d'environ 0,5 % ; le documenter ou annualiser sur le nombre observé | `core/finance/performance_report.py`, revue quantitative phase 2 (10) | ? |
| B116 | Ratio de split stocké en float : un regroupement 1 pour 3 donne 0,3333… et le rapprochement exact signale un écart ; le stocker en fraction ou en Decimal texte (migration de la base) | `core/finance/portfolio.py`, revue quantitative phase 2 (11) | 3 |
| B117 | Une ligne sans historique à `compare_to` fait échouer tout le rapport de risque ; mettre seulement `var_change` dans `unavailable` | `core/finance/risk_report.py`, revue quantitative phase 2 (12) | 3 |
| B120 | Base synthétique de la recherche (`var/finance/research/synthetique.db`) chargée une fois puis réutilisée : un jeu de données synthétique modifié n'y entre pas tant que Lucas ne supprime pas le fichier à la main ; y inscrire l'empreinte du jeu et refuser, ou recharger dans une base neuve, quand elle change | `interfaces/cli/strategy.py` (`synthetic_store`), `core/finance/fixtures.py`, ADR-026 | 4 |
| B121 | Un backtest du Copilote qui ne se rejoue plus (grille ou période de l'entrée modifiée, `params` journalisé tronqué au-delà de 2 048 caractères par l'adaptateur MCP) bloque `cerveau strategy protocol` pour de bon : prévoir un essai « non rejouable » compté dans N sans série, ou une reconnaissance manuelle de Lucas journalisée | `core/finance/research/copilot.py`, `core/mcp/adapter.py` (`_clip`), ADR-027 | 4 |
| B122 | NautilusTrader stocke la monnaie en virgule fixe et refuse un montant au-delà de `MONEY_MAX` (9,22 milliards) : un recoupement sur un portefeuille de cette taille échoue par une `ValueError` de la bibliothèque. Le test de propriété écarte ces marchés tirés ; prévoir un refus explicite « hors du domaine du recoupement » dans l'adaptateur | `core/finance/research/nautilus.py`, `tests/test_finance_research_nautilus.py`, ADR-024 | 4 |
| B123 | `market_data` ne donne que les cours et le référentiel : ni les taux (€STR) ni le change de la base ne sont exposés. L'analyste actualités et macro du Comité n'a donc pour taux et change que les pages lues, alors que le plan de phase 3 (§10) les attendait de `market_data`. Ajouter un `kind` « taux » et « change » à l'outil, point-in-time (R10) | `plugins/finance_data/`, `domain_packs/finance/committee.yaml` | 4 |

## Évaluations
| # | Élément | Origine | Phase |
|---|---|---|---|
| B59 | Juge et planificateur sont tous deux des modèles Anthropic (le tier deep sert aussi `planner_complex`) : juge d'un autre fournisseur ou second juge ; en attendant, relecture hebdomadaire de 20 jugements | `core/evals/judge.py`, plan §9 | ? |
| B60 | Mesures réelles que le hors-ligne ne prouve pas : résistance du modèle aux injections (canari écrit par le rédacteur, requête détournée), score du juge, coûts réels ; une campagne `eval-live` par accord de Lucas (D8) | `evals/redteam`, faille 5 | 1 (avec accord) |
| B61 | Journal d'audit : acteur ou type d'entrée dédié aux évals (le juge écrit aujourd'hui sous l'acteur `orchestrator`) | R11, `core/evals/judge.py` | 2 |
| B62 | Golden set : passer de 37 à 300 cas (objectif section 9), validés par Lucas puis gelés (R9) | section 9, plan §9 | 2 |
| B63 | Mode réel : le « petit lot en web réel » de l'ADR-009 n'est pas implémenté (le mode réel lit les pages fixtures) ; à ajouter sans stocker les résultats Brave (droits de stockage) | ADR-009, plan §9 | ? |
| B73 | Juge : refuser aussi un cas dont `payload.guard.pii` n'est pas vide, pas seulement ceux marqués `expect.pii` (le juge reçoit la question brute et la réponse ré-identifiée) | `core/evals/judge.py`, revue (F4), R6 | 2 |
| B118 | Recoupement sur le portefeuille de référence : couvrir aussi la CVaR, Kupiec, les contributions, le stress de taux et `var_change`, avec un ajustement recalculé depuis le générateur plutôt que relu par `closes()` comme le code testé | `tests/test_finance_risk.py`, revue quantitative phase 2 (14) | 3 |
| B119 | Aucun cas d'éval ne couvre la qualité « non évaluable » (seuil `min_quality_score_above_N1` à `A_DEFINIR` ou score absent), seuls les tests unitaires le font ; c'est pourtant l'état réel tant que `data_sources.yaml` garde `A_DEFINIR` | `evals/behaviors/` (`finance_qualite`), `core/finance/views.py`, D12 | 3 |

## Auto-amélioration et ouverture publique (ADR-011)
Décision de Lucas du 18/10/2026 : CERVEAU s'améliore seul, sans validation humaine, derrière deux
verrous automatiques (porte d'évals et de red team avant chaque mise en ligne, noyau verrouillé). La
phase 1 pose les premières briques : entrées `ERROR` et `FEEDBACK` du journal et `cerveau feedback`.

| # | Élément | Origine | Phase |
|---|---|---|---|
| B74 | Boucle d'apprentissage : lire les entrées `ERROR` et `FEEDBACK` et les notes de `var/feedback/`, regrouper les erreurs par type et par version de prompt, proposer une variante de prompt ou de paramètre (couche apprise uniquement) | ADR-011 | 7 |
| B75 | Porte de mise en ligne automatique : golden set, comportements et red team complets sur la variante, adoption seulement si aucun seuil ne baisse et si le gain dépasse la marge `A_DEFINIR` ; sinon rejet journalisé ; retour arrière automatique sur régression en production | ADR-011, R9 | 7 |
| B76 | Emplacement et format de la couche apprise (prompts et paramètres modifiables) : `A_DEFINIR` ; jamais `config/` ni les fichiers du noyau | ADR-011 | 7 |
| B77 | Verrouillage technique du noyau : l'apprentissage ne peut écrire ni dans les règles R1–R16, ni dans les limites de risque et de budget, ni dans l'autonomie, ni dans les golden sets, ni dans les garde-fous (ACL, contrôle de hash au démarrage, test qui échoue sinon) | ADR-011, ADR-003 | 7 |
| B78 | Défenses contre l'empoisonnement : retours d'un même utilisateur plafonnés, un retour seul ne change rien, la red team rejoue les retours suspects ; métrique de Goodhart (évals tenues hors de la boucle, jamais vues par elle) | ADR-011, R5 | 7 |
| B79 | Acteur `user` (ou identifiant par utilisateur) dans le journal ; en phase 1 un retour est signé `lucas` | ADR-011, R11 | 8 |
| B80 | Mémoire longue apprise : décider si des leçons apprises automatiquement peuvent coexister avec la règle de la section 11 (mémoire validée par Lucas) ou rester dans la seule couche apprise | ADR-011, section 11 | ? |
| B81 | Ouverture publique : comptes et authentification, isolation multi-locataire (journal, retours, mémoire, budgets par utilisateur) | ADR-011 | 8 |
| B82 | Ouverture publique : notice RGPD, base légale, durée de conservation, droit d'accès et oubli par utilisateur des retours (notes déjà hors du journal pour le permettre) ; anonymisation avant tout usage pour l'apprentissage | ADR-011, RGPD | 8 |
| B83 | Ouverture publique : quotas et budgets par utilisateur, limitation de débit, traitement des abus (signalement, blocage, retours écartés de l'apprentissage) | ADR-011, D9 | 8 |
| B84 | Ouverture publique : relire R16 (pas de conseil à des tiers) et les CGU des fournisseurs (Anthropic, Brave) avant tout accès d'un tiers | ADR-011, R15, R16 | 8 |
