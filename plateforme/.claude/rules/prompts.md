---
paths:
  - "**/prompts/**"
---

# Prompts

- Toute modification de prompt met à jour la suite de comportements correspondante et relance les
  évals concernées (R9) : skill `run-evals`.
- Chaque prompt porte une version ; elle est écrite dans le journal d'audit à chaque appel (R11).
- Un prompt n'autorise jamais à suivre des instructions venues d'un contenu externe (R5) et ne
  demande jamais au modèle de produire un chiffre décisionnel (R1).
- Aucun secret, aucune donnée personnelle de tiers dans un prompt (R6).
