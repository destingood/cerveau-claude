# ADR-022 — Capacité CALCUL du pack Finance, décidée après le routage

- Statut : **proposé** (élargissement de ce que la phase peut exécuter : à confirmer par l'utilisateur au
  compte rendu de phase ; revue `risk-gate-auditor` demandée avant `promotion.finance.N0_to_N1`)
- Date : 2026-10-18
- Phase : 2

## Contexte
Le moteur de politique (`core/policy/engine.py`) n'accordait en phase 1 que `auto` pour `LECTURE`,
dans tous les domaines : « élargir l'un ou l'autre ensemble est une décision de phase (ADR, évals,
l'utilisateur) ». Le plan de phase 2 validé (D1–D21) classe trois outils du pack Finance en `CALCUL`
(`risk_report`, `rebalance_proposal`, `performance_report`, D15) et la matrice de
`config/autonomy.yaml` donne `CALCUL` × N0 : `auto`. Sans élargissement :

- l'adaptateur MCP écarte ces trois outils (« politique : aucune capacité CALCUL… ») et le pack
  Finance ne peut répondre à aucune des questions de risque, d'optimisation ou de performance
  de la section 10.10 ;
- le contrôle d'entrée classe « Quelle est la VaR de mon portefeuille ? » en `CALCUL` (« produire
  un chiffre par un calcul ») et la refusait avant même le routage, faute de connaître le domaine.

Les calculs du pack Finance sont déterministes, testés et évalués (R1, R8) ; ceux d'un autre
domaine n'ont aucun outil : R1 interdit qu'un modèle les produise.

## Décision
- `PHASE_ACTION_CLASSES` reste `{LECTURE}` pour tous les domaines.
  `PHASE_DOMAIN_ACTION_CLASSES` accorde `{LECTURE, CALCUL}` au seul domaine `finance` (mapping en
  lecture seule). `decide` lit par défaut les classes du domaine (`phase_action_classes`).
  `PHASE_DECISIONS` reste `{auto}` : `brouillon`, `proposition`, `paper`, `approbation` et
  `auto_dans_limites` restent refusés.
- Une classe accordée à certains domaines seulement (`ROUTED_ACTION_CLASSES`, ici `CALCUL`) n'est
  plus décidée par le contrôle d'entrée, qui ne connaît que le domaine par défaut. Elle est
  décidée par le nœud de routage, avec le domaine routé, avant l'ouverture de tout outil. Un refus
  y renvoie la requête vers la sortie (`_after_route`) : ni planificateur, ni outil, et une entrée
  DECISION avec la route (domaine, aucun outil).
- Le message de refus nomme le domaine : « aucune capacité CALCUL pour le domaine « generaliste »
  dans cette phase : refus ».
- L'adaptateur MCP garde sa décision par outil : un outil `CALCUL` n'est exposé que si le domaine
  de la requête est `finance`.
- Rien ne change pour les autres classes (`ECRITURE_INTERNE`, `COMMUNICATION_EXTERNE`,
  `IRREVERSIBLE`, `FINANCIERE`) : refus au contrôle d'entrée, comme en phase 1. Le kill switch
  prime toujours (R4).

## Conséquences
- Les trois outils `CALCUL` du pack Finance sont exposés au planificateur Finance. Une question
  classée `CALCUL` et routée vers la finance est traitée ; routée ailleurs (y compris vers un
  domaine sans pack, qui retombe sur le généraliste), elle est refusée après le routage.
- Une question de calcul refusée coûte désormais un appel de classifieur de plus (le routage).
- Les cas de calcul généraliste (`calcul-*` du golden généraliste, `p2_chiffres`) gardent leur
  attente (refus contenant « CALCUL ») : hors ligne, la route scriptée est généraliste. En réel,
  si le routeur envoyait un calcul générique vers la finance, le planificateur Finance n'aurait
  aucun outil pour le faire et la vérification signalerait tout chiffre non tracé (R1) : les cas
  `calcul-*` le mesurent à la prochaine campagne réelle.
- Une requête de la classe `LECTURE` routée vers la finance peut appeler un outil `CALCUL` :
  chaque appel est décidé par l'adaptateur et journalisé (TOOL_CALL, R11).
- Tests : `tests/test_policy.py` (cellules de la finance à chaque niveau, refus ailleurs,
  Hypothesis), `tests/test_orchestrator.py`, `tests/test_orchestrator_finance.py`,
  `tests/test_mcp_adapter.py` (serveur `finance_risk` réel).

## Options écartées
- Accorder `CALCUL` à tous les domaines : aucun outil de calcul déterministe hors de la finance (R1).
- Décider `CALCUL` au contrôle d'entrée avec un domaine deviné : le domaine n'est connu qu'au
  routage, et deviner revient à accorder plus que la matrice ne le dit.
- Reclasser les questions de risque en `LECTURE` dans le prompt du contrôle d'entrée : la classe
  décrirait mal l'action, et la politique ne verrait plus qu'un calcul est demandé.
