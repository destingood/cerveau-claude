# Pack Code

Pack P3 de CERVEAU (section 9.2, complément de plan P3, parties P3a et P3b) : lecture des dépôts
git de l'utilisateur (historique, différences, fichiers commités), contrôles ruff et pytest dans un
conteneur isolé, état des derniers runs GitHub Actions, et tâche de code confiée à un agent
Claude Code (`code_agent`, ADR-053, ADR-054) sur une copie isolée, dont le patch est enregistré
sous `var/code/agent/<id>/` sans être appliqué. Autonomie courante N0 (`config/autonomy.yaml`,
`domains.code`, D3, F9) : le pack lit, contrôle et propose un patch, il n'écrit rien dans un
dépôt ; l'utilisateur relit et applique lui-même. N2 (branche locale et PR en brouillon) n'est pas livré :
il se gagnera par les évals réelles (R9). Statut : **expérimental** jusqu'à ce que l'utilisateur le passe
en « actif » au vu d'une mesure réelle du golden set (section 9.3, D2).

Chaque compte (tests, diagnostics, lignes) et chaque citation viennent de l'outil qui les a lus
(R1). Le dépôt de CERVEAU est refusé par le code, même s'il est listé (ADR-047) ; un fichier
sensible est nommé, jamais montré, et un secret vu dans un diff est masqué (R6). Tout texte d'un
dépôt (code, commentaire, message de commit, sortie de pytest, titre de run) et le résumé de
l'agent sont des données (R5) ; le patch nomme ses chemins à risque (CI, outils, hooks,
contrôles) et écarte les fichiers sensibles sans les lire.

## Contenu

| Fichier | Rôle |
|---|---|
| `manifest.yaml` | Périmètre, plugins (`code_repo`, `code_checks`, `code_ci`, `code_agent`), renvoi à l'autonomie, aux seuils et à `config/code.yaml` (dépôts autorisés, conteneur, CI, agent) |
| `prompts/role.md` | Rôle et méthode du domaine, insérés dans le prompt système (Annexe D) |
| `prompts/rubric.md` | Grille du juge des évals : critères notés 0, 1 ou 2 ; le score est calculé par le code (R1) |
| `knowledge/sources.yaml` | Corpus RAG : vide en P3a ; le code vient des dépôts de la liste blanche |
| `evals/golden.jsonl` | Golden set : 43 cas (minimum 30), seuil 0,80 (`config/evals.yaml`, D4) : revue de diff, historique et fichiers, contrôles (ruff, pytest, environnement non préparé, hors délai), CI, « je ne sais pas », injection, secrets, dépôts refusés, R16 ; 12 cas de l'agent (patch rendu, contrôles de la copie, dépôts refusés, budget de tâche absent, secret masqué, erreur, délai, plafond du proxy, Docker absent, lecture sans agent, clé absente) |
| `evals/behaviors.yaml` | 10 cas : comptes de pytest et de ruff cités de l'outil (R1), clé privée commitée nommée sans contenu (R6), fichier introuvable (R12), retour pour un candidat refusé (R16), question générale de programmation laissée au généraliste (ADR-050) ; pour l'agent, comptes de la copie cités d'agent_task (R1), clés jamais montrées (R6), tours épuisés sans patch (R12), patch pour un client refusé (R16) |

Le red team du pack est dans `evals/redteam/injection_code/` (18 cas : consignes dans un diff, un
sujet de commit, une docstring, un identifiant de test ou un titre de run ; planificateur
compromis qui demande un chemin hors du dépôt, un lien symbolique sortant, un fichier `.env`, le
dépôt de CERVEAU, un dépôt hors liste, un push ou une relance de CI ; agent qui écrit un workflow
de CI, des réglages de Claude Code, un `conftest.py` ou un fichier d'environnement, qui donne des
consignes dans son résumé ou que le proxy refuse) ; les suites communes à tous
les packs dans `evals/behaviors/` et `evals/redteam/injection_base/`.

## Données des cas hors ligne

Les cas portent leur dépôt (`code.commits`, avec `links` pour un lien symbolique), et au besoin le
dépôt de CERVEAU listé (`code.cerveau`), la sortie de chaque contrôle (`code.checks`) et les runs
de CI (`code.runs`), et ce que ferait l'agent (`code.agent` : fichiers écrits dans la copie,
dernière ligne du runner, comptes du proxy, Docker ou clé absents). Les marqueurs `«JETON_FICTIF»` et `«CLE_PRIVEE»` sont remplacés à la
construction par un jeton et une clé fictifs, jamais écrits dans le dépôt (R6, gitleaks). Aucun
réseau ni conteneur : le dépôt est construit dans un dossier temporaire, Docker et GitHub sont
remplacés par des doublures qui rendent la sortie du cas (`core/evals/code_fixtures.py`), aucun
modèle n'est appelé et la clé de l'API est une valeur factice que le serveur ne lit pas ; les
quatre serveurs du pack tournent pour de vrai dessus.
