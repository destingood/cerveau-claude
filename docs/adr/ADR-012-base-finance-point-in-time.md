# ADR-012 — Base Finance point-in-time en SQLite

- Statut : **accepté par Lucas le 18/10/2026** (plan de phase 2, D6)
- Date : 2026-10-18
- Phase : 2

## Contexte
Le pack Finance lit des cours, des opérations sur titres, du change, des taux et un portefeuille.
R10 interdit toute donnée postérieure à la date de décision. Or les séries ajustées que livrent
les fournisseurs sont recalculées en arrière à chaque split ou dividende : elles intègrent des
événements futurs. La phase 2 ne fait que lire, pour un seul utilisateur, et la CI tourne sans
réseau ni Docker.

## Options
1. **Postgres** (déjà dans `infra/`) : robuste, mais le service doit tourner pour chaque test ou
   chaque question, et les tests ont besoin de Docker.
2. **DuckDB** (MIT) : rapide en analytique, mais c'est une dépendance de plus, et le format de
   fichier change entre versions majeures.
3. **SQLite de la bibliothèque standard** : un fichier, aucune dépendance, transactions ACID,
   tests en mémoire.

## Décision
Option 3, dans `var/finance/finance.db` (ignoré par git) :
- un schéma versionné (`schema_version`), avec des migrations idempotentes et testées ;
- un modèle **bitemporel** : chaque ligne de cours, d'opération, de change et de taux porte sa
  date de valeur, sa date de publication (`published_at`), sa date d'ingestion (`ingested_at`) et
  un numéro de révision ;
- les lectures prennent une date `as_of` et ne voient que les lignes publiées au plus tard à cette
  date, dans leur dernière révision connue ; le mode strict lit `ingested_at` pour rejouer
  exactement ce que CERVEAU savait ;
- les cours sont stockés **bruts**, et l'ajustement est calculé à la lecture avec les seules
  opérations connues à `as_of` ;
- le référentiel d'instruments est versionné (`valid_from`, `valid_to`) ;
- seule la CLI (`cerveau finance sync`, `cerveau portfolio import`) écrit dans la base ; les
  outils MCP l'ouvrent en lecture seule (`mode=ro`).

## Conséquences
- Plus simple : aucun service à lancer, tests rapides en mémoire, sauvegarde par copie de fichier.
- Plus difficile : un seul écrivain à la fois, ce qui suffit pour la CLI de Lucas. La mémoire
  (phase 3, Postgres) restera séparée.
- Les fondamentaux du fournisseur ne sont pas point-in-time : ils sont marqués comme tels et exclus
  de tout backtest (R10).
- Réversible : oui ; le schéma est simple à porter vers Postgres (backlog).
