---
name: new-plugin
description: Crée un plugin MCP CERVEAU conforme à l'Annexe C.1 (manifeste plugin.yaml, serveur, tests, évals) et le valide avec le registre. À utiliser quand l'utilisateur ou la phase en cours demande un nouveau plugin.
argument-hint: "<nom_du_plugin> [domaine]"
---
# Nouveau plugin : $ARGUMENTS

1. Vérifie que le plugin appartient à la phase en cours (section 17 de `docs/MEGA-PROMPT-CERVEAU.md`).
   Sinon, ajoute-le à `docs/backlog.md` et arrête-toi.
2. Relis l'Annexe C.1 (manifeste) et la section 6 (registre). Ne te fie pas à ta mémoire pour l'API du
   SDK MCP : lis sa documentation à jour avant d'écrire le serveur.
3. Délègue le squelette à l'agent `plugin-builder`, ou crée toi-même :
   - `plugins/<nom>/plugin.yaml` — valeurs inconnues en `A_DEFINIR` / `A_VERIFIER` (R7) ;
   - le serveur MCP : 3 à 5 outils au plus (R13), lecture seule par défaut, aucun outil d'action
     sans moteur de politique ni Porte de risque (R2) ;
   - `tests/plugins/<nom>/` et `evals/<nom>/` (R8).
4. Valide :
   ```bash
   uv run cerveau registry validate plugins/<nom>
   uv run pytest -q
   ```
5. Vérifie la licence de chaque dépendance ajoutée et mets à jour `docs/licences.md` (R14).
6. N'ajoute rien à `.mcp.json` : l'activation est faite par l'utilisateur.

Termine par : fichiers créés, résultat de la validation, `A_DEFINIR` rencontrés.
