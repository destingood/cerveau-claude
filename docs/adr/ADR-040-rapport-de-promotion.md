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
- **En-tête** : le rapport s'ouvre sur un en-tête YAML (`rapport: promotion`, `domain`, `level`,
  `statut`). À partir de N3, une signature ne compte que si le rapport cité porte sur le même
  domaine et le même niveau et conclut `promotion_possible` (`signatures.py`).
- **Écart paper/backtest** : sans seuil au §8.3, il est « atteint » dès qu'il est mesuré ; son
  détail l'explique (exécutions, frais, glissement, ordres sans exécution). Le backtest rejoue la
  configuration approuvée le jour du rapport, depuis la première valorisation paper.
- **Incidents** : arrêts `incident_execution` de tout le journal d'audit, chaîne vérifiée.
- **Journal** : chaque rapport écrit une entrée `TOOL_CALL` (chemin et SHA-256), pas une
  `DECISION` : la décision reste la signature de Lucas.
- **N3 → N4** : compteurs d'approbations posés (ADR-035) ; rapport en phase 7. D'ici là, une
  signature N4 ne peut pas compter : aucun rapport N4 ne conclut `promotion_possible`.

## Conséquences
- Une promotion est traçable : la signature cite l'empreinte du rapport, que le code vérifie.
- Le rapport est un chiffre déterministe : aucun modèle ne le produit.
