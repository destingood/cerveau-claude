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
  interactif. Un écart issu d'un incident d'exécution déclenche le kill switch.

## Conséquences
- Le paper ne tourne que sur le marché synthétique tant qu'aucune source de cours n'est choisie
  (D19).
- Le modèle de recherche (`_CostsFeeModel`) reste inchangé : il compte le glissement comme un frais
  à la clôture ; un modèle natif y différerait de c × montant × s (suite de B154 au backlog).
- **Tests** : exécution partielle, limite non atteinte, ordre annulé en fin de séance, refus au-delà
  de `MONEY_MAX`, recoupement au centime, écart forcé ⇒ blocage.
