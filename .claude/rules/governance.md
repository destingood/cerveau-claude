---
paths:
  - "config/**"
  - "governance/**"
---

# Configuration et gouvernance

- **Ne jamais modifier `config/live.yaml` ni `governance/approvals/**`.** Seul Lucas les modifie, à la
  main (R3). Les hooks `protect_paths.py` et `guard_shell.py` refusent ces écritures ; ne pas chercher
  de contournement. Un refus se signale à Lucas, il ne se contourne pas.
- Tout nouveau paramètre sensible (limite, seuil, budget, frais, fiscalité, identifiant de modèle)
  vaut `A_DEFINIR` (décision de Lucas) ou `A_VERIFIER` (fait à contrôler à la source). Jamais de valeur
  devinée (R7).
- Une valeur peut seulement être rendue plus prudente par Claude Code ; l'assouplir est réservé à Lucas.
- Après toute modification d'un fichier `config/*.yaml` : `uv run cerveau config check`.
- Aucun secret dans ces fichiers (R6) : les secrets vivent dans `infra/.env` (hors dépôt) ou dans un
  gestionnaire de secrets.
