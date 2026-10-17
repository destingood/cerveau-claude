---
name: run-evals
description: Lance les évaluations concernées par les fichiers modifiés (prompts, plugins, packs, modèles) et compare les scores aux seuils et à la référence. À utiliser après toute modification de prompt, de plugin ou de configuration de modèle (R9), et avant chaque commit qui en touche.
argument-hint: "[chemin ou suite]"
---
# Évals concernées

1. Liste les fichiers modifiés : `git status --short` et `git diff --name-only`.
2. Déduis les suites à lancer :
   - `**/prompts/**`, `config/models.yaml` → suites de comportement + golden sets des packs concernés ;
   - `plugins/<nom>/**` → `evals/<nom>/` et tests du plugin ;
   - `domain_packs/<domaine>/**` → `domain_packs/<domaine>/evals/` ;
   - aucun de ces chemins → suite témoin seulement.
   Si `$ARGUMENTS` est fourni, lance seulement cette suite.
3. Lance :
   ```bash
   make eval
   uv run pytest -q
   ```
4. Compare chaque score à son seuil et à la dernière référence. Une régression au-delà du seuil
   bloque le commit.
5. Interdit (R9) : baisser un seuil, modifier ou supprimer un cas pour faire passer l'éval. Un cas
   douteux est signalé à Lucas.

Réponds par un tableau : suite, score, seuil, référence, écart, statut (OK / RÉGRESSION / ÉCHEC).
