# ADR-023 — Horloge et chiffres gelés des évals du pack Finance

- Statut : **proposé** (les chiffres gelés du golden set Finance attendent la validation de Lucas
  avant le gel, R9 ; plan de phase 2, D17)
- Date : 2026-10-18
- Phase : 2

## Contexte
Les évals hors ligne de la phase 1 datent chaque cas de `FIXTURE_NOW` (18 octobre 2026, 12 h UTC) :
les pages des fixtures n'ont pas d'âge réel. Le pack Finance ajoute des outils qui lisent une base
point-in-time (R10) : `tests/fixtures/finance/reference/`, générée à `REFERENCE_FETCHED_AT`
(18 octobre 2026, 12 h UTC), dont les scores de qualité sont écrits juste après. Un outil qui lit
la base à `FIXTURE_NOW` ne voit pas ces scores et rapporte des données manquantes. Le golden set
Finance (60 cas) doit par ailleurs dire quel chiffre exact l'outil calcule, sans qu'aucun modèle
le produise (R1), et le juge doit pouvoir noter l'exactitude d'un chiffre sans le recalculer.

## Décision
- **Horloge des évals Finance** : un cas qui appelle un outil finance est daté de `FINANCE_NOW =
  REFERENCE_READ_AT = REFERENCE_FETCHED_AT + 1 h` (18 octobre 2026, 13 h UTC,
  `core/finance/fixtures.py`, `core/evals/offline.py`). Les autres cas gardent `FIXTURE_NOW`.
- **Chiffres gelés** : chaque cas porte, dans `expect.figures`, l'outil, l'identifiant du chiffre et
  son affichage exact tels que les vrais serveurs MCP finance les calculent sur la base de
  référence. Le contrôle compare l'affichage recalculé à l'affichage gelé après normalisation NFKC :
  un écart d'un centime fait échouer le cas. La réponse doit contenir la partie numérique.
- **Mesure réelle** : la requête garde l'horloge réelle (budgets du jour) ; les outils
  finance lisent toujours la base de référence à sa propre date. Une question Finance du golden set
  nomme donc ses dates (« depuis lundi (12 octobre 2026) »).
- **Appel en échec** : un appel demandé par le planificateur qui échoue (fonction bloquée, rejeu
  strict) compte comme appelé pour le contrôle « outil appelé » ; son erreur devient une limite
  rapportée (« Limite signalée par <outil> : … »), comme les avertissements et les mesures
  indisponibles, chacune une seule fois.
- **Juge par pack** : le juge reçoit les chiffres, avertissements et limites des outils comme
  références. Chaque pack a sa grille (`domain_packs/<pack>/prompts/rubric.md`, version
  `rubric_<pack>@X.Y+sha256:<12 hex>` journalisée, R11) et son seuil (`config/evals.yaml` :
  `generaliste_golden_min_score` 0,80, D6 ; `finance_golden_min_score` 0,85, D17).
- **Rôle du pack** : la mention R16 du rôle Finance (`prompts/role.md`) est reformulée pour ne pas
  reproduire mot pour mot l'avis que les outils renvoient (`notice`) : sinon le contrôle de fuite du
  prompt système signalait toute réponse qui recopie l'avis de l'outil.

## Conséquences
- Les cas hors ligne Finance sont reproductibles et gratuits ; toute modification d'un calcul qui
  change un affichage fait échouer au moins un cas (R9 : on ne retouche pas le cas, on justifie).
- Les chiffres gelés dépendent de la base de référence : la régénérer (`generate.py`) impose de
  revalider le golden set avec Lucas.
- En mesure réelle, les chiffres dépendent des arguments que le planificateur passe aux outils
  (méthode, horizon, date de comparaison) : un argument différent donne un autre chiffre et le cas
  échoue. La campagne réelle le mesure ; elle n'est lancée qu'avec l'accord de Lucas (D8).
- Tests : `tests/test_evals.py` (golden Finance, grille Finance, appel en échec, limites),
  `tests/test_cli_ask_eval.py`.

## Options écartées
- Dater tous les cas de `REFERENCE_READ_AT` : les fixtures web de la phase 1 et leurs dates de
  lecture changeraient sans raison.
- Comparer les chiffres avec une tolérance : un chiffre recopié doit être celui de l'outil (R1) ;
  la tolérance D11 ne vaut que pour l'oracle indépendant des tests de risque.
- Faire recalculer les chiffres par le juge : un modèle ne produit aucun chiffre décisionnel (R1).
