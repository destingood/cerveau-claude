# ADR-028 — Mode Comité : sous-graphe enregistré, débat contrôlé par le code, verdict déterministe

- Statut : accepté (D15 à D22 du plan de phase 3, validées par Lucas le 19/10/2026 ; le budget d'une
  séance reste `A_DEFINIR` jusqu'à sa décision)
- Date : 2026-10-19
- Phase : 3

## Contexte
F11 (§7.2, Annexe E) décrit un Comité : analystes, défenseur et contradicteur, gestionnaire,
contrôleur de risque, puis le moteur de politique. Le §6.1 prévoit qu'un agent s'enregistre comme un
plugin (`kind: agent`). R1 interdit qu'un modèle produise un chiffre décisionnel, R5 qu'un contenu
externe donne des instructions, R4 impose un arrêt prioritaire et R11 un journal de chaque décision.

Faits relevés le 19/10/2026 :

- **LangGraph 1.2.16** (installé) : `langgraph.types.Send` lance un même nœud plusieurs fois en
  parallèle avec des états distincts, puis le graphe agrège les résultats. La documentation est
  relue en détail avant le code (sous-graphes, réducteurs d'état).
- **Registre** : il n'accepte aujourd'hui que des transports MCP, et `Runtime` exige `mcp-stdio`.
- **Configuration** : `config/risk_limits.paper.yaml` est à `A_DEFINIR`. L'Annexe C.3 a déjà le type
  d'événement `DECISION`.

## Options
1. Code du Comité dans l'orchestrateur : rien à enregistrer, mais c'est contraire au §6.1.
2. Serveur MCP : un sous-processus pour un graphe qui appelle lui-même des modèles et des outils.
3. **Sous-graphe enregistré** (`kind: agent`), avec un transport `in-process` ajouté au registre.

## Décision
Option 3.

- **Intégration (D22)** :
  - manifeste `plugins/finance_committee/plugin.yaml` en `kind: agent`, avec le transport
    `in-process` réservé aux agents ;
  - moteur générique dans `core/committee/`, fiches de rôle dans
    `domain_packs/finance/prompts/committee/` (Annexe E), boîtes à outils dans
    `domain_packs/finance/committee.yaml` ;
  - paramètres dans `config/committee.yaml` : tours de débat et niveau de modèle par rôle.
- **Déclenchement (D15)** : le routage classe en `mode: comite` une requête Finance qui demande une
  décision, et `cerveau ask --comite` le force. Une question de mesure reste traitée directement.
  Seul le pack Finance a un Comité en phase 3.
- **Déroulé** :
  1. **Analystes en parallèle (D16)** : technique, actualités et macro, portefeuille.
     - Ils sont lancés par `Send`. Leurs sorties sont triées par rôle, pour un résultat
       indépendant de l'ordre d'arrivée.
     - Les analystes fondamental et sentiment, qui n'ont pas de source, sont écrits mais inactifs.
       C'est un écart aux quatre analystes de la spec : un analyste sans données coûterait un appel
       pour rien. Le sentiment tiré des actualités est une opinion (R12), qui reste chez l'analyste
       actualités.
  2. **Débat** : défenseur et contradicteur, sur `max_debate_rounds` tours (2, D17), sans outil.
  3. **Gestionnaire** (modèle `deep`) : décision proposée, confiance et horizon en catégories,
     conditions d'invalidation, désaccords non résolus.
  4. **Contrôleur de risque** : il dispose de `risk_report` (stress) et des limites du paper.
  5. **Moteur de politique** : inchangé (D20). La sortie est une « analyse » en N0, une
     « proposition non exécutée » en N1, et la classe `FINANCIERE` reste refusée.

  Les rôles autres que le gestionnaire utilisent le niveau `standard`.
- **Règles vérifiées par le code** :
  - **Schémas** : chaque sortie est validée par un schéma Pydantic, avec une seule nouvelle
    tentative accompagnée de l'erreur. Au second échec, le Comité conclut « pas de décision »
    (échec fermé).
  - **Constats** : chaque constat d'analyste cite un appel d'outil de la séance. Chaque argument
    cite un constat qui existe.
  - **Arguments** : le gestionnaire retient ou écarte chaque argument, avec une raison. Un argument
    ignoré invalide sa sortie.
  - **R1** : tout nombre passe le vérificateur de la phase 2. Un seuil d'invalidation chiffré vient
    d'une sortie d'outil.
  - **Verdict du contrôleur (D21)** : il est d'abord calculé par le code. Une limite dépassée ou à
    `A_DEFINIR` donne `BLOQUER` : c'est le cas actuel (R7). Le modèle peut durcir ce verdict,
    jamais l'assouplir.
  - **R5** : aucun rôle n'a d'outil d'action, et le web n'arrive que par le lecteur.
  - **R4** : le kill switch est vérifié avant chaque appel de modèle et entre les rôles.
- **Journal (D19, R11)** :
  - chaque séance a un `committee_record_id`, que l'intention d'ordre reprendra en phase 4 ;
  - chaque rôle produit une entrée `DECISION` : rôle, tour, modèle, validité du schéma, constats
    cités et empreinte SHA-256 de la sortie ;
  - le texte complet, pseudonymisé, va dans `var/finance/committee/<id>.json` ;
  - `cerveau committee show <id>` relit une séance et vérifie les empreintes.
- **Budget (D18)** : une section `per_committee` de `config/budgets.yaml` fixe les jetons, les
  secondes et les appels d'outil. Elle reste `A_DEFINIR`, ce qui refuse toute séance réelle. En cas
  de dépassement, la séance s'arrête et elle est enregistrée comme incomplète.

## Conséquences
- **Réponse** : le format du §7.3, avec la décision proposée, la confiance, l'horizon, les
  conditions d'invalidation, les désaccords, le verdict du contrôleur, l'identifiant de séance et
  la mention R16.
- **Coût** : une dizaine d'appels de modèle par séance. Hors ligne, les modèles sont scriptés ; en
  réel, il faut le budget et l'accord de Lucas pour chaque campagne.
- **Plus tard** : la confiance et l'horizon sont enregistrés dès maintenant pour une calibration
  (backlog). Le moteur est générique : les Comités des autres packs viendront avec leurs fiches.
- **Tests** :
  - schéma invalide, argument sans constat, argument ignoré ;
  - limite inconnue, budget dépassé, kill switch entre deux rôles ;
  - ordre déterministe des analystes ;
  - journal vérifié par `cerveau audit verify` ;
  - red team `injection_comite` : verdict jamais assoupli.
