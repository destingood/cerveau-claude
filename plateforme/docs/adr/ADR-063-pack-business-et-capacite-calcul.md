# ADR-063 — Pack Business & commerce : capacité CALCUL, évals hors ligne, remplacement de `pack-business-absent`

- Statut : **proposé** (élargissement de ce que la phase peut exécuter, décidé par Lucas le
  2026-10-29 ; à confirmer au compte rendu de P6)
- Date : 2026-10-29
- Phase : 6 (P6, décisions I1, I4, I5, I8, I11)

## Contexte
Le complément de plan P6 (validé « GO P6 », I1 à I12) ouvre le pack `business` au niveau N0 (plafond
N1) avec quatre plugins : `business_calc` (ADR-061), `entreprises` (ADR-062), `insee_stats` et
`web_research`. Le plan classe `biz_calc` en `CALCUL` et dit qu'« aucune règle de politique ne
change ». C'est faux : `core/policy/engine.py` n'accorde `CALCUL` qu'aux domaines `finance`
(ADR-022) et `code` (ADR-049). Sans élargissement, l'adaptateur MCP écarte `biz_calc` (« aucune
capacité CALCUL pour le domaine business ») et R1 ne peut plus être tenu : aucun outil ne calcule
une marge ni une TVA. Lucas a tranché le 2026-10-29 : accorder `CALCUL`.

Le pack s'évalue sans réseau, comme les packs cyber (ADR-057) et juridique (ADR-060). Le cas de
comportement `pack-business-absent` (groupe `pack_generaliste`, ADR-021) attend l'absence du pack :
il devient faux à son ouverture, et R9 interdit de le supprimer sans ADR (I11).

## Options
1. **Accorder `{LECTURE, CALCUL}` au domaine `business`** (retenue), sur le précédent d'ADR-049.
2. **Classer `biz_calc` en `LECTURE`** : la classe décrirait mal l'action et la politique ne verrait
   plus qu'un calcul est demandé.
3. **Laisser le modèle calculer** : contraire à R1.

## Décision
- `PHASE_DOMAIN_ACTION_CLASSES` accorde `{LECTURE, CALCUL}` à `business`, et rien d'autre.
  `COMMUNICATION_EXTERNE`, `ECRITURE_INTERNE`, `IRREVERSIBLE`, `FINANCIERE` et `EXECUTION_ISOLEE`
  restent refusées à tous les niveaux : un brouillon n'est jamais envoyé (I5). Le kill switch, puis
  la règle live, priment toujours ; une réponse de la Porte de risque pour un calcul est refusée.
- `biz_calc` calcule à partir des chiffres qu'on lui donne, sur une liste fermée d'opérations
  déterministes, sans réseau ni écriture (ADR-061).
- **Évals hors ligne.** Une fixture `business` de cas décrit les entreprises d'une fausse API
  Recherche d'entreprises et les jeux d'une fausse API Melodi ; les vrais serveurs `entreprises`,
  `insee_stats` et `business_calc` tournent derrière l'adaptateur MCP, via `httpx.MockTransport`,
  un faux DNS, un débit qui n'attend jamais, sans cache et sous le kill switch de l'éval
  (`core/evals/business_fixtures.py`). Chaque fausse entreprise porte un dirigeant, une date de
  naissance et une rue inventés : un canari qui fait échouer l'éval si une personne passe (I4).
- **Remplacement (I11).** `pack-business-absent` est retiré et remplacé, dans la même modification,
  par `pack-photographie-absent` (domaine `photographie`, sans pack ni projet de pack). Le plan
  proposait `pack-cuisine-absent`, qui existe déjà depuis ADR-046. Aucun pack n'étant plus prévu,
  la série s'arrête : B263 est clos.

## Conséquences
- Une question `CALCUL` routée vers `business` est traitée ; routée ailleurs, elle reste refusée
  (ADR-022). Tests : `tests/test_policy.py` (classes de la phase, refus de toute autre classe, kill
  switch, live, Porte de risque, raison du refus) et `tests/test_evals_business.py`.
- Révocable en retirant l'entrée `business` : `biz_calc` redevient refusé, le reste du pack lit.
- L'envoi réel d'un message reste hors de la phase 6 : aucun outil d'envoi n'existe.
