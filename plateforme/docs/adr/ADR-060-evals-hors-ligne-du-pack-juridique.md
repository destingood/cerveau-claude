# ADR-060 — Évals hors ligne du pack Juridique FR et remplacement du cas `pack-juridique-absent`

- Statut : **proposé** (R9 : retrait d'un cas existant ; l'utilisateur a choisi ce remplacement au plan de
  P5, H11 ; à valider au compte rendu de P5)
- Date : 2026-10-27
- Phase : 6 (P5)

## Contexte
Le pack Juridique et administratif FR (P5) lit l'API Légifrance par PISTE (`legifrance`, ADR-059)
et des pages officielles d'une liste fermée de sites (`web_research`, ADR-058). Ses évals hors
ligne (`make eval`, gratuites, sans réseau) doivent exercer le vrai serveur `legifrance`, ses
versions datées (H3), ses limites et ses erreurs, sans contacter PISTE, sans identifiants réels
(R6) et sans écrire sous `var/` du dépôt.

Le cas `pack-juridique-absent` (suite `behaviors`, groupe `pack_generaliste`) vérifiait qu'une
question de droit (« Quel est le délai de rétractation pour un achat en ligne ? ») retombait sur le
pack généraliste avec la note « « juridique_fr » n'existe pas encore ». Le manifeste du pack
(`domain_packs/juridique_fr/manifest.yaml`, statut `experimental`) rend sa prémisse fausse : il
échoue par construction, comme `pack-cyber-absent` avant lui (ADR-057).

## Options
- Évals : fixtures servies au vrai serveur (retenu) ; serveur simulé (ne teste ni le jeton OAuth,
  ni les versions, ni les plafonds) ; mesure réelle seulement (réseau, identifiants, coût).
- Cas : remplacer par un domaine sans pack prévu et reprendre la question dans le pack juridique
  (retenu, H11) ; modifier l'attente du cas (R9 le réserve à l'utilisateur) ; le retirer sans remplacement
  (le groupe tomberait sous les cinq cas exigés).

## Décision
- **Fixtures.** Un cas décrit les versions d'articles, les recherches et l'état de l'API
  (`legal:`, `core/evals/cases.py`). `core/evals/legifrance_fixtures.py` les sert au vrai serveur
  par un transport httpx factice (jeton OAuth, `getArticle`, `getArticleWithIdAndNum`, `search`) :
  aucune requête ne sort. L'API peut répondre 503, une taille au-delà du plafond ou un autre
  identifiant que celui demandé ; les identifiants PISTE sont des valeurs de test que seul le faux
  serveur accepte, cherchées aussi dans les messages aux modèles et le journal du run. La copie de
  la configuration du cas fixe l'environnement (`sandbox`, `production` ou `A_DEFINIR`) sans
  toucher `config/`. Les identifiants LEGIARTI et les textes des fixtures sont des données de test
  (« Texte de test : »), pas des reproductions de Légifrance.
- **Rédacteur scripté.** Hors ligne, la réponse juridique est écrite par `_from_legal`
  (`core/evals/offline.py`) à partir des seuls résultats des outils : identifiant, état et dates
  recopiés (R1), version qui ne couvre pas la date dite avec la version applicable (R10),
  avertissements de l'outil repris, aucun délai ni montant calculé (H8), « je ne sais pas » sans
  résultat (R12).
- **Cas.** `pack-juridique-absent` est remplacé, dans la même modification que le manifeste, par
  `pack-musique-absent` (domaine `musique`, sans pack ni projet de pack, absent de `DOMAINS`), avec
  la même attente. Ni le seuil du groupe (100 %), ni le minimum de cinq cas, ni les autres cas ne
  bougent. La question retirée rejoint les comportements du pack juridique
  (`juridique-pack-retractation-fiche`), avec une fiche de `service-public.gouv.fr` (site de la
  liste fermée) au lieu de la page d'un site d'exemple qui serait désormais écartée (H6) ; elle
  attend une réponse sourcée, la note « Pack « juridique_fr » expérimental » et la mention datée
  de Service Public.

## Conséquences
- Golden set de 32 cas, 11 comportements, red team `evals/redteam/injection_juridique_fr/`, tous
  hors ligne.
- Hors ligne, les refus R16 et H8 sont écrits par la route scriptée : qu'un modèle refuse un
  conseil personnalisé, un acte ou un calcul appliqué au cas réel ne se mesure qu'en réel. Le pack
  ne passe `actif` qu'après cette mesure, sur accord de l'utilisateur (H12 : aucune campagne en P5).
- Une fixture reproduit la forme de l'API décrite par la documentation PISTE lue le 2026-10-27 ;
  un écart avec les réponses réelles ne se voit qu'au premier appel réel (A_VERIFIER, backlog).
- Une page hors liste est écartée dès la recherche (`web_search` filtre ses résultats) : le cas du
  golden le vérifie par l'absence de l'hôte dans la réponse ; la redirection vers un hôte hors
  liste se mesure dans la red team.
- Les rapports d'évals passés citent encore `pack-juridique-absent` : mesures passées, inchangées.
- `pack-business-absent` tombera de la même façon à l'arrivée du pack business ; B263 reste ouvert.
- Si l'utilisateur refuse ce remplacement, il choisit l'attente du cas dans une modification dédiée.
