# ADR-040 — Rapport de promotion N2 → N3 généré, signature manuelle

- Statut : accepté (D17 du plan de phase 5 : 13 semaines, 30 décisions, drawdown paper ≤ 10 %,
  validées par Lucas le 21/10/2026)
- Date : 2026-10-21
- Phase : 5

## Contexte
Le §8.3 et le §17 demandent un rapport de promotion automatique, que Lucas signe à la main. Les
compteurs N2 → N3 et l'écart paper/backtest manquent (B181).

## Décision
- **`cerveau promotion report finance --to N3`** écrit `var/promotion/finance-N3-AAAA-MM-JJ.md` et
  affiche son SHA-256.
- **Critères** (`autonomy.yaml`, `promotion.finance.N2_to_N3`), chacun avec valeur, seuil, statut
  et outil source (R1) : semaines de paper (≥ 13), décisions (≥ 30), drawdown paper (≤ 10 %),
  incidents d'exécution (0), écart paper/backtest mesuré, golden et red team du domaine.
- **Seuil `A_DEFINIR` ou mesure absente** : critère « non évaluable », promotion impossible (R7).
- **Signature** : le rapport propose le texte du fichier de signature (ADR-036). Lucas le copie
  lui-même dans `governance/approvals/` ; le code n'y écrit jamais.
- **N3 → N4** : compteurs d'approbations posés (ADR-035) ; rapport en phase 7.

## Conséquences
- Une promotion est traçable : la signature cite l'empreinte du rapport, que le code vérifie.
- Le rapport est un chiffre déterministe : aucun modèle ne le produit.
