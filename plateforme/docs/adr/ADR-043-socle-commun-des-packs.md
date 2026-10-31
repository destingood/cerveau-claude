# ADR-043 — Socle commun des packs de domaine

- Statut : proposé (principes validés par l'utilisateur le 21/10/2026 : plan de phase 6 §3, D1 à D4 ;
  détails d'implémentation ci-dessous à valider par l'utilisateur)
- Date : 2026-10-21
- Phase : 6

## Contexte
La phase 6 ouvre les packs P2 à P6 (§9.2). Jusqu'ici, chaque pack est écrit en dur dans quatre
modules : la liste `PACK_IDS` (`core/orchestrator/packs.py`), les golden sets, comportements et red
teams (`core/evals/cases.py`), les seuils (`core/evals/judge.py`) et leurs planchers
(`core/config/loader.py`). Un oubli ne se voit qu'à l'exécution : un pack sans domaine dans
`config/autonomy.yaml` lève une `KeyError` au routage. L'anti-SSRF et robots.txt vivent dans
`plugins/web_research/`, alors que `scholarly` et `feeds` lisent aussi le réseau (ADR-006).
Aucun pack n'a été mesuré en campagne réelle (budgets `A_DEFINIR`, R7) ; §9.3 : un pack ne passe
« actif » qu'au-dessus de son seuil ; R12 : dire ce qui n'est pas mesuré.

## Options
1. **Constantes par pack** (phases 1 à 5) : simple, mais quatre modules à toucher par pack et des
   erreurs révélées à l'exécution.
2. **Découverte par convention de dossier, bornée par `DOMAINS` et contrôlée au démarrage**
   (retenue) : un pack s'ajoute par son dossier, son domaine et son seuil.
3. **Registre de packs en base** : sort la décision du dépôt relu ; rien ne le justifie.

## Décision
- **Découverte** : `load_packs()` lit `domain_packs/<id>/manifest.yaml` pour chaque `id` de
  `DOMAINS`, dans l'ordre du §9.2. Un dossier sans manifeste est ignoré ; un manifeste invalide
  bloque le démarrage. `generaliste` reste obligatoire (repli).
- **Statut** : `statut` est obligatoire (`experimental` | `actif`). Claude Code n'écrit que
  `experimental` ; seul l'utilisateur passe un pack à `actif`, après une campagne réelle (D2). Un test
  exige `experimental` pour chaque pack du dépôt : le passage de l'utilisateur le modifie aussi.
- **Dossier unique** : l'orchestrateur, les prompts et `cerveau config check` lisent le même
  dossier de packs (`PACKS_DIR`, ou celui passé en paramètre).
- **Marquage** : la réponse d'un pack expérimental porte le signalement « Pack « <id> »
  expérimental : sa qualité n'est pas encore mesurée. », sans chiffre pour ne pas déclencher le
  contrôle R1. Il vaut aussi pour `generaliste` et `finance`, jamais mesurés en réel (D2).
- **Cohérence** : un pack découvert sans domaine dans `config/autonomy.yaml`, sans seuil
  `<id>_golden_min_score` dans `config/evals.yaml` ou avec un seuil marqueur (`A_DEFINIR`,
  `A_VERIFIER`) bloque le démarrage et `cerveau config check`, qui affiche par pack le statut,
  le niveau écrit et le niveau effectif. `golden_threshold` refuse aussi un seuil marqueur.
- **Plafond** : le chargeur refuse un domaine hors `DOMAINS` et un `max_level` au-dessus de
  l'autonomie maximale initiale du §9.2 (generaliste N1, finance N4 par promotion, recherche N1,
  code N2, cyber N1, juridique_fr N1, business N1). Les planchers et plafonds sont figés
  (`MappingProxyType`).
- **Niveau d'entrée** : un domaine sans règle de promotion signée (`autonomy.promotion`) ne peut
  pas dépasser son niveau d'entrée (`UNSIGNED_LEVELS` : generaliste N1, hérité de la phase 1 ;
  tout autre domaine N0, D3), même si `level` et `max_level` le permettent. Seul un ADR élève
  ce niveau ; le kill switch ramène tout domaine à N0 (R4).
- **Seuils** : un plancher par pack dans le code (0,80 ; 0,85 pour juridique_fr, D4) ;
  `judge.py` lit `<id>_golden_min_score`. Un test vérifie qu'à chaque champ de seuil correspond
  un plancher.
- **Évals** : `cases.py` découvre `domain_packs/<id>/evals/golden.jsonl`, `behaviors.yaml` et
  `evals/redteam/injection_<id>/`, tous trois obligatoires (la red team du généraliste est celle
  de la suite commune). Les cas existants ne changent pas (R9).
- **Réseau** : `guard.py` et `robots.py` passent dans `core/net/`, sans changement de comportement.
- **Agent de pack** : `agent: {plugin, mode}` remplace `comite`. Le Comité Finance devient
  `mode: comite` (ADR-028 inchangé) ; la recherche approfondie ne part que sur demande explicite
  (`--approfondi`, D14, ADR-045). `load_agent` refuse, avant tout import, un agent dont le
  `domain` du `plugin.yaml` n'est pas l'`id` du pack qui l'appelle.
- **Revue** : `risk-gate-auditor` le 22/10/2026 (aucun bloquant ; les constats I1, I2 et M1 à M6
  sont traités ci-dessus ; les liens symboliques de `domain_packs/` vont au backlog).

## Conséquences
- Un pack s'ajoute sans toucher au code, hormis son champ de seuil et son plancher, voulus
  explicites (R9).
- Plus strict : la configuration ne peut plus élever un `max_level` au-delà du §9.2 sans ADR.
- Chaque réponse porte une ligne de plus, y compris en généraliste et en finance, jusqu'au
  passage à `actif`.
- Le passage reste manuel ; la mesure est la campagne réelle (`cerveau eval --live`), lancée
  seulement avec l'accord de l'utilisateur.
- Réversible : retirer un manifeste retire le pack.
