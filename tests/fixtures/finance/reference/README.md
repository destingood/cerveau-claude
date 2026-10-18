# Portefeuille de référence fictif

Données de test et d'évaluation du pack Finance (plan de phase 2, §4). **Tout est inventé** :
les instruments, les cours, les opérations, les changes et l'€STR. Aucun identifiant ne désigne
un vrai titre (pas d'ISIN), chaque nom porte « (fictif) » et aucune valeur ne vient d'un
fournisseur. Ces données ne disent rien d'un vrai marché.

## Fichiers

| Fichier | Contenu | Format |
|---|---|---|
| `instruments.csv` | 10 instruments `FICT-…` : 6 actions, 2 ETF, 1 obligation, 1 or | référentiel CSV (ADR-013) |
| `cours.csv` | clôtures quotidiennes du 16/10/2023 au 16/10/2026 | `date,identifiant,cloture,devise` |
| `operations.csv` | 34 opérations : 1 split, 33 dividendes | `date_ex,identifiant,type,valeur,devise,date_annonce` |
| `bce_change.csv` | change de référence USD et GBP contre l'euro | réponse `csvdata` de la BCE (flux EXR) |
| `bce_estr.csv` | €STR du 16/10/2023 au 15/10/2026 | réponse `csvdata` de la BCE (flux EST) |
| `generate.py` | le générateur, à graine fixe | Python : bibliothèque standard et `core.finance.calendars` |

Devises : EUR, USD (FICT-GLOBEX, FICT-EMERG) et GBP (FICT-HELIOS). Places : XPAR, XETR, XNYS,
XLON. Les cours suivent les séances de chaque place selon exchange-calendars ; les changes et
l'€STR suivent le calendrier TARGET.

## Régénérer

```bash
uv run python tests/fixtures/finance/reference/generate.py
```

La graine est fixe (`cerveau-reference-2026`), chaque série a son propre flux aléatoire, et
les tirages gaussiens sont calculés à la main (Box–Muller) : le résultat ne dépend pas de la
version de Python. `tests/test_finance_reference.py` vérifie que les fichiers commités sont
exactement ceux du générateur. Une nouvelle version d'exchange-calendars qui change un jour
férié peut casser ce test : il faut alors régénérer et relire le diff. Les CSV sont en fin de
ligne LF sur toutes les plateformes (`.gitattributes`).

## Anomalies placées

| Anomalie | Où | Ce qu'elle teste |
|---|---|---|
| Split 2 pour 1 | FICT-ACME, jour ex 16/06/2025, annoncé le 20/05/2025 | l'ajustement des cours ; le split n'est connu qu'à la fin du jour d'annonce |
| Dividendes annuels | ACME, BOREAL, CYGNE, DELTA, EMERG, en EUR ou en USD | le rendement total |
| Dividendes trimestriels | FICT-GLOBEX, 12 en USD | une devise étrangère |
| Dividendes sans date d'annonce | FICT-BOREAL, FICT-HELIOS (en GBP) | la date de connaissance par défaut : 00:00 à Paris le jour ex |
| Cours manquant | FICT-CYGNE, 16/09/2026 | le contrôle des trous |
| Cours aberrant (× 1,22) | FICT-BOREAL, 20/11/2025 | le contrôle des valeurs aberrantes, sans le prendre pour un split |
| Pic de volatilité | actions, ETF et or, du mardi 13 au vendredi 16/10/2026 (choc de marché, volatilité propre doublée) | « pourquoi la VaR a-t-elle augmenté depuis lundi ? » |
| Obligation à duration connue | FICT-OAT35, zéro coupon, échéance 12/03/2035, duration 8,4 | la sensibilité aux taux |

Le renforcement d'une position pendant la semaine de stress (lundi 12/10/2026) et la trésorerie
en EUR et en USD viendront avec l'import du portefeuille : il n'y a pas encore de fichier de
transactions.

## Dates de connaissance

Les fichiers sont lus comme s'ils avaient été récupérés le dimanche 18/10/2026 à 12:00 UTC.
Chaque valeur est datée à son heure de publication documentée (ADR-017). L'€STR du vendredi
16/10/2026 ne serait publié que le lundi 19/10 : le générateur l'omet, la série s'arrête donc au
15/10.

## Chargement

`core.finance.fixtures.load_reference(store, quality=…, window_sessions=…)` charge ces fichiers
dans une base finance par les vrais fournisseurs (`CsvCorporateActions`, `CsvCloses`,
`EcbProvider`), sans réseau : les fichiers de la BCE sont servis par un transport en mémoire.
Chaque enregistrement porte la source `fixtures`, jamais `csv` ni `ecb` (R12).
