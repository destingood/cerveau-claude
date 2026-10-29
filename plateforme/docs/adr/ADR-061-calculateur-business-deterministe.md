# ADR-061 — Plugin `business_calc` : calculateur business déterministe

- Statut : **proposé** (à valider par l'utilisateur au compte rendu de P6)
- Date : 2026-10-29
- Phase : 6 (P6, décisions I1, I2, I7)

## Contexte
Le pack Business & commerce répond à des questions chiffrées : marge, prix de vente, TVA, seuil de
rentabilité, coût d'acquisition et valeur client, variation, croissance annuelle. R1 interdit
qu'un modèle produise ces chiffres ; chacun doit sortir d'un outil qui le calcule et le nomme.
R13 borne le pack à 3 à 5 outils (I1 : cinq outils, dont un seul calculateur, I2). Les taux de TVA
sont des valeurs juridiques qui changent : R7 interdit de les écrire en dur. Faits vérifiés le
2026-10-29 : taux normal de 20 % (CGI, art. 278, Légifrance, version en vigueur depuis le
01/01/2014) ; les règles de TVA passent dans le code des impositions sur les biens et services
(CIBS) le 01/01/2027 (BOI-RES-TVA-000253). Les taux de 10 %, 5,5 % et 2,1 % (service-public.fr,
F23567) n'ont pas pu être relus dans Légifrance le même jour.

## Options
1. **Laisser le modèle calculer, puis vérifier.** Rien à écrire ; contraire à R1, aucune trace de
   la formule ni de l'arrondi.
2. **Un outil par opération.** Schémas simples ; sept outils dépassent la borne de R13.
3. **Un outil `biz_calc`, opération choisie dans une liste fermée** (retenue) : union discriminée
   Pydantic sur `operation`, une formule par opération, aucune dépendance nouvelle (Pydantic et
   mcp déjà présents, MIT).

## Décision
Option 3, dans `core/business/calc.py` (calcul pur) et `plugins/business_calc/` (serveur MCP) :
- **Opérations fermées** : `marge`, `prix_de_vente`, `tva`, `seuil_rentabilite`, `cac_ltv`,
  `variation`, `tcac`. Toute autre valeur, tout champ inconnu, toute valeur non finie ou hors borne
  est refusée par le schéma avant le calcul ; un taux de marque d'au moins 1, des charges variables
  d'au moins le chiffre d'affaires, une marge brute au-delà de 100 % ou un taux de marge au-delà
  de 10 (1 000 %, signe d'un pourcentage donné pour une fraction) sont refusés. Un résultat hors
  des bornes affichables est refusé avec un message, jamais tronqué.
- **Conventions signalées** : coefficient inférieur à 1 (prix sous le coût), TTC qu'aucun HT ne
  redonne au centime, TCAC sur moins d'un an (extrapolé) ; le coefficient est HT/HT.
- **Calcul décimal** (`Decimal`, contexte local à 28 chiffres significatifs), montants arrondis au centime au demi
  supérieur pour la TVA ; l'année commerciale de 360 jours date le point mort.
- **Sortie traçable (R1)** : chaque nombre est une `Figure` (identifiant, valeur, affichage
  français, unité) ; la réponse porte les entrées, les résultats, les formules, les conventions et,
  pour la TVA, la source du taux. Aucun nombre libre.
- **TVA (I7, R7, R10)** : taux lus dans `config/business.yaml`, chacun avec son article ; un taux
  `A_VERIFIER` est refusé avec son chemin dans la configuration. La table porte une date de fin de
  validité (`2026-12-31`) : après elle, le calcul est refusé jusqu'à relecture des taux dans le
  CIBS. Les autres opérations ne lisent aucune configuration.
- **Annotations** : lecture seule, idempotent, non destructif, monde fermé ; aucun réseau.

## Conséquences
- Plus simple : une réponse business cite un outil pour chaque chiffre ; les propriétés
  (HT + TVA = TTC, prix rebâti par le coefficient, formule du TCAC) sont testées par Hypothesis.
- Plus difficile : seul le taux normal est utilisable tant que l'utilisateur n'a pas relu les trois autres
  dans le CGI (backlog) ; la table doit être reprise avant le 01/01/2027 (CIBS).
- Réversible : ajouter une opération est un ajout à l'union, avec ses tests et ses évals (R8, R9).
- Hors périmètre : règles d'arrondi par ligne de facture, régimes particuliers (DOM, Corse,
  franchise en base), devises, date d'opération de la TVA (`valid_from`), unité de
  `variation` et `tcac` ; au backlog (revue quant du 2026-10-29).
