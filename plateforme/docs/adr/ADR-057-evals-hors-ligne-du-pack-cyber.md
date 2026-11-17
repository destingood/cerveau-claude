# ADR-057 — Évals hors ligne du pack Cyber et remplacement du cas `pack-cyber-absent`

- Statut : **proposé** (R9 : retrait d'un cas existant ; à valider par l'utilisateur au compte rendu de
  P4 ; la règle commune du backlog B263 reste à trancher)
- Date : 2026-10-27
- Phase : 6 (P4)

## Contexte
Le pack Cyber (P4) lit le NVD, le catalogue KEV de la CISA, l'EPSS du FIRST et un index ATT&CK
local. Ses évals hors ligne (`make eval`, gratuites, sans réseau) doivent exercer les vrais serveurs
`cyber_cve` et `cyber_attack`, leurs limites et leurs refus, sans jamais contacter ces services ni
écrire sous `var/` du dépôt (règle des tests), et sans que l'utilisateur ait lancé `cerveau cyber
attack-fetch`.

Le cas `pack-cyber-absent` (suite `behaviors`, groupe `pack_generaliste`) vérifiait qu'une question
de sécurité défensive (« Qu'est-ce qu'un gestionnaire de mots de passe ? ») retombait sur le pack
généraliste avec la note « « cyber » n'existe pas encore ». Le manifeste du pack
(`domain_packs/cyber/manifest.yaml`, statut `experimental`) rend sa prémisse fausse : il échoue par
construction. ADR-050 l'avait annoncé ; l'utilisateur a choisi au plan de P4 (G11) le remplacement par ADR,
B263 restant ouvert.

## Options
- Évals : fixtures servies aux vrais serveurs (retenu) ; serveurs simulés (ne testent ni les
  schémas, ni les plafonds, ni l'empreinte de l'index) ; mesure réelle seulement (payante, réseau).
- Cas : remplacer par un domaine sans pack prévu et reprendre la question dans le pack Cyber
  (retenu) ; modifier l'attente du cas (R9 le réserve à l'utilisateur) ; le retirer sans remplacement (le
  groupe tomberait sous les cinq cas exigés).

## Décision
- **Fixtures.** Un cas décrit son NVD, son KEV, son EPSS et l'état de l'index ATT&CK (`cyber:`,
  `core/evals/cases.py`). `core/evals/cyber_fixtures.py` les sert aux vrais serveurs par un
  transport httpx factice et un résolveur fixe (aucune requête ne sort) ; une source peut répondre
  503 ou une taille au-delà du plafond ; la clé du NVD, quand un cas en veut une, est une valeur de
  test que seul le faux NVD accepte, et le cas la cherche aussi dans les messages aux modèles et
  dans le journal du run. L'index ATT&CK est construit dans le dossier temporaire du cas à partir
  d'un bundle de synthèse (`core/evals/attack_sample.py`, commit fictif) : présent, absent ou
  d'une autre empreinte ; la copie de la configuration remet le marqueur `A_VERIFIER` si l'utilisateur a
  déjà inscrit l'empreinte du vrai bundle.
- **Rédacteur scripté.** Hors ligne, la réponse cyber est écrite par `_from_cyber`
  (`core/evals/offline.py`) à partir des seuls résultats des outils : scores, dates et identifiants
  recopiés (R1), aucun lien des outils, source non lue dite, « je ne sais pas » sans résultat (R12).
  Il mesure les défenses déterministes, pas la qualité d'un modèle (mesure réelle sur accord).
- **Cas.** `pack-cyber-absent` est remplacé, dans la même modification que le manifeste, par
  `pack-astronomie-absent` (domaine `astronomie`, sans pack ni projet de pack, absent de `DOMAINS`),
  avec la même attente. Ni le seuil du groupe (100 %), ni le minimum de cinq cas, ni les quatre
  autres cas ne bougent. La question retirée rejoint les comportements du pack Cyber
  (`cyber-pack-question-generale`) avec la même page ; comme pour ADR-046, elle est routée vers le
  nouveau pack, qui a `web_search` et `web_read`, et attend une réponse sourcée et la note « Pack
  « cyber » expérimental ».

## Conséquences
- Golden set de 31 cas, 10 comportements, 12 cas de red team (`injection_cyber`), tous hors ligne.
- Hors ligne, les refus R15 et R16 sont écrits par la route scriptée, et l'identifiant piégé
  (`cyber-rt-identifiant-piege`) ne mesure que le refus du schéma : qu'un modèle refuse un usage
  offensif ou un conseil à un tiers, et n'invente rien sans résultat, ne se mesure qu'en réel. Le
  pack ne passe au statut `actif` qu'après cette mesure réelle, sur accord de l'utilisateur.
- Une fixture reproduit la forme des API observée le 2026-10-27 ; un changement de forme côté NVD,
  CISA ou FIRST ne se voit qu'en mesure réelle (backlog).
- Les rapports d'évals passés citent encore `pack-cyber-absent` : mesures passées, inchangées.
- En réel, le routeur ne propose que les domaines de `DOMAINS` : la question d'astronomie, comme
  celles du jardinage et de la cuisine, mesure s'il nomme quand même un domaine sans pack.
- `pack-business-absent` tombera de la même façon (P5) : B263 reste à trancher avant.
- Si l'utilisateur refuse ce remplacement, il choisit l'attente du cas dans une modification dédiée.
