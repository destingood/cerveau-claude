# ADR-033 — Adaptateur paper maison, recoupé par NautilusTrader, et réconciliation

- Statut : accepté (D1, D2, D14 à D16 du plan de phase 4, validées par Lucas le 20/10/2026)
- Date : 2026-10-20
- Phase : 4

## Contexte
Le §17 demande un adaptateur paper et une réconciliation. Le §8.6 impose un compte séparé. Aucune
source de cours d'actions n'est active ; les cours stockés sont des clôtures.

Faits relevés le 20/10/2026 dans NautilusTrader 1.231.0 (code installé) :

- `SandboxExecutionClient` enveloppe un `SimulatedExchange` dans un client d'exécution live et
  reçoit ses prix d'un client de données live : il exige un flux de données, donc un compte.
- `MakerTakerFeeModel.get_commission` vaut `notional_value(fill_qty, fill_px) × taker_fee` (ou
  `maker_fee` selon `liquidity_side`), en devise de cotation, sans minimum. `Money` arrondit
  `float(valeur) × 100` à l'entier le plus proche : une demi-cent décimale exacte peut y perdre un
  centime (1,005 € → 1,00 €, mais 5,025 € → 5,03 € ; mesuré le 21/10/2026 sur 200 000 valeurs,
  version 1.231.0). `MONEY_MAX` vaut 9 223 372 036.

## Options
1. `sandbox` NautilusTrader : flux live obligatoire.
2. Compte paper IBKR : compte de Lucas, TWS ou Gateway, clés hors dépôt.
3. **Simulateur maison**, sans réseau, recoupé par NautilusTrader en tests.

## Décision
Option 3 ; IBKR paper au backlog.

- **Interface** `BrokerAdapter` (Protocol) : `submit`, `cancel`, `cancel_all`, `open_orders`,
  `account_snapshot`, `fills_since`. Le reste du code ne connaît qu'elle.
- **`PaperSimulator` (D2, D16)** : compte en euros, capital initial = capital de référence, positions
  longues, sans levier, comptabilité propre dans `var/paper/`.
  - Un ordre DAY envoyé après la clôture de t est traité sur la séance t+1, comme le backtest.
  - Exécution à la clôture de t+1 si la limite l'autorise ; glissement défavorable `slippage_bps`
    plafonné au prix limite.
  - Participation au plus 5 % du volume de la séance (`max_participation_pct` dans
    `config/execution.yaml`) ; au-delà, `PARTIELLE`, puis le reste est annulé en fin de séance.
  - Frais de `trading_costs` ; montant hors de `MONEY_MAX` refusé explicitement (B122).
- **Recoupement (B154)** : chaque exécution est rejouée dans NautilusTrader (une barre au prix
  d'exécution, un ordre au marché) avec `MakerTakerFeeModel`, le minimum de commission ajouté par
  une enveloppe. Prix et positions doivent être égaux ; commissions et cash, égaux au centime à
  l'écart près que `Money` crée sur une demi-cent exacte, prédit exécution par exécution et jamais
  toléré en bloc (`tests/test_execution_nautilus.py`).
- **Réconciliation (D14, D15)** : après chaque exécution et chaque jour, le livre de CERVEAU, rejoué
  par `core/finance/portfolio`, est comparé au relevé de l'adaptateur (positions exactes, cash au
  centime). Un écart donne une alerte, une entrée au journal et le blocage des nouvelles intentions.
  Il se lève après une réconciliation propre **et** un acquittement de Lucas en terminal
  interactif. Un écart issu d'un incident d'exécution déclenche le kill switch. Le journal de
  réconciliation (`var/paper/reconciliation.db`, insertion seule) garde les écarts et leurs
  montants ; le journal d'audit reçoit une entrée `DECISION` par réconciliation et une entrée
  `APPROVAL` (acteur `lucas`) par acquittement, avec les actifs en écart, des nombres et des empreintes, sans montant
  (`core/execution/reconcile.py`).

## Conséquences
- Le paper ne tourne que sur le marché synthétique tant qu'aucune source de cours n'est choisie
  (D19).
