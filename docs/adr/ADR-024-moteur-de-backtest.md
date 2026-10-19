# ADR-024 — Moteur de backtest : stratégie pure, moteur maison et adaptateur NautilusTrader 1.231

- Statut : accepté (D1, D6 et D12 du plan de phase 3, validées par Lucas le 19/10/2026 ; la
  sémantique détaillée ci-dessous est soumise à sa relecture au compte rendu de phase 3)
- Date : 2026-10-19
- Phase : 3

## Contexte
La spec (§10.6) demande NautilusTrader pour les stratégies candidates. Elle veut aussi que le même code
de stratégie tourne en backtest puis en live, et que les écarts avec le live soient documentés.
R1 impose que tout chiffre vienne d'un outil déterministe, R10 qu'aucune donnée postérieure à la
décision ne soit lue et que les frais soient toujours inclus. La base n'a que des clôtures.

Faits vérifiés le 19/10/2026 :

- **Version et licence** : NautilusTrader 1.231.0 (02/08/2026) est sous LGPL-3.0-or-later. La v1 ne
  reçoit plus que les correctifs de sécurité critiques. La 2.0 n'existe qu'en rc et exige
  Python 3.13 (README, PyPI).
- **Ordre de traitement d'une barre**, lu dans la source installée
  (`nautilus_trader/backtest/engine.pyx`, `_run`) : la place traite la barre (`process_bar`), puis la
  stratégie la reçoit (`on_bar`), puis les commandes en file sont exécutées au même horodatage
  (`_process_and_settle_venues`). Un ordre au marché envoyé dans `on_bar(t)` est donc rempli sur la
  barre de t.
- **Frais et glissement** : `FillModel` ne glisse que d'un tick, avec une probabilité. Le glissement
  en points de base doit donc passer par un `FeeModel` maison, dont la méthode à surcharger est
  `get_commission(order, fill_qty, fill_px, instrument) -> Money`.
- **Précision** : la roue Windows installée est en précision standard (`FIXED_PRECISION = 9`,
  `HIGH_PRECISION = False`). Les montants `Money` sont arrondis à la précision de la devise (2
  décimales pour l'EUR).
- **Dépendance vulnérable** (vérifié le 20/10/2026) : NautilusTrader 1.231.0 fixe
  `fsspec==2026.2.0`. Cette version est touchée par PYSEC-2026-4217 (CVE-2026-104851, publiée le
  15/10/2026) : exécution de code par les gabarits de `ReferenceFileSystem`, corrigée en 2026.6.0.
  `pip-audit` bloque donc la CI.

## Options
1. NautilusTrader seul : sa sémantique (file de commandes, compte, risque pré-trade) devient la
   référence, sans contrôle indépendant.
2. Moteur maison seul : simple, mais c'est un écart à la spec, et il n'a pas de chemin vers le live.
3. **Stratégie pure + moteur maison de référence + adaptateur NautilusTrader mince, recoupés.**

## Décision
Option 3.

- **Stratégie** : un objet avec `decide(vue, paramètres) -> poids cibles`. La vue est un
  `PointInTimeView` lié à la date t (ADR-026). Les poids sont positifs, leur somme est ≤ 1, le
  reste en cash. Il n'y a ni vente à découvert, ni levier, ni entrée-sortie, ni horloge, ni hasard.
  Une forme vectorisée facultative (`weights_frame`) sert au criblage. Le contrôle d'invariance par
  troncature (ADR-026) prouve qu'elle redonne `decide`.
- **Exécution (D6)** :
  - **Décision** : à la date t, avec les données publiées avant l'heure de coupure
    `decision_cutoff_utc` de t (`config/research.yaml`).
  - **Quantités** : cible qᶜ = w·Vₜ / pₜ, où Vₜ est la valeur à la clôture de t et pₜ la clôture de t.
    L'ordre est l'écart qᶜ − q **arrondi vers zéro** à l'entier : on ne dépasse jamais la cible.
  - **Exécution** : à la clôture de t+1. Un planificateur commun aux moteurs passe les ventes
    d'abord. Il traite ensuite les achats par écart de valeur croissant (w·Vₜ − q·pₜ, à égalité par
    identifiant), comme l'ordre `call_seq='auto'` de vectorbt. Chaque achat est réduit au plus
    grand entier que le cash projeté couvre, frais compris.
