# Étape 1 — Propositions pour les réglages non fixés

Date : 17/11/2026 · Statut : **proposé**, à valider ligne par ligne par l'utilisateur.
Plan : `docs/archive/plans/plan-parite-aladdin.md`, étape 1. Sources lues le 17/11/2026 (certaines par le
cache de Firecrawl, daté du 15 ou du 16/11/2026).

`cerveau config check` compte 57 marqueurs (39 `A_DEFINIR`, 18 `A_VERIFIER`) qui bloquent 38
fonctions. Ce document propose une valeur pour chacun. Rien n'est écrit dans `config/` avant ta
validation. Les réglages de gouvernance (`config/live.yaml`, limites, autonomie), c'est toi qui les
écris (P9 du plan, R3).

Colonne « Qui » : **L** = toi seul ; **C** = Claude Code après ta validation.

## 1. Trois faits qui changent des hypothèses du dépôt

1. **Le prélèvement forfaitaire unique est de 31,4 % en 2026, pas de 30 %.** Il se compose de
   12,8 % d'impôt et de 18,6 % de prélèvements sociaux. La CSG sur les revenus du patrimoine a
   augmenté de 1,4 point (art. 12 de la loi n° 2025-1403 du 30/12/2025, LFSS 2026). Les
   plus-values sur titres et le PEA sont concernés ; l'assurance-vie reste à 17,2 %. Sources :
   service-public.gouv.fr F21618 et F2329, boss.gouv.fr (page CSG), art. 200 A du CGI.
2. **Aucun ETF MSCI World coté en euros ne couvre la crise de 2008.** EUNL commence en 09/2009,
   CW8 en 06/2009 (puis une fusion en 2018). Le stress test 2008 doit donc s'appuyer sur la série
   de l'indice lui-même, ou sur un substitut déclaré comme tel (`[Approximation]`). Trouver une
   source gratuite de cette série reste à faire (étape 3).
