---
name: spec-kit
description: "Construire un projet ou une grosse fonction à partir d'une spec écrite, avec Spec Kit de GitHub (github.com/github/spec-kit, licence MIT, CLI specify) : principes du projet (constitution), spec, plan, tâches, code, puis contrôle que le code colle à la spec ; extensions pour réparer un bug pas à pas ou évaluer une idée avant de la construire. Vérifie qu'il est là, sinon l'installe sur ce PC avec l'accord de l'utilisateur, puis le pose dans le projet. À utiliser quand l'utilisateur dit « spec kit », « spec-kit », « speckit », « specify init », « spec-driven », « développement piloté par la spec », « installe spec kit dans ce projet », « /speckit-specify ». Ne pas utiliser pour un plan ou une tâche en plusieurs étapes dans la conversation (superpowers:writing-plans), un bug ordinaire (superpowers:systematic-debugging) ni une idée de business sans code (validate-idea)."
---

# Spec Kit — la spec d'abord, le code ensuite

## 1. Déjà là ?
- CLI : `specify version` répond, en 1.x (une 0.x ne connaît pas `--integration`). Sinon installer (2).
- Projet : `.specify/` et `.claude/skills/speckit-*/` existent → aller en 4. Sinon le poser (3).

## 2. Installer la CLI (code tiers : l'utilisateur donne son accord, ou lance lui-même les commandes)
1. uv : `uv --version`, sinon `winget install --id=astral-sh.uv -e` (Windows) ou
   `curl -LsSf https://astral.sh/uv/install.sh | sh` (Mac, Linux).
2. Dernier tag : `gh api repos/github/spec-kit/releases/latest --jq .tag_name` (ou la page Releases du dépôt).
3. `uv tool install --python 3.12 specify-cli --from git+https://github.com/github/spec-kit.git@vX.Y.Z`
   — `--python 3.12` : avec Python 3.15, `pyyaml` n'a pas de roue et sa compilation exige Visual C++ ; uv
   télécharge 3.12 s'il manque. Route GitHub épinglée = celle que recommande le dépôt (PyPI `specify-cli` aussi officiel).
4. Vérifier : `specify version`, puis `specify check` doit afficher « Claude Code (available) ».
   Pas de télémétrie dans le code (relu en 1.2.5) ; réseau vers GitHub pour les catalogues et les mises à jour.

## 3. Poser Spec Kit dans un projet (terminal, dans le dossier parent ou le projet)
- Nouveau : `specify init mon-projet --integration claude --integration-options="--no-model-invocation"`
- Existant : committer d'abord, puis
  `specify init --here --force --integration claude --integration-options="--no-model-invocation"` (fusionne).
- `--integration claude` toujours : sans lui, le mode non interactif choisit Copilot.
- `--no-model-invocation` : les 10 skills `speckit-*` ne partent qu'à la main (`/speckit-…`) et leurs
  descriptions restent hors du contexte (tokens). Elles sont gardées par `specify integration upgrade claude`.
- Scripts PowerShell par défaut sous Windows (marchent avec 5.1), Bash sur Mac et Linux.
- Pose `.specify/` (modèles, scripts, constitution) et `.claude/skills/speckit-*/` : à committer avec le projet.
  Si les `/speckit-…` n'apparaissent pas, nouvelle conversation.

## 4. Le déroulé (dans la conversation, une étape à la fois, relire chaque résultat avant la suivante)
1. `/speckit-constitution <principes>` — une fois par projet → `.specify/memory/constitution.md`.
2. `/speckit-specify <quoi et pourquoi, sans technique>` → `specs/NNN-nom/spec.md`.
3. Option : `/speckit-clarify` (questions sur les zones floues), avant le plan.
4. `/speckit-plan <choix techniques>` → `plan.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`.
5. `/speckit-tasks` → `tasks.md`. Options : `/speckit-checklist`, `/speckit-analyze` (cohérence avant de coder).
6. `/speckit-implement`, puis `/speckit-converge` ; recommencer les deux jusqu'au verdict « converged ».

Extensions (terminal, dossier du projet ; elles restent appelables par le modèle, donc n'ajouter que l'utile) :
- `specify extension add bug` → `/speckit-bug-assess "symptôme" slug=x`, `/speckit-bug-fix slug=x`,
  `/speckit-bug-test slug=x` ; rapports dans `.specify/bugs/x/`, seul le verdict `verified` vaut réparation.
- `specify extension add assess` → `/speckit-assess-intake "idée" slug=x`, puis `-research`, `-define`, `-shape`,
  `-decide` (même `slug`) ; décision `go`, `needs-clarification` ou `kill` dans `.specify/assessments/x/`.
- `specify extension add git` : une branche par fonction. Catalogue (`specify extension search`) : non audité,
  relire le code avant d'installer.

## Lequel choisir
- Spec Kit : projet ou grosse fonction dont la spec doit rester dans le dépôt (reprise plus tard, ami, autre
  agent). Plusieurs étapes et fichiers : seulement quand l'utilisateur le demande.
- superpowers:writing-plans puis executing-plans : tâche en plusieurs étapes, sans dossier de spec.
- superpowers:systematic-debugging : bug ordinaire ; l'extension `bug` dans un projet déjà sous Spec Kit.
- validate-idea : idée de business ; `assess` pour une idée de logiciel dans un projet Spec Kit.

## Mise à jour et retrait
- CLI : `uv tool install --force --python 3.12 specify-cli --from git+https://github.com/github/spec-kit.git@vX.Y.Z`.
  Jamais `specify self upgrade` nu sur un PC en Python 3.15 : il réinstalle sans `--python` et casse l'outil
  (vu en 1.2.5) ; à défaut, poser `UV_PYTHON=3.12` avant. Nouveauté dispo ? `specify self check` (lecture seule).
- Projet : committer, puis `specify integration upgrade claude` (reprend les options gardées ; passer
  `--integration-options` les remplace toutes) et `specify extension update`.
- Retrait : `uv tool uninstall specify-cli` ; dans un projet, `specify integration uninstall claude` (garde les
  fichiers modifiés), puis supprimer `.specify/` si on n'en veut plus. Les specs de `specs/` restent.

## Règles
- Étapes `/speckit-…` dans la conversation ; commandes `specify` dans le terminal.
- `/speckit-implement` écrit du code et lance des commandes : prévenir avant ce qui envoie, publie ou supprime.
- `specify extension add github` (`/speckit-github-taskstoissues`) crée des issues sur GitHub : publication,
  seulement sur demande explicite.
