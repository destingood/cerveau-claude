---
paths:
  - "evals/**"
---

# Évaluations

- **R9.** Ne jamais baisser un seuil ni retoucher un golden set pour faire passer une PR. Un cas faux
  se corrige dans une PR dédiée, justifiée, que l'utilisateur valide.
- Un nouveau cas s'ajoute ; un cas existant ne se supprime pas sans ADR ou accord de l'utilisateur.
- Chaque suite déclare son seuil et la commande qui la lance (`make eval`). Les résultats sont
  comparés à la dernière exécution de référence ; une régression au-delà du seuil bloque la fusion.
- Les jeux de données respectent R10 (point-in-time) et ne contiennent aucune donnée personnelle de
  tiers ni aucun secret (R6).
- Revue conseillée : agent `eval-engineer`.
