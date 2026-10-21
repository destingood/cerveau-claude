# ADR-029 — Intention d'ordre : schéma strict, UUID v7 maison, rédacteur déterministe

- Statut : accepté (D7, D8 et D17 du plan de phase 4, validées par Lucas le 20/10/2026)
- Date : 2026-10-20
- Phase : 4

## Contexte
Le §10.8 et l'Annexe C.2 font de toute action financière une intention d'ordre structurée, qui
passe la politique puis la Porte de risque avant toute exécution. R1 interdit qu'un modèle produise
un chiffre décisionnel. R10 impose le point-in-time. B108 demande un rédacteur d'intentions.

Faits relevés le 20/10/2026 :

- **UUID v7** : Python 3.12 ne fournit que `uuid1`, `uuid3`, `uuid4` et `uuid5` ; `uuid7` arrive en
  3.14 ([docs.python.org/3.12/library/uuid](https://docs.python.org/3.12/library/uuid.html)). Le
  projet est en 3.12 (ADR-001).
- **C.2** ne prévoit que `committee_record_id` comme origine, alors que la phase 3 a aussi produit
  des stratégies `candidate` (ADR-027).

## Options
1. C.2 à la lettre : seules les décisions du Comité donnent des intentions.
2. Une dépendance pour l'UUID v7.
3. **C.2 étendu** d'une origine typée, avec un UUID v7 écrit et testé dans le projet.

## Décision
Option 3.

- **Paquet** `core/execution/`. Le schéma `OrderIntent` est Pydantic strict et figé.
  - `environment: Literal["paper"]` : un `live` est refusé par le schéma lui-même en phase 4.
  - `order_type` vaut `LIMIT` et `time_in_force` vaut `DAY`.
  - `quantity` est un entier > 0 ; `limit_price` est un `Decimal` > 0.
  - `price_source` et `sizing_source` citent l'identifiant de l'appel d'outil journalisé
    (`TOOL_CALL`) qui a produit le chiffre (R1).
  - `rationale` contient la thèse, le catalyseur, l'invalidation, l'horizon et une confiance dans
    [0, 1], tous obligatoires et bornés.
- **`intent_id`** : UUID v7 (RFC 9562, horodatage de 48 bits en millisecondes, version 7,
  variante 10), testé contre la RFC. Il sert aussi d'identifiant client de l'ordre (ADR-032).
- **Origine (D8)** : `origin {kind: strategy | committee, id}`. `committee_record_id` devient
  facultatif ; il est requis quand `kind` vaut `committee`.
- **Rédacteur `IntentDrafter`** (déterministe) :
  - il part d'ordres cibles calculés par le code (`target_orders` ou `rebalance.py`) ;
  - il prend le dernier cours connu à la décision (R10) ;
  - le prix limite vaut ce cours ± `limit_offset_pct`, arrondi au centime dans le sens prudent
    (vers le bas à l'achat, vers le haut à la vente) ; ce décalage ne peut dépasser la bande de prix ;
  - le modèle ne fournit que les textes de justification.
- **Paramètre (D17)** : `limit_offset_pct` dans le nouveau `config/execution.yaml`, fixé à 0,5 %
  par Lucas le 20/10/2026.
- **Sources (D7)** :
  1. une stratégie `candidate`, rejouée chaque jour avec le code du backtest. Sa fiche gagne
     `invalidation` et `horizon_jours`, hors des empreintes du code et de la grille ;
  2. une décision « agir » du Comité sur une proposition de rééquilibrage. `ManagerDecision` gagne
     `catalyseur`, obligatoire pour « agir ». Ce changement de prompt relance les évals (R9).

## Conséquences
- Toute intention est rejouable : son empreinte SHA-256 va au journal, ses montants au carnet.
- Un ordre au marché, un ordre live ou une quantité fractionnaire sont impossibles à construire.
- **Tests** : vecteurs de la RFC 9562, monotonie des UUID générés dans une même milliseconde,
  rejets du schéma, prix limite toujours dans la bande, rédacteur sans aucun chiffre venu du modèle.

## Mise en œuvre (21/10/2026)
- **Catalyseur du Comité** : `ManagerDecision.catalyseur {texte, constats}` est facultatif dans le
  schéma ; ses constats doivent exister, et son texte passe les contrôles R1 et R5 des autres champs.
  Une décision « agir » sans catalyseur n'est pas réparée : elle bloque. Le code ajoute la raison
  `NO_CATALYST` au verdict, qui devient BLOQUER quelles que soient les limites, le contrôleur la voit
  sans pouvoir la lever, et aucune intention d'ordre n'en naît.
- **Pourquoi bloquer plutôt que réparer** : une réparation exigerait un catalyseur dès la première
  réponse. Or le cas golden gelé `comite-agir-taille-inconnue` scripte un « agir » sans catalyseur ;
  il aurait échoué, et R9 interdit de retoucher un golden pour faire passer un commit. Le blocage
  garde ce cas vert (son verdict était déjà BLOQUER) et tient la règle en échec fermé. Passer à la
  réparation, une fois ce cas corrigé dans une PR validée par Lucas, est inscrit au backlog (B174).
- La fiche du gestionnaire demande le catalyseur : la version du Comité change et les évals sont
  relancées (R9). Deux cas de comportement s'ajoutent, avec et sans catalyseur.