- Le modèle de recherche (`_CostsFeeModel`) reste inchangé : il compte le glissement comme un frais
  à la clôture ; un modèle natif y différerait de c × montant × s (suite de B154 au backlog).
- **Tests** : exécution partielle, limite non atteinte, ordre annulé en fin de séance, refus au-delà
  de `MONEY_MAX`, recoupement au centime, écart forcé ⇒ blocage.

## Mise en œuvre de la boucle paper (21/10/2026)

`core/execution/loop.py` (`run_day`) et `core/execution/market.py`. Écarts et précisions par
rapport au plan de phase 4 (§10) :

- **Pas de `--date`** : la journée traitée est la dernière dont l'heure limite (21:00 UTC) est
  passée (`decision_day`). Une date choisie à la main permettrait de décider sur une séance dont
  la suite est déjà connue (R10). Une journée déjà close ne refait rien (`deja_traitee`).
- **Ordre des étapes** : kill switch, clôtures de séance (exécutions et réconciliation), puis
  fraîcheur des données, valorisation et limites de perte, puis intentions. Les exécutions passent
  avant la fraîcheur : elles ne dépendent que de la clôture de la séance, déjà exigée.
- **Lectures strictes** : seuls les enregistrements ingérés à l'instant du traitement sont lus,
  pour le simulateur (`StoreMarket`) comme pour la Porte (`market_facts`).
- **Arrondis prudents** : une clôture au-delà de six décimales compte comme absente, jamais
  arrondie ; le taux BCE inversé est arrondi vers le haut, le volume moyen et la valorisation vers
  le bas.
- **Âges** : celui d'un cours en séances de sa place closes depuis ; celui d'un taux en jours
  TARGET jusqu'au jour inclus (le taux du jour compte comme absent tant que le jour n'est pas fini).
  `open_markets` = places dont le calendrier est connu.
- **Compteurs de la Porte** : tout ordre allé au-delà de la proposition (états autres
  qu'`INTENTION` et `REJETEE`) compte dans les limites par heure et par jour.
- **Réduction** : une intention `REDUIT` garde son `intent_id`, quantité ramenée par la Porte.
- **Envoi** : `VALIDEE`, `ENVOYEE`, puis appel à l'adaptateur ; un refus de l'adaptateur passe
  l'ordre en `REJETEE`. À la reprise, un ordre resté `VALIDEE` (journée interrompue avant l'envoi)
  est annulé ; un ordre que le simulateur ne travaille plus est annulé (« expiré en fin de séance »).
- **Fenêtre de décision** : la `decision_date` d'une intention suit la date de Paris. Après minuit à
  Paris, une intention viserait une séance trop tard : la journée se valorise, mais n'en rédige
  aucune.
- **Issues** : `terminee`, `deja_traitee`, `pas_de_seance`, `attente_donnees`, `arret`. Une donnée
  périmée sur une position, une limite de perte franchie ou un incident d'exécution engagent le
  kill switch : l'issue est `arret`. Seule `terminee` clôt la journée dans `var/paper/loop.db`
  (insertion seule) ; les autres laissent la journée à reprendre. Le rapport
  `var/paper/reports/AAAA-MM-JJ.md` cite pour chaque section l'outil qui a produit ses chiffres
  (R1) ; une journée déjà close ne le réécrit pas.
- **Sources stratégie** (`core/execution/sources.py`) : chaque fiche `candidate` repasse ses
  contrôles de promotion chaque jour et rejoue le code de son backtest avec la configuration
  retenue par le rapport approuvé (retrouvé par son empreinte), à condition qu'elle soit un point de
  la grille (B179). Les ordres visent ses poids sur la valeur liquidative du compte paper ; les
  positions hors de son univers sont ignorées. Une candidate refusée ne propose rien et la raison
  figure dans les remarques du rapport.
- **CLI** : `cerveau paper run` (codes de sortie 0, 1, 2 et 4), `paper status`, `paper orders`,
  `paper report` (lecture seule, rien n'est créé), `paper acquitter` (Lucas seul, terminal
  interactif, B177) et `cerveau status` (B54).
- **Non couvert** : écart paper/backtest et compteurs N2→N3 (B181).
