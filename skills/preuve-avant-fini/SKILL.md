---
name: preuve-avant-fini
description: "Avant d'annoncer qu'un travail est fini, corrigé, qu'il marche ou que les tests passent, et avant un commit, une PR ou un compte rendu. Pas pour une simple question."
metadata:
  triggers: >-
    « c'est vraiment fini » « montre-moi la preuve » « tu as vraiment vérifié » « ça marche vraiment » « les tests
    passent vraiment » « vérifie avant de dire que c'est fini » « preuve avant fini » « verification before completion »
    Ne pas utiliser pour une recherche de faits sur le web (cerveau:recherche).
---

# Preuve avant « fini »

D'après verification-before-completion de Jesse Vincent (obra/superpowers, github.com/obra/superpowers,
skills/verification-before-completion, licence MIT : `LICENSE`), réécrite en français.

**La règle : aucune annonce de réussite sans une preuve fraîche.** Si la commande qui le prouve n'a pas tourné dans
ce message, je ne peux pas dire que ça marche.

## Avant toute annonce
1. **Quelle commande le prouve ?** (test, lint, build, page ouverte, script lancé sur un vrai fichier.)
2. **La lancer en entier**, maintenant, pas une version partielle.
3. **Lire la sortie** : code de sortie, nombre d'échecs, avertissements.
4. **Elle confirme ?** Oui → l'annoncer **avec** la preuve (« `python tests/test_x.py` : 42 vérifications OK,
   0 échec »). Non → dire l'état réel, chiffres à l'appui.

## Ce qui ne prouve rien

| Annonce | Preuve exigée | Pas suffisant |
|---|---|---|
| Les tests passent | sortie du test : 0 échec | un ancien passage, « ça devrait passer » |
| Le lint est propre | sortie du lint : 0 erreur | un contrôle partiel |
| Ça se construit | build terminé, code 0 | le lint qui passe |
| Le bug est corrigé | le symptôme d'origine refait : il a disparu | le code modifié, « en principe » |
| Le test de non-régression marche | vu rouge sans le correctif, vert avec | un passage au vert une fois |
| Un agent a fini | le diff (`git diff`, fichiers) relu | son compte rendu « réussi » |
| La demande est remplie | la demande relue point par point | les tests verts |
| La page de la boutique est en ligne | la page ouverte, le prix et le bouton vus | « publié » sans l'ouvrir |
| La map est prête | une partie lancée, la fiche relue (cerveau:fortnite) | la compilation UEFN seule |

## Signaux d'alerte : s'arrêter
- « devrait », « normalement », « a l'air de », « je pense que c'est bon » ;
- « Parfait ! », « C'est fait ! » avant d'avoir lancé quoi que ce soit ;
- un commit, une PR, un compte rendu qui arrive sans vérification ;
- « juste pour cette fois », la fatigue, l'envie d'en finir ;
- croire un agent, un outil ou un log sur parole.

| Excuse | Réponse |
|---|---|
| « Ça devrait marcher » | Lancer la vérification. |
| « J'en suis sûr » | L'assurance n'est pas une preuve. |
| « Le lint passe » | Le lint ne compile pas et ne teste pas. |
| « L'agent dit que c'est bon » | Vérifier soi-même. |
| « Un contrôle partiel suffit » | Un contrôle partiel ne prouve rien du reste. |

## Quand une vérification est impossible
(pas d'accès, outil absent, action que seul l'utilisateur peut faire) : le dire tel quel, avec ce qui a été
vérifié et ce qui ne l'a pas été, et la commande ou le geste qui le prouvera. Ne jamais l'arrondir en « fini ».

Un projet qui a sa propre vérification (`make test`, la CI, un hook de fin de tâche, la commande notée dans son
`CLAUDE.md`) : c'est elle, la preuve, en entier.
