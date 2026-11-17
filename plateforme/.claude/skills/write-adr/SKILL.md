---
name: write-adr
description: Rédige un ADR (Architecture Decision Record) court au format du projet dans docs/adr/ (contexte, options, décision, conséquences). À utiliser pour chaque choix structurant (stack, orchestration, stockage, sécurité, dépendance majeure).
argument-hint: "<titre de la décision>"
---
# ADR : $ARGUMENTS

1. Numérote : prochain numéro libre de `docs/adr/` (`ADR-NNN-titre-en-kebab-case.md`).
2. Relis les ADR existants : le nouveau ne doit pas en contredire un sans le déclarer
   (« Remplace ADR-00X »).
3. Format (français, une page au plus) :
   ```markdown
   # ADR-NNN — Titre

   - Statut : proposé | accepté | remplacé par ADR-00X
   - Date : AAAA-MM-JJ
   - Phase : N

   ## Contexte
   Problème, contraintes (règles R1–R16 concernées), faits vérifiés avec sources et dates.

   ## Options
   2 à 4 options, avec avantages, inconvénients, licence (R14) et coût.

   ## Décision
   L'option retenue et pourquoi, en quelques phrases.

   ## Conséquences
   Ce qui devient plus simple, plus difficile, réversible ou non ; tâches induites (backlog).
   ```
4. Les faits cités (versions, licences, fonctionnalités) sont vérifiés à la source le jour même
   (agent `source-verifier`) ; une incertitude est écrite comme telle.
5. Statut « proposé » tant que l'utilisateur n'a pas validé.