- **Frais** (s = glissement en fraction, c = commission en %, m = minimum par ordre) :
  - prix d'exécution p·(1+s) à l'achat et p·(1−s) à la vente ;
  - commission = max(m, c·q·p·(1±s)) ;
  - cash de l'achat = −(q·p + q·p·s + commission) ; cash de la vente = +(q·p − q·p·s − commission) ;
  - change : en phase 3, un instrument hors EUR est refusé par les deux moteurs ;
    `fx_conversion_bps` est lu et validé, sans autre effet (multidevise au backlog) ;
  - arrondi : mode `cent` (glissement et commission arrondis séparément au centime, au pair le plus
    proche) pour le réalisme et le recoupement avec NautilusTrader ; mode `none` (aucun arrondi)
    pour le recoupement avec vectorbt (ADR-025).
- **Valeurs des frais** : elles viennent de `config/risk.yaml#trading_costs`. Tant qu'elles valent
  `A_DEFINIR`, un backtest sur données réelles est refusé (R7). La démonstration utilise un jeu de
  frais **fictif**, nommé comme tel dans chaque sortie.
- **Opérations sur titres** : dividendes crédités en cash à la date ex, à condition d'être publiés
  à cette date (sinon à leur publication). Splits appliqués aux quantités à leur date d'effet.
  Impôts non modélisés. Cash non rémunéré `[Hypothèse]`.
- **Mesures** : rendements quotidiens Vₜ/Vₜ₋₁ − 1, sans flux externe. Volatilité, Sharpe, Sortino,
  perte maximale et Calmar avec les conventions de l'ADR-020 (ddof = 1, × √252). Taux sans risque :
  €STR (ADR-020) sur données réelles, nul sur données synthétiques `[Hypothèse]`, ce qui est écrit
  dans le rapport. S'y ajoutent :
  - la rotation annualisée : Σ montants échangés / (2 × valeur moyenne) × 252 / séances ;
  - le nombre d'opérations, les frais payés et l'exposition moyenne.
- **Moteur maison** (`core/finance/research/engine.py`, numpy et pandas) : c'est la référence.
- **Adaptateur NautilusTrader** (`core/finance/research/nautilus.py`, seul module qui l'importe) :
  - **Place et compte** : `BacktestEngine`, une place fictive `SIM`, `OmsType.NETTING`,
    `AccountType.CASH` en EUR.
  - **Instruments et barres** : un `Equity` par instrument (quantités entières). Une barre
    quotidienne par séance, avec O = H = L = C = clôture.
  - **Ordres** : la stratégie adaptatrice garde la décision de t et soumet les ordres du
    planificateur commun sur la **dernière barre de t+1**. Ils sont donc remplis à la clôture de
    t+1.
  - **Frais** : un `FeeModel` maison renvoie glissement et commission arrondis (mode `cent`).
  - **Calendrier** : un univers dont les séances diffèrent d'un instrument à l'autre est refusé.
  - **À vérifier** à l'implémentation : le contrôle pré-trade d'un compte cash face aux achats
    financés par les ventes de la même barre. S'il bloque, il sera désactivé en backtest seulement
    (le planificateur fait ce contrôle), et l'ADR le dira. `add_venue` n'expose que
    `allow_cash_borrowing` (faux par défaut), qui n'est pas activé sans cette preuve.
  - **fsspec** : `pyproject.toml` force `fsspec==2026.9.0` par `override-dependencies` (uv), contre
    l'épinglage exact de NautilusTrader. CERVEAU n'ouvre aucun système de fichiers fsspec. Un
    backtest de fumée est passé avec cette version le 20/10/2026, et le recoupement D12 la teste à
    chaque exécution de la CI. L'override est retiré dès qu'une version de NautilusTrader épingle
    une version corrigée. C'est un écart à une contrainte amont, soumis à Lucas au compte rendu.
- **Recoupement (D12)** : sur la démonstration, les deux moteurs doivent produire les mêmes
  opérations (date, instrument, sens, quantité) et la même valeur finale, à 1e-6 près en relatif.
  Les frais sont comparés à part. Le recoupement porte sur l'exécution et la comptabilité : la
  décision et le planificateur sont communs par construction.

## Conséquences
- **Chemin vers le live** : en phase 4, le paper changera l'adaptateur, pas la stratégie. Le passage
  à NautilusTrader 2 (Python 3.13) ne touchera que `nautilus.py` (backlog).
- **Limites écrites dans chaque rapport** : clôture seulement, pas de carnet ni de liquidité, place
  fictive, ni latence ni persistance, et les écarts avec le live que la spec cite.
- **Périmètre du recoupement NautilusTrader** : séries de prix sans dividende ni split. Les
  opérations sur titres sont testées dans le moteur maison seul (écart documenté).
- **Tests** : invariants Hypothesis (valeur = cash + positions ; frais ≥ 0 ; quantités entières ;
  ni découvert ni levier), recoupement des deux moteurs, cas du planificateur à court de cash.
