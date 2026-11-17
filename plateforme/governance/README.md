# Gouvernance

- `approvals/` : signatures manuelles de l'utilisateur (par exemple `AAAA-MM-JJ-finance-N3.md`, section 8).
  Seul l'utilisateur y écrit ; Claude Code n'y crée rien, pas même un `.gitkeep`. Git ne suit donc ce
  dossier qu'à partir de la première approbation.
- `kill_switch/` : la présence du fichier `KILL` déclenche l'arrêt d'urgence (section 8).
