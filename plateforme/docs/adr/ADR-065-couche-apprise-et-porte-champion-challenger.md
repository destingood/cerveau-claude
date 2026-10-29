# ADR-065 — Couche apprise, noyau verrouillé et porte champion / challenger

- Statut : proposé
- Date : 2026-10-29
- Phase : 7 (lot 7.2 du plan validé le 2026-10-29)

## Contexte
Lucas a décidé le 18/10/2026 une auto-amélioration « tout automatique, avec le test avant chaque
mise en ligne et le noyau verrouillé » (ADR-011). Il faut donc :
- un endroit borné où CERVEAU écrit ce qu'il apprend ;
- un noyau que l'apprentissage ne touche jamais ;
- une porte déterministe avant toute mise en service.

Contraintes :
- R5 : une leçon tirée d'un retour est du contenu externe ;
- R7 : seuils inconnus = `A_DEFINIR` ;
- R9 : jamais baisser un seuil ni toucher un golden ;
- R11 : chaque verdict est journalisé.

Risque principal : la loi de Goodhart. Une couche optimisée sur le golden finit par réussir le
golden sans mieux répondre ; d'où un jeu tenu à l'écart que l'apprentissage ne voit jamais.

## Options
1. **Fichiers Markdown en liste fermée dans `learned/`, ajoutés au rôle du pack, porte sur deux
   rapports d'évals** (retenue) : relisible dans git (D3), sans dépendance nouvelle.
2. **Mémoire vectorielle injectée par similarité** : contenu variable d'une requête à l'autre,
   non reproductible, difficile à évaluer.
3. **Réglage fin d'un modèle** : coûteux, opaque, irréversible à l'échelle d'une requête ; hors
   périmètre de la phase.

## Décision
- `core/learning/layer.py` :
  - liste fermée `learned/<pack>/{lessons,examples}.md` pour les packs déclarés ;
  - refus de tout autre chemin, d'un lien symbolique ou d'une jonction (`LockedCoreError`) ;
  - section de 1 à 4 000 caractères, imprimables, sans `{{ }}`, sans signal d'injection (R5) ;
  - écriture atomique.
- `PromptSet.load` ajoute les sections au rôle du pack, sous un titre qui les dit non vérifiées,
  et les inclut dans l'empreinte de version. Une section refusée empêche le chargement (échec
  fermé). Sans section, la version est inchangée.
- `core/learning/gate.py` compare le rapport du champion et celui du challenger :
  - jeu tenu à l'écart : 20 % du golden (D6), choisi par empreinte sha256 de l'identifiant ;
  - rejet : cas absent ou en erreur, comportement ou red team perdu, plus de violations R5,
    moins de cas tenus à l'écart réussis ;
  - non conclu : seuils à `A_DEFINIR`, jeu trop petit, gain inférieur à la marge, ou évals hors
    ligne (D4) ;
  - promouvable sinon.
- `config/evals.yaml › learning` : `holdout_percent: 20` ; `promotion_margin`,
  `min_held_out_cases`, `rollback_window_days`, `min_support`,
  `max_feedback_per_user` à `A_DEFINIR`. La fonction `learning.promotion`
  reste bloquée tant qu'ils ne sont pas fixés, avec les budgets.
- `core/learning/patterns.py` regroupe les entrées `ERROR` et les retours « mauvais » par pack
  (celui de la `DECISION` de la requête) et par type. Défenses contre l'empoisonnement (B78) :
  retours plafonnés par utilisateur (`max_feedback_per_user`), au moins `min_support` requêtes
  distinctes et jamais moins de deux (un retour seul ne change rien), notes porteuses de consignes
  écartées et comptées ; le rédacteur hors ligne écrit à partir des seuls comptes, jamais d'une
  note. Un challenger est une copie de la section avec une leçon ajoutée, sous
  `var/learning/challengers/`.
- `core/learning/champion.py` : la mise en service recalcule elle-même le verdict et exige
  `learning.promotion` ; l'historique `var/learning/champions.jsonl` (ajout seul) se rejoue en
  pile, si bien que chaque retour arrière défait une seule promotion ; la surveillance défait la
  dernière promotion si la porte rejette le rapport de production dans la fenêtre
  `rollback_window_days` (toujours surveillée tant qu'elle est `A_DEFINIR`).
- `cerveau learn status | gate | patterns | promote | rollback | watch` ; verdicts, mises en
  service et retours arrière s'écrivent au journal (événement `LEARNING`, empreintes, comptes et
  statut, jamais le texte appris).

## Conséquences
- Rien n'entre en service sans verdict « promouvable » sur des évals réelles, donc payantes et
  soumises à l'accord de Lucas.
- La couche peut seulement ajouter du texte de méthode ; les règles, seuils, autonomies et
  garde-fous restent hors d'atteinte.
- Restent à faire (backlog B347) : paramètres de routage et de recherche appris.
- La protection effective de `learned/` en écriture est l'ACL Windows (B77), comme pour
  `config/live.yaml` (ADR-003).
- Réversible : supprimer une section revient au champion d'origine ; git garde l'historique.
