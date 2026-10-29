# ADR-050 — Remplacement du cas de comportement `pack-code-absent`

- Statut : **proposé** (R9 : retrait d'un cas existant ; à valider par l'utilisateur au compte rendu de
  P3a ; la règle commune du backlog B263 reste à trancher)
- Date : 2026-10-22
- Phase : 6 (P3a)

## Contexte
Le cas `pack-code-absent` (suite `behaviors`, groupe `pack_generaliste`,
`domain_packs/generaliste/evals/behaviors.yaml`) vérifiait qu'une question de programmation
(« À quoi sert une liste en compréhension en Python ? »), faute de pack Code, retombait sur le pack
généraliste avec la note « « code » n'existe pas encore ». P3a ajoute le manifeste du pack Code
(`domain_packs/code/manifest.yaml`, statut `experimental`) : le socle des packs (ADR-043) le
découvre et le routeur l'ouvre. La prémisse du cas devient fausse, et il échoue par construction.

ADR-046 a annoncé ce cas et laissé le choix entre un ADR par pack et une règle commune (B263). L'utilisateur
n'a pas tranché B263 : ce remplacement suit le précédent, un ADR par pack, et le signale.

## Décision
- Le cas est retiré et remplacé, dans la même modification que le manifeste du pack, par
  `pack-jardinage-absent` : une question de jardinage (domaine `jardinage`, sans pack ni projet de
  pack), avec la même attente (réponse sourcée, note « « jardinage » n'existe pas encore »). Ni le
  seuil du groupe (100 %), ni le minimum de cinq cas, ni les quatre autres cas ne bougent.
- La question du cas retiré rejoint les comportements du pack Code (`code-pack-question-generale`,
  `domain_packs/code/evals/behaviors.yaml`), avec la même page. À la différence d'ADR-046, elle
  n'est pas routée vers le nouveau pack : le pack Code lit les dépôts de l'utilisateur et n'a aucun outil
  web, donc une question générale de programmation, sans dépôt, reste au généraliste. Le cas
  attend une réponse sourcée, sans la note d'absence ni la note « Pack « code » expérimental ».
- Le prompt du routeur (`core/orchestrator/prompts/route.md`) définit désormais « code » dans ce
  sens. Hors ligne, la route est scriptée ; en réel, le cas mesure la décision du routeur.

## Conséquences
- Le groupe `pack_generaliste` garde 5 cas ; le groupe `pack_code` en ajoute 6.
- Les rapports d'évals passés citent encore `pack-code-absent` : mesures passées, inchangées.
- `pack-cyber-absent` et `pack-business-absent` tomberont de la même façon (P4, P5) : B263 reste à
  trancher avant.
- Si l'utilisateur refuse ce remplacement, il choisit l'attente du cas dans une modification dédiée.

## Options écartées
- Router la question vers le pack Code (comme ADR-046) : le pack n'a aucune source pour y répondre
  et donnerait « je ne sais pas » à une question publique simple.
- Modifier l'attente du cas existant : c'est retoucher un cas, ce que R9 réserve à l'utilisateur.
- Retirer le cas sans le remplacer : le groupe tomberait sous les cinq cas exigés.
