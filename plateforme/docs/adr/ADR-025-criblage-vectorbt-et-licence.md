# ADR-025 — Criblage vectorbt 1.1.2 isolé (licence Commons Clause) ; Qlib et RD-Agent reportés

- Statut : accepté (D2, D3 et D12 du plan de phase 3, validées par Lucas le 19/10/2026)
- Date : 2026-10-19
- Phase : 3

## Contexte
La spec (§10.6) cite vectorbt pour le criblage rapide d'idées (« licence Commons Clause : usage
personnel uniquement »), Qlib pour la recherche ML et RD-Agent en expérimental.

Faits vérifiés le 19/10/2026 :

- **Licence vectorbt** : `LICENSE.md` du dépôt polakowo/vectorbt indique Apache 2.0 avec la
  « Commons Clause » v1.0. La clause interdit de vendre le logiciel, ou un service dont la valeur
  vient de lui. GitHub affiche NOASSERTION.
- **Version retenue** : la 1.2.0 est publiée le jour même. La 1.1.2 (09/10/2026) est la plus récente
  qui a au moins 7 jours.
- **Poids** : avec le verrou actuel, vectorbt ajoute 33 paquets, dont numba 0.68.0, llvmlite, la pile
  IPython et widgets, et matplotlib.
- **Calcul d'un ordre**, lu dans la source installée (`vectorbt/portfolio/nb.py`) :
  - prix d'achat ajusté p·(1+glissement) ; frais = montant · `fees` + `fixed_fees` ;
  - à court de cash : taille = ⌊(cash − `fixed_fees`)/(1+`fees`)/prix ajusté⌋ à la granularité ;
  - `TargetPercent` : cible = w · valeur du groupe / `val_price`, l'écart à la position est
    tronqué à `size_granularity` (vers zéro, en achat comme en vente) ;
  - `call_seq='auto'` : ventes d'abord, puis les ordres par valeur approchée croissante ;
  - la suffisance du cash est testée avec une égalité approchée (`is_close_or_less_nb`).

## Options
1. vectorbt en dépendance principale : sa licence restrictive toucherait les serveurs MCP et
   l'orchestrateur.
2. Criblage maison en numpy, vectorbt reporté : c'est un écart au livrable du §17.
3. **vectorbt isolé**, dans un groupe uv `research`, importé par un seul module, en CLI seulement.

## Décision
Option 3.

- **Isolement (R14)** :
  - `core/finance/research/screening.py` est le seul module qui importe vectorbt, et il le fait à
    l'intérieur de ses fonctions. Un test vérifie qu'aucun autre module ne l'importe.
  - Aucun serveur MCP, ni l'orchestrateur, ni le protocole (ADR-026) n'en dépendent : le protocole
    fait tous ses calculs avec le moteur maison.
  - Le criblage se lance par `cerveau strategy screen`. Sans le groupe `research`, la commande le dit
    et s'arrête.
  - vectorbt est listé dans `docs/licences.md`, avec la clause.
- **Rôle** :
  - évaluer vite toute la grille d'une stratégie, avec sa forme vectorisée (ADR-024), frais et
    glissement compris ;
  - chaque combinaison évaluée est un essai, inscrit au journal des essais (ADR-026) avec
    l'origine `criblage`, même si elle est écartée ;
  - le criblage ne rend aucun verdict.
- **Correspondance avec le moteur maison** : `Portfolio.from_orders` est appelé ainsi :
  - poids de la décision de t placés sur la ligne de t+1, `size_type='targetpercent'` ;
  - `price` = clôture de t+1 et `val_price` = clôture de t ;
  - `size_granularity=1`, `cash_sharing=True`, `call_seq='auto'`, `direction='longonly'` ;
  - `fees` = commission, `slippage` = glissement, `fixed_fees` = 0.

  Le minimum par ordre n'a pas d'équivalent exact : le moteur maison prend max(m, c·montant), là où
  vectorbt additionne `fixed_fees`.
- **Recoupement (D12)** : il porte sur le moteur maison en mode d'arrondi `none` avec un minimum à
  0, sur des séries sans dividende ni split. Le Sharpe, sur un échantillon de combinaisons, doit
  concorder à 1e-9 près en relatif. Avec un minimum non nul ou l'arrondi au centime, l'écart est
  mesuré et publié, jamais caché par une tolérance élargie. L'égalité approchée du test de cash peut
  faire diverger un achat à la limite exacte du cash : si cela arrive, le test le montre et l'écart
  est documenté.
- **Qlib et RD-Agent (D3)** : reportés au backlog. Ils ne font pas partie des livrables du §17, ils
  tirent mlflow, redis, pymongo, gym et jupyter, et le protocole n'a pas besoin de recherche ML.
  C'est un écart à la spec (§10.6), assumé ici.

## Conséquences
- **Licence** : le cœur de CERVEAU reste libre de la Commons Clause. Une ouverture publique (phase 8)
  ne redistribuera jamais vectorbt, et le README rappellera qu'un service payant fondé sur lui
  violerait sa licence.
- **Coût** : `uv sync` installe le groupe `research` par défaut (`default-groups`), et la première
  exécution compile numba. L'effet sur la durée de `make test` est mesuré au compte rendu.
- **Réversible** : le criblage peut être remplacé par une boucle du moteur maison sans changer le
  protocole.
