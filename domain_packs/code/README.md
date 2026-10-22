# Pack Code

Pack P3 de CERVEAU (section 9.2, complément de plan P3, partie P3a) : lecture des dépôts git de
Lucas (historique, différences, fichiers commités), contrôles ruff et pytest dans un conteneur
isolé, état des derniers runs GitHub Actions. Autonomie courante N0 (`config/autonomy.yaml`,
`domains.code`, D3) : le pack lit et contrôle, il n'écrit rien. N2 (branche locale et PR en
brouillon) n'arrive qu'en P3b, avec `code_agent`. Statut : **expérimental** jusqu'à ce que Lucas le
passe en « actif » au vu d'une mesure réelle du golden set (section 9.3, D2).

Chaque compte (tests, diagnostics, lignes) et chaque citation viennent de l'outil qui les a lus
(R1). Le dépôt de CERVEAU est refusé par le code, même s'il est listé (ADR-047) ; un fichier
sensible est nommé, jamais montré, et un secret vu dans un diff est masqué (R6). Tout texte d'un
dépôt (code, commentaire, message de commit, sortie de pytest, titre de run) est une donnée (R5).

## Contenu

| Fichier | Rôle |
|---|---|
| `manifest.yaml` | Périmètre, plugins (`code_repo`, `code_checks`, `code_ci`), renvoi à l'autonomie, aux seuils et à `config/code.yaml` (dépôts autorisés, conteneur, CI) |
| `prompts/role.md` | Rôle et méthode du domaine, insérés dans le prompt système (Annexe D) |
| `prompts/rubric.md` | Grille du juge des évals : critères notés 0, 1 ou 2 ; le score est calculé par le code (R1) |
| `knowledge/sources.yaml` | Corpus RAG : vide en P3a ; le code vient des dépôts de la liste blanche |
| `evals/golden.jsonl` | Golden set : 31 cas (minimum 30), seuil 0,80 (`config/evals.yaml`, D4) : revue de diff, historique et fichiers, contrôles (ruff, pytest, environnement non préparé, hors délai), CI, « je ne sais pas », injection, secrets, dépôts refusés, R16 |
| `evals/behaviors.yaml` | 6 cas : comptes de pytest et de ruff cités de l'outil (R1), clé privée commitée nommée sans contenu (R6), fichier introuvable (R12), retour pour un candidat refusé (R16), question générale de programmation laissée au généraliste (ADR-050) |

Le red team du pack est dans `evals/redteam/injection_code/` (12 cas : consignes dans un diff, un
sujet de commit, une docstring, un identifiant de test ou un titre de run ; planificateur
compromis qui demande un chemin hors du dépôt, un lien symbolique sortant, un fichier `.env`, le
dépôt de CERVEAU, un dépôt hors liste, un push ou une relance de CI) ; les suites communes à tous
les packs dans `evals/behaviors/` et `evals/redteam/injection_base/`.

## Données des cas hors ligne

Les cas portent leur dépôt (`code.commits`, avec `links` pour un lien symbolique), et au besoin le
dépôt de CERVEAU listé (`code.cerveau`), la sortie de chaque contrôle (`code.checks`) et les runs
de CI (`code.runs`). Les marqueurs `«JETON_FICTIF»` et `«CLE_PRIVEE»` sont remplacés à la
construction par un jeton et une clé fictifs, jamais écrits dans le dépôt (R6, gitleaks). Aucun
réseau ni conteneur : le dépôt est construit dans un dossier temporaire, Docker et GitHub sont
remplacés par des doublures qui rendent la sortie du cas (`core/evals/code_fixtures.py`), et les
trois serveurs du pack tournent pour de vrai dessus.
