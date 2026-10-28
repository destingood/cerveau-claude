# ADR-001 — Stack technique du cœur

- Statut : accepté (Lucas, 2026-10-18, décision D13 du plan de phase 1)
- Date : 2026-10-17
- Phase : 0

## Contexte
La section 5 du méga-prompt fixe des choix par défaut ; tout écart passe par un ADR. Règles
concernées : R6 (secrets), R7 (aucune valeur sensible en dur), R11 (audit), R14 (licences).
Poste de développement : Windows 11 (PowerShell et Git Bash) ; cible : VPS Debian (phase de
déploiement). Faits vérifiés le 2026-10-17 :

| Composant | Version retenue | Licence | Source |
|---|---|---|---|
| Python (géré par uv) | 3.12.15 | PSF | `uv python list` |
| uv | 0.13.1 | Apache-2.0 ou MIT | dépôt astral-sh/uv |
| pydantic / jsonschema / PyYAML / Typer | 2.14.1 / 4.26.0 / 6.0.3 / 0.27.3 | MIT | PyPI |
| pytest / Hypothesis / ruff | 9.1.1 / 6.170.1 / 0.17.1 | MIT / MPL-2.0 / MIT | PyPI |
| pip-audit / pre-commit | 2.10.1 / 4.7.0 | Apache-2.0 / MIT | PyPI |
| PostgreSQL + pgvector | image `pgvector/pgvector:0.8.7-pg17-trixie` | PostgreSQL License | Docker Hub |
| promptfoo (via `npx`, Node ≥ 22.22) | 0.124.1 | MIT | npm |
| gitleaks | 8.30.1 | MIT | GitHub releases |

## Options
1. **Défauts de la section 5** : Python 3.12 + uv, Pydantic, Typer, PostgreSQL + pgvector,
   Node.js limité aux outils (promptfoo, puis le bot Discord). Toutes les bibliothèques finance de
   l'Annexe A sont en Python.
2. **Cœur en Node.js / TypeScript** (langage que Lucas maîtrise) : écosystème finance quantitative
   (NautilusTrader, Riskfolio-Lib, QuantLib, qlib) absent ou indirect ; ponts Python à maintenir.
3. **Python avec pip + venv ou Poetry** : outillage plus lent ; pas de gestion intégrée de
   l'interpréteur ; verrouillage moins strict qu'`uv.lock`.

## Décision
Option 1. Précisions de la phase 0 :
- schémas en Pydantic v2 ; manifestes de plugins validés contre le JSON Schema de l'Annexe C.1
  avec jsonschema ; YAML lu uniquement par `yaml.safe_load` ;
- dépendances verrouillées par `uv.lock`, installées par `uv sync --frozen` en CI ;
- Python 3.12 installé par uv, indépendant du Python système (3.15 sur le poste) ;
- PostgreSQL 17 plutôt que 18 : version du Compose officiel de Langfuse (ADR-004) ; une montée de
  version majeure fera l'objet d'un ADR (changement d'emplacement des données dans l'image 18) ;
- DuckDB, Docling, Presidio, FastAPI et le SDK MCP arrivent avec les phases qui les utilisent.

## Conséquences
- Plus simple : un seul langage pour le cœur, la finance et les tests ; installation reproductible.
- Plus difficile : Node.js reste nécessaire pour promptfoo ; deux écosystèmes à auditer
  (`pip-audit` couvre Python ; l'audit npm de promptfoo est au backlog).
- Réversible : oui pour les bibliothèques ; le choix du langage du cœur ne l'est pratiquement pas.
- Hypothesis (MPL-2.0, copyleft faible par fichier) n'est utilisé qu'en développement, sans
  modification : sans effet sur CERVEAU (`docs/licences.md`).
