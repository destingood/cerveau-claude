# ADR-049 — Capacité CALCUL du pack Code

- Statut : **proposé** (élargissement de ce que la phase peut exécuter : à confirmer par Lucas au
  compte rendu de P3a ; revue `risk-gate-auditor` à faire, non lancée en P3a)
- Date : 2026-10-22
- Phase : 6 (P3a)

## Contexte
Le moteur de politique (`core/policy/engine.py`) accorde `{LECTURE}` à tous les domaines et
`{LECTURE, CALCUL}` au seul domaine `finance` (ADR-022) ; élargir l'un ou l'autre ensemble est une
décision de phase. Le complément de plan P3 validé (« GO P3 », E1–E6, §3) classe `run_checks`
(plugin `code_checks`) en `CALCUL` : l'outil exécute ruff et, si Lucas a préparé l'environnement du
dépôt, pytest, dans un conteneur sans réseau, en lecture seule et borné (ADR-048, E3–E5). La
matrice de `config/autonomy.yaml` donne `CALCUL` × N0 : `auto`.

Sans élargissement, l'adaptateur MCP écarte `run_checks` (« aucune capacité CALCUL pour le domaine
« code » ») et le nœud de routage refuse toute question de contrôle routée vers le pack Code : les
cas `code-checks-*` du golden set et les behaviours `code-pack-comptes-*` échouent par construction.

## Décision
- `PHASE_DOMAIN_ACTION_CLASSES` accorde `{LECTURE, CALCUL}` au domaine `code`, comme à `finance`.
  `PHASE_ACTION_CLASSES` reste `{LECTURE}` et `PHASE_DECISIONS` reste `{auto}` : `brouillon`,
  `proposition` et au-delà restent refusés, donc aucune écriture (N2 n'arrive qu'en P3b).
- Les comptes (tests, diagnostics) restent produits par l'outil, jamais par un modèle (R1) ; le
  code exécuté est celui du dépôt, isolé par le conteneur (ADR-048), jamais celui de CERVEAU
  (ADR-047).
- Rien ne change pour les autres domaines ni pour les autres classes ; le kill switch prime (R4).

## Conséquences
- Une question classée `CALCUL` et routée vers `code` est traitée ; routée ailleurs, elle reste
  refusée après le routage (ADR-022).
- Le risque propre au pack Code est l'exécution de code non fiable (pytest importe le code testé) :
  il est porté par les bornes du conteneur (réseau coupé, lecture seule, utilisateur non root,
  capacités retirées, processeur, mémoire, processus et durée bornés) et non par la politique. Le
  premier test réel de Docker est à faire par Lucas (backlog).
- Tests : `tests/test_policy.py` (`test_phase_2_classes` : `code` accordé, `recherche`, `cyber` et
  les domaines inconnus refusés).
- Révocable en retirant l'entrée `code` : `run_checks` redevient refusé, le reste du pack lit.

## Options écartées
- Classer `run_checks` en `LECTURE` : la classe décrirait mal l'action (exécuter des outils sur une
  copie du dépôt) et la politique ne verrait plus qu'un calcul est demandé.
- Une classe dédiée (`EXECUTION_ISOLEE`) : changement de l'Annexe C.4 et de la matrice d'autonomie,
  hors du périmètre de P3a ; à reconsidérer si un pack exécute du code avec effets (backlog).
