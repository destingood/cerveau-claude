---
name: phase-report
description: Produit le compte rendu de fin de phase au format imposé de la section 18 dans docs/rapports/. Déclenché uniquement par l'utilisateur.
disable-model-invocation: true
argument-hint: "<numéro de phase>"
---
# Compte rendu — Phase $ARGUMENTS

1. Rassemble les faits, sans rien inventer :
   - `git log --oneline` depuis le début de la phase ;
   - `make test`, `make lint`, `make eval`, `make audit-verify` (résultats chiffrés) ;
   - `gitleaks git --no-banner` ;
   - ADR produits (`docs/adr/`), `docs/backlog.md`, `A_DEFINIR` présents dans `config/` et le code.
2. Fais relire la phase par l'agent `security-reviewer` (exigé par la section 17) et reporte ses
   constats BLOQUANT / MAJEUR.
3. Écris `docs/rapports/phase-N-AAAA-MM-JJ.md` en français, au format exact :
   ```markdown
   ## Compte rendu — Phase N — AAAA-MM-JJ
   1. Synthèse (3 à 5 phrases)
   2. Livré (modules, fichiers, commandes)
   3. Tests et évals (résultats chiffrés, comparaison aux seuils)
   4. Écarts à ce document + ADR produits
   5. Risques ouverts et dette technique
   6. Coûts de la phase (LLM, infrastructure)
   7. Décisions demandées à l'utilisateur (liste des A_DEFINIR rencontrés)
   8. Optimisation & Prochaines Étapes
   ```
4. Un résultat non mesuré s'écrit « non mesuré », jamais estimé sans le dire (R12).
5. Arrête-toi ensuite et attends `GO PHASE N+1`.
