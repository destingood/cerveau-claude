# ADR-013 — Sources de données de marché : pas de yfinance, OpenBB reporté

- Statut : **accepté par Lucas le 18/10/2026** (plan de phase 2, D1, D2, D3, D5)
- Date : 2026-10-18
- Phase : 2

## Contexte
Le §17 cite « OpenBB MCP + yfinance » parmi les livrables de `finance_data`. Faits vérifiés le
18/10/2026 :
- les CGU de Yahoo (versions US et UE) interdisent d'accéder aux Services ou d'en collecter des
  données par tout moyen automatisé sans permission écrite préalable. yfinance (Apache-2.0)
  interroge Yahoo de cette façon et imite l'empreinte TLS d'un navigateur ;
- openbb 5.0.0 et openbb-mcp-server 2.0.1 sont sous Apache-2.0, mais leur extension Yahoo
  (`openbb-yfinance`) est sous AGPL-3.0. Le serveur MCP expose un outil `install_skill` qui écrit
  sur le disque, son authentification ne couvre pas le transport stdio, et la plupart de ses
  fournisseurs exigent une clé ;
- la BCE autorise la réutilisation de ses données si elle est citée comme source et que toute
  modification est signalée.

## Options
1. **yfinance**, comme le prévoit le §17 : gratuit et simple, mais contraire à R15.
2. **OpenBB MCP** : large couverture, mais une pile lourde, un outil qui écrit sur le disque, et un
   intérêt réel seulement avec des fournisseurs à clé.
3. **Une interface `MarketDataProvider` et des fournisseurs légaux** : fixtures (hors ligne), CSV
   exporté par Lucas, BCE pour le change et les taux, puis une API officielle choisie avec Lucas
   (Tiingo Starter, ou un fournisseur couvrant Euronext).

## Décision
Option 3. `config/data_sources.yaml` passe `yfinance` à `enabled: false` (resserrement) et active
`ecb`. OpenBB part au backlog. IBKR est lu par un export CSV ou Flex que Lucas télécharge lui-même,
sans connexion de compte ni jeton. Le fournisseur de cours à clé s'ajoute quand Lucas l'a choisi :
il crée la clé et la place dans une variable d'environnement que Claude Code ne lit jamais. Chaque
ligne ingérée garde sa source, et chaque sortie d'outil la cite (R1, R12).

## Conséquences
- Écart assumé au livrable du §17 (« OpenBB MCP + yfinance ») : R15 l'emporte. L'écart est
  signalé dans le compte rendu de phase.
- Plus simple : zéro secret et zéro réseau en CI ; la BCE n'exige pas de clé.
- Plus difficile : sans fournisseur à clé, les cours viennent des CSV de Lucas ou des fixtures ; les
  fondamentaux attendent ce fournisseur.
- Réversible : oui ; OpenBB pourra s'ajouter derrière la même interface (stdio, catégories
  autorisées, `install_skill` exclu par le manifeste).
