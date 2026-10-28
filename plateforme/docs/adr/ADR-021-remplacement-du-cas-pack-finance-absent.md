# ADR-021 — Remplacement du cas de comportement `pack-finance-absent`

- Statut : **proposé** (R9 : retrait d'un cas existant ; à valider par Lucas au compte rendu de
  phase)
- Date : 2026-10-18
- Phase : 2

## Contexte
Le cas `pack-finance-absent` (suite `behaviors`, groupe `pack_generaliste`,
`domain_packs/generaliste/evals/behaviors.yaml`) vérifiait qu'une question de finance, faute de
pack Finance, retombait sur le pack généraliste avec la note « « finance » n'existe pas encore ».
Le routeur de la phase 2 ouvre le pack Finance (plan de phase 2 validé D1–D21, commit 16,
`core/orchestrator/packs.py`) : la prémisse du cas devient fausse, et il échoue par construction.

R9 interdit de retoucher un cas pour faire passer une modification et ne permet d'en supprimer un
qu'avec un ADR ou l'accord de Lucas.

## Décision
- Le cas est retiré et remplacé, dans la même modification, par `pack-business-absent` : une
  question de gestion d'entreprise (domaine `business`, toujours sans pack), avec la même attente
  (réponse sourcée, note « « business » n'existe pas encore »). Ni le seuil du groupe (100 %), ni
  le minimum de cinq cas par groupe, ni les quatre autres cas ne bougent.
- Le repli sur le généraliste reste aussi couvert par le test
  `test_a_domain_without_a_pack_falls_back_to_generaliste` (`tests/test_orchestrator_finance.py`).
- La question de définition du cas retiré (« Qu'est-ce qu'un ETF ? ») rejoint les comportements du
  pack Finance (commit 18 du plan) : routée vers le pack Finance, elle répond sourcée et sans
  cette note.

## Conséquences
- Le groupe `pack_generaliste` garde 5 cas et la suite `behaviors` 59 ; le commit 18 en ajoute.
- Les rapports d'évals de la phase 1 citent encore `pack-finance-absent` : ce sont des mesures
  passées, ils ne changent pas.
- Si Lucas refuse ce remplacement, il choisit l'attente du cas (le retirer, le garder sous une autre
  question) dans une modification dédiée qu'il valide.

## Options écartées
- Modifier l'attente du cas : c'est retoucher un cas existant, ce que R9 réserve à Lucas.
- Retirer le cas sans le remplacer : le groupe tomberait sous les cinq cas exigés par
  `tests/test_evals.py`, ce qui revient à réduire la suite.
- Garder le pack Finance hors du routage : bloque les critères de la phase 2.
