# ADR-046 — Remplacement du cas de comportement `pack-recherche-absent`

- Statut : **proposé** (R9 : retrait d'un cas existant ; à valider par Lucas au compte rendu de
  phase)
- Date : 2026-10-22
- Phase : 6

## Contexte
Le cas `pack-recherche-absent` (suite `behaviors`, groupe `pack_generaliste`,
`domain_packs/generaliste/evals/behaviors.yaml`) vérifiait qu'une question de méthode de recherche
(« Qu'est-ce qu'une revue systématique de la littérature ? »), faute de pack Recherche, retombait
sur le pack généraliste avec la note « « recherche » n'existe pas encore ». La phase 6 ajoute le
manifeste du pack Recherche (plan de phase 6 validé D1–D24, `domain_packs/recherche/manifest.yaml`,
statut `experimental`) : le socle des packs (ADR-043) le découvre et le routeur l'ouvre. La
prémisse du cas devient fausse, et il échoue par construction.

R9 interdit de retoucher un cas pour faire passer une modification et ne permet d'en supprimer un
qu'avec un ADR ou l'accord de Lucas. ADR-021 a traité le même cas pour le pack Finance.

## Décision
- Le cas est retiré et remplacé, dans la même modification que le manifeste du pack, par
  `pack-cuisine-absent` : une question culinaire (domaine `cuisine`, sans pack ni projet de pack),
  avec la même attente (réponse sourcée, note « « cuisine » n'existe pas encore »). Ni le seuil du
  groupe (100 %), ni le minimum de cinq cas par groupe, ni les quatre autres cas ne bougent.
- La question du cas retiré rejoint les comportements du pack Recherche
  (`rech-pack-revue-systematique`, `domain_packs/recherche/evals/behaviors.yaml`) : routée vers le
  pack, elle répond sourcée, avec la note « Pack « recherche » expérimental » et sans la note
  d'absence.
- Le domaine `cuisine` est choisi parce qu'aucun pack de P3 à P6 (D19–D24) ne le couvre : le cas
  ne devra pas être remplacé à nouveau à l'ouverture d'un prochain pack.

## Conséquences
- Le groupe `pack_generaliste` garde 5 cas ; le groupe `pack_recherche` en ajoute 8.
- Les rapports d'évals des phases précédentes citent encore `pack-recherche-absent` : ce sont des
  mesures passées, ils ne changent pas.
- Les cas `pack-juridique-absent`, `pack-code-absent`, `pack-cyber-absent` et
  `pack-business-absent` tomberont de la même façon à l'ouverture des packs correspondants : chaque
  pack apporte alors son ADR de remplacement, ou Lucas décide d'une règle commune.
- Si Lucas refuse ce remplacement, il choisit l'attente du cas dans une modification dédiée qu'il
  valide.

## Options écartées
- Modifier l'attente du cas : c'est retoucher un cas existant, ce que R9 réserve à Lucas.
- Retirer le cas sans le remplacer : le groupe tomberait sous les cinq cas exigés par
  `tests/test_evals.py`, ce qui revient à réduire la suite.
- Remplacer par un domaine prévu en P3 à P6 : le cas tomberait à la phase suivante.
- Garder le pack Recherche hors du routage : bloque les critères de la phase 6.
