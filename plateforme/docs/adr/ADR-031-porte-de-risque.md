# ADR-031 — Porte de risque : fonction pure, échec fermé, réduction en titres entiers

- Statut : accepté (D3 à D6 et D23 du plan de phase 4, validées par l'utilisateur le 20/10/2026 ; valeurs
  des limites écrites à sa demande le 20/10/2026 ; l'univers reste `A_DEFINIR` jusqu'à sa liste)
- Date : 2026-10-20
- Phase : 4

## Contexte
Le §8.4 décrit la Porte de risque : une couche déterministe, sans modèle, qui accepte, réduit ou
refuse chaque intention. R2 interdit toute action réelle sans elle, R7 impose qu'une valeur inconnue
bloque. Le §17 exige au moins 10 000 cas générés sans intention hors limites acceptée et une
couverture de 100 %.

Faits relevés le 20/10/2026 : `core/risk_gate/` est vide. Les 9 limites de
`risk_limits.paper.yaml` n'ont ni borne ni unité (B156). Il manque les limites de pays, de devise,
de perte glissante, d'ordres par jour et l'univers autorisé. `trading_costs` est `A_DEFINIR`.

## Options
1. Contrôles dans l'orchestrateur, avec court-circuit au premier refus.
2. **Fonction pure isolée**, tous contrôles évalués, en `Decimal`.

## Décision
Option 2.

- **Forme** : `evaluate(intent, snapshot, limits, costs, compliance) -> RiskGateResult`. Pas de
  modèle, pas d'entrée-sortie, pas d'horloge implicite. Le `snapshot` est figé à la décision.
- **Échec fermé** : une limite `A_DEFINIR`, une donnée absente ou une exception donnent `REFUSE`.
  Chaque contrôle est évalué, pour que le refus donne toutes ses raisons.
- **Contrôles** : schéma et idempotence ; univers, marché ouvert, volume moyen ; taille (ordre,
  position, secteur, pays, devise, en % du capital de référence) ; pertes (jour, glissante,
  drawdown) ; prix (limite, bande, fraîcheur) ; cash, frais et change compris ; interdits (levier,
  vente à découvert, dérivés) ; fréquence (heure, jour) ; justification ; conformité (exclusions,
  crypto refusée tant que `A_VERIFIER`) ; réconciliation (aucun écart ouvert).
- **`REDUIT` (D6)** : seulement sur la taille et le cash, jusqu'au plus grand entier qui respecte
  toutes les limites ; 0 donne `REFUSE`. Le résultat garde les deux quantités.
- **Limites (D4, D5)** : pourcentages (5 = 5 %), bornés `gt=0, le=100` ; capital strictement
  positif ; nouvelles clés `max_country_pct`, `max_currency_pct`, `max_orders_per_day`,
  `max_rolling_loss_pct`, `rolling_loss_sessions`, `avg_volume_sessions`, `universe`.
- **Valeurs (D3)**, écrites à la demande de l'utilisateur le 20/10/2026 : capital 10 000 € ; ordre 5 % ;
  position 10 % ; secteur 30 % ; pays 60 % ; devise 50 % ; perte du jour 2 % ; perte glissante 5 %
  sur 20 séances ; drawdown 10 % ; 10 ordres par heure, 20 par jour ; bande de prix 2 % ; volume
  moyen 100 000 titres sur 20 séances. L'univers reste `A_DEFINIR` : la Porte refuse donc tout en
  usage réel.
- **Journal** : une entrée `POLICY` au format C.4 (`checks[{name, ok, value, limit}]`), acteur
  `risk_gate`.

## Conséquences
- **Tests (D23)** : profil Hypothesis `gate` (`max_examples=10_000`, `derandomize=True`,
  `deadline=None`, `database=None`) ; oracle écrit à part ; monotonie (resserrer une limite ne
  transforme jamais un refus en acceptation) ; limite inconnue ⇒ refus ; déterminisme ; seuil
  minimal de cas acceptés. Couverture lignes et branches de `core/risk_gate` à 100 % dans `make ci`.
- Un frais `A_DEFINIR` bloque le contrôle du cash : un paper réel attend la décision D13 de la
  phase 2.

## Amendement (phase 5, 21/10/2026)
- **Cash d'une vente (B188, D24, décision de l'utilisateur)** : une vente paie ses frais sur ce qu'elle
  rapporte ; elle n'exige que `max(0, frais − brut)`. Ce besoin décroît quand la quantité croît :
  la réduction cherche la plus grande quantité sur les autres contrôles de taille, puis vérifie le
  cash à cette quantité, et refuse s'il manque. Des frais d'au moins 100 % du montant sont une
  donnée inconnue (refus). Les ventes ouvertes réservent toujours leurs frais.
- **Justification (B195)** : la taille doit venir de l'outil qui dimensionne l'origine,
  `strategy.<id>` pour une stratégie, `rebalance_proposal` pour un comité ; tout autre outil est
  refusé. La Porte ne lit pas le journal : que l'appel y figure relève de la boucle, et le test de
  complétude du journal le vérifie.