3. **Le dépôt GitHub d'OpenBB redirige vers `github.com/openbq-org/OpenBB`**, une organisation au
   nom inhabituel, alors que PyPI pointe toujours vers `OpenBB-finance`. Il peut s'agir d'un
   transfert de dépôt ou d'un typosquat. OpenBB reste désactivé tant que ce n'est pas élucidé
   (risque de chaîne d'approvisionnement, T6).

## 2. Faits vérifiés (`A_VERIFIER`)

| Réglage | Proposition | Source | Certitude | Qui |
|---|---|---|---|---|
| `risk.yaml › market_risk.benchmark.isin` | **IE00B4L5Y983** (iShares Core MSCI World UCITS ETF Acc, EUNL sur Xetra en EUR) : TER 0,20 %, encours 150 Md USD, réplication physique. Alternative moins chère : Xtrackers IE00BJ0KDQ92 (XDWD, TER 0,12 %, depuis 2014) | page produit iShares ; etf.dws.com | élevée | C |
| `historical_stress.crise_2008` | **31/10/2007 → 09/03/2009** (pic à creux du MSCI World, −57,46 % en USD) ; variante « Lehman » : 15/09/2008 → 09/03/2009 | fiche MSCI World du 30/10/2026 (maximum drawdown) ; federalreservehistory.org (Lehman) | élevée en USD ; dates en EUR non vérifiées | C |
| `historical_stress.covid_2020` | **19/02/2020 → 23/03/2020** | pic et creux du S&P 500 cités dans des documents déposés à la SEC (N-CSR, 424B2) | élevée pour le S&P 500 ; non vérifiée pour le MSCI World en EUR | C |
| `historical_stress.taux_2022` | **03/01/2022 → 12/10/2022** (S&P 500 : 4 796,56 → 3 577,03, −25,4 %). La première hausse de la BCE (21/07/2022) tombe après l'essentiel de la baisse | ecb.europa.eu (communiqué du 21/07/2022) ; dates du S&P 500 : source secondaire seulement (Capital Group) | élevée sur les faits ; source primaire à trouver | C |
| `data_sources.yaml › fred.terms` | Clé API obligatoire (32 caractères, une par application) ; 120 requêtes par minute, au-delà une erreur 429 ; séries de tiers sous copyright limitées à un usage personnel ; mention obligatoire « This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis » ; cache local compatible (lecture des conditions, pas un avis juridique) | fred.stlouisfed.org/docs/api (terms_of_use, api_key, errors) | élevée | C |
| `data_sources.yaml › openbb.url` | `http://127.0.0.1:8001/mcp` (`openbb-mcp`, streamable HTTP ; paquet `openbb-mcp-server` 2.0.1) | README du serveur MCP ; PyPI | élevée | C, mais `enabled: false` tant que le point 3 du §1 n'est pas élucidé |
| `data_sources.yaml › openbb.terms` | Apache-2.0 (et non AGPL) ; conditions de chaque fournisseur de données en plus ; données « not necessarily accurate » | fichier LICENSE ; PyPI `openbb` 5.0.0 | élevée pour la licence | C |
| `compliance.yaml › fiscal.regime_plus_values` | PFU 31,4 % (12,8 % + 18,6 %). L'option pour le barème est globale et annuelle ; 6,8 points de CSG sont alors déductibles. Prix moyen pondéré par série de titres de même nature, **tous comptes confondus** ; le calcul compte par compte n'est qu'une tolérance (BOFiP § 40). Moins-values imputables 10 ans, sur des plus-values de même nature. PEA : exonéré d'impôt après 5 ans, prélèvements sociaux dus | art. 200 A et 150-0 D du CGI ; BOI-RPPM-PVBMI-20-10-20-40 ; service-public F21618, F2329, F22449 | élevée ; à confirmer par un professionnel avant toute déclaration (R16) | C |
| `compliance.yaml › fiscal.comptes_etrangers_declaration` | Un formulaire 3916 / 3916-bis par compte ouvert, utilisé ou clos à l'étranger, y compris un courtier étranger comme Interactive Brokers et les comptes de crypto-actifs (art. 1649 A et 1649 bis C du CGI). Amende de 1 500 € par compte (10 000 € pour un État non coopératif) ; crypto : 750 € par compte | service-public F34342 ; BOI-CF-CPF-30-20 ; Légifrance | élevée | C |
| `compliance.yaml › crypto.plateforme_autorisee_france` | Vérifier sur la liste blanche des PSCA de l'AMF, puis sur le registre MiCA de l'ESMA. La période transitoire a pris fin le 01/07/2026. Agréés MiCA et passeportés en France : Kraken (Payward Europe Solutions Ltd, Irlande), Coinbase (Coinbase Luxembourg S.A.), Bitstamp (Bitstamp Europe S.A., Luxembourg). Binance France SAS : enregistrement radié le 02/07/2026 | fiches AMF des trois PSCA ; communiqué AMF du 06/07/2026. Registre ESMA non lu (blocage anti-robot) | élevée pour l'AMF ; moyenne pour les noms d'entité | C |
| `data_sources.yaml › legifrance.terms` (texte) | Version des CGU de PISTE, durée de vie du jeton : à lire dans PISTE une fois l'application créée | — | — | L |
| `data_sources.yaml › attack.sha256` | Inscrite par `cerveau cyber attack-fetch`, que tu lances toi-même (G5) | — | — | L |

## 3. Frais et glissement (`risk.yaml › trading_costs`)

Proposition fondée sur Interactive Brokers, formule « Fixed », Euronext Paris et Xetra (décision P5
du plan ; interactivebrokers.ie, pages des commissions, lues le 17/11/2026) :

| Réglage | Proposition | Justification | Qui |
|---|---|---|---|
| `commission_pct` | **0.05** | 0,05 % du montant | C |
| `min_commission_eur` | **3.75** | minimum de 3,00 €, plus 0,75 € de frais de bourse refacturés par exécution sur les ETF d'Euronext : prudence | C |
| `slippage_bps` | **5** | ETF les plus liquides de Xetra : environ 3,5 pb aller-retour pour 100 000 € (XLM 2024, Deutsche Börse), soit 1,75 pb par sens ; marge de prudence d'environ ×3 (choix, pas un chiffre publié) | C |
| `fx_conversion_bps` | **3** | conversion automatique d'IBKR : environ 0,03 % ajouté au cours ; la conversion manuelle coûte 0,2 pb, minimum 2 USD | C |

Non couvert par ce modèle de frais : la taxe sur les transactions financières (0,3 % sur certaines
actions françaises, pas sur les ETF), la TVA éventuelle et les abonnements aux données de marché.
L'entité IBKR des résidents français (Ireland ou Central Europe) n'est pas confirmée sur une page
officielle.

## 4. Choix à faire (`A_DEFINIR`)

| Réglage | Proposition | Raison | Qui |
|---|---|---|---|
| `budgets.yaml › llm_budget_eur.daily` / `.monthly` | **5 € / 50 €** | coût estimé hors ligne : p95 de 0,03 à 0,05 € par requête (rapports P1 et P2) ; 50 € par mois couvrent environ 1 000 requêtes et une campagne d'évals | L |
| `budgets.yaml › per_committee` | **400 000 jetons, 600 s, 40 appels** | ta proposition du plan de phase 3 | L |
| `budgets.yaml › per_deep_research` | **300 000 jetons, 600 s, 30 appels** | 5 sous-questions et 12 lectures au plus (D13), avec de la marge pour les recherches | L |
| `budgets.yaml › per_code_agent` | **500 000 jetons, 960 s, 10 appels** | une tâche de 900 s au plus, plus la réponse ; une tâche par requête | L |
| `code.yaml › agent.max_requests` | **60** | 30 tours au plus (`max_turns`), deux requêtes par tour, dans la limite de `max_usd` à 2 | L |
| `code.yaml › repositories`, `checks.image`, `agent.image`, `agent.proxy_image` | tes dépôts et les images que tu construis (`infra/agent/README.md`) | — | L |
| `compliance.yaml › exclusions_personnelles` | `[]` (aucune), ou ta liste de secteurs ou d'émetteurs | choix personnel | L |
| `data_sources.yaml › quality.outlier_robust_z` | **3.5** | z modifié d'Iglewicz et Hoaglin, déjà proposé dans le fichier | C |
| `data_sources.yaml › quality.max_unexplained_move` | **0.30** | déjà proposé dans le fichier | C |
| `data_sources.yaml › legifrance.url` | bac à sable `https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app` d'abord | aucune application PISTE n'existe encore | L |
| `evals.yaml › regression_block_delta` | **0.03** | bloque une baisse de plus de 3 points du score du juge par rapport à la référence | L |
| `guardrails.yaml › pii.score_threshold` | **0.5** | valeur des évals hors ligne, proposée à chaque phase depuis la phase 1 | L |
| `interfaces.yaml › discord.owner_user_id` | ton identifiant numérique Discord | — | L |
| `interfaces.yaml › api.port` | **8787** | port libre courant ; boucle locale seule | L |
| `interfaces.yaml › ntfy.server` | `https://ntfy.sh` | D14, jusqu'au VPS | L |
| `models.yaml › tiers.local.model` | reporté | aucune fonction ne l'exige avant l'étape 7 | L |
| `risk.yaml › kill_switch.data_loss_timeout_seconds` | **60** | cours quotidiens en paper ; à resserrer pour l'intrajournalier | L |
| `risk.yaml › plugin_health.slo_breach_days_before_disable` | **2** | défaut documenté au § 6.5 du méga-prompt | L |
| `risk.yaml › keys.rotation_days` | **90** | rotation trimestrielle | L |
| `risk.yaml › infra.private_network` | reporté (WireGuard au déploiement du VPS) | B9 | L |
| `risk.yaml › optimization.risk_aversion` | **3** (prudent, entre 2 et 5) | aucune source primaire : c'est un choix d'attitude face au risque | L |
| `risk_limits.paper.yaml › universe` | pour commencer, l'indice de référence (EUNL) et les lignes de ton portefeuille | — | L |
| `autonomy.yaml › N3_to_N4.*` | reporté | N4 est hors du plan | L |
| `live.yaml › broker` | Interactive Brokers (P5), écrit à la main par toi seulement | R3 | L |

## 5. Points restés incertains

1. Dates de pic et de creux du MSCI World **en euros** (2008, 2020, 2022) : il faut les recalculer
   sur la série de l'indice.
2. Source primaire des dates 2022 du S&P 500 (S&P Dow Jones Indices).
3. Redirection du dépôt OpenBB vers `openbq-org`.
4. Registre MiCA de l'ESMA : non lu ; noms exacts d'entité (Kraken).
5. Entité IBKR des résidents français ; TTF, TVA et données de marché.
6. PEA : taux historiques des prélèvements sociaux sur les gains acquis avant 2018.
7. Compte chez une plateforme crypto passeportée en France mais établie à l'étranger : il se
   déclare a priori sur le 3916-bis, à confirmer par un professionnel.

## 6. Après validation

Claude Code écrit les lignes « C » validées, lance `cerveau config check` et les tests, puis
présente les fonctions débloquées. Tu écris les lignes « L ».
