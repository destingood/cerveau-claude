---
paths:
  - "plugins/finance_*/**"
  - "core/risk_gate/**"
  - "core/policy/**"
---

# Finance, Porte de risque et moteur de politique

- **R1 — Chiffres déterministes.** Aucun LLM ne produit un chiffre décisionnel final (prix, mesure de
  risque, taille de position, montant). Les chiffres viennent d'outils déterministes testés ; le LLM
  orchestre, interprète, critique et explique. Tout chiffre affiché cite l'outil qui l'a calculé.
- **R2 — Porte de risque.** Aucune action réelle sans passer par le moteur de politique puis, pour la
  finance, par la Porte de risque déterministe. Le LLM émet une intention structurée validée par schéma ;
  il n'appelle jamais un broker directement.
- **R10 — Point-in-time.** Aucune donnée publiée après la date de décision dans un backtest ou une
  évaluation de décision. Frais, coûts et glissement toujours inclus.
- **Tests obligatoires.** Toute modification de ces dossiers arrive avec ses tests : cas limites,
  refus attendus, tests de propriétés (Hypothesis) pour les calculs. Pas de couverture = pas de fusion.
- Une limite inconnue vaut `A_DEFINIR` et bloque la fonction (R7) ; ne jamais deviner une valeur.
- Après la modification : demander une revue `quant-reviewer` (calculs) et `risk-gate-auditor`
  (Porte de risque, politique).
