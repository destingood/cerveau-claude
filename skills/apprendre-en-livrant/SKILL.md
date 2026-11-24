---
name: apprendre-en-livrant
description: "Quand l'utilisateur veut mettre en pratique un tutoriel, une vidéo, un cours ou des conseils, ou apprendre en livrant de petits projets. Pas pour un simple résumé."
metadata:
  triggers: >-
    « apprendre en livrant » « ship learn next » « ship-learn-next » « mets ce tuto en pratique » « mets cette vidéo en
    pratique » « transforme cette vidéo en plan d'action » « transforme ce cours en projets » « j'ai regardé cette vidéo,
    et maintenant » « plan d'action à partir de ce tuto » « apprendre en faisant » « des petits projets pour apprendre »
    Ne pas utiliser pour « résume cette vidéo » (cerveau:web), ni pour un plan de travail sur un projet existant.
---

# Apprendre en livrant : Livrer → Apprendre → Suivant

D'après ship-learn-next de Michał Parkola et des contributeurs de tapestry-skills
(github.com/michalparkola/tapestry-skills, ship-learn-next, licence MIT : `LICENSE`), réécrite en français.

**Principe : 100 répétitions valent mieux que 100 heures d'étude.** Apprendre, c'est mieux faire, pas en savoir plus.
Chaque répétition a trois temps : **Livrer** une chose réelle (une page, une vidéo, une map, un message de
prospection, un script), **Apprendre** (bilan honnête), **Suivant** (la répétition d'après).

## Méthode

1. **Lire la source.** Fichier, page, notes : la lire. Une vidéo YouTube d'un autre : ses sous-titres par
   cerveau:web (Agent Reach ou yt-dlp). Garder seulement ce qui se pratique : techniques, étapes, exemples à refaire,
   pas les histoires ni la théorie « bonne à savoir ».
2. **Fixer la quête** (4 à 8 semaines), par deux ou trois questions courtes : que veux-tu avoir fait ? à quoi verras-tu
   que c'est réussi ? qu'est-ce que tu peux livrer de concret ? Bonne quête : « publier 3 Shorts et en garder un au-dessus
   de 1 000 vues ». Mauvaise : « apprendre le montage » (trop vague : la reformuler en « livrer Y avant le Z »).
3. **Répétition 1 : la plus petite version livrable cette semaine** — concrète, faisable en 1 à 7 jours, qui laisse
   une trace (fichier, lien, capture), assez petite pour ne pas faire peur, assez grande pour apprendre quelque chose.
   N'apprendre **que** ce qu'il faut pour elle.
4. **Écrire le plan**, une fiche par répétition :

   ```markdown
   ## Répétition 1 : <but précis>
   **À livrer** : … · **Réussi si** : - [ ] … - [ ] … · **Pour le** : <date>
   **Ce que je pratique** (tiré de la source, avec le minutage ou la section) : …
   **Étapes** : 1. … 2. … 3. Livrer (publier, mettre en ligne, envoyer, montrer)
   **Ressource minimale** (seulement si elle sert à CETTE répétition) : …
   **Après** : qu'est-ce qui s'est passé ? qu'est-ce qui a marché, raté, surpris ? note sur 10 ? une chose à changer ?
   ```

   Puis les répétitions 2 à 5 en une ligne chacune : une seule nouveauté par répétition, difficulté qui monte si la
   précédente a réussi, chacune reliée à une leçon de la source. Elles changeront après le bilan des deux premières.
5. **Enregistrer** le plan en Markdown : `Plan Livrer-Apprendre - <titre en 3 à 6 mots>.md`, dans le coffre Obsidian
   ou le wiki du cerveau si l'utilisateur en a un (demander où, une fois), sinon dans le dossier courant. Ajouter
   l'échéance de la répétition 1 aux à-faire du cerveau : `brain add -t todo -T "Répétition 1 : <but>" --due <date>`.
6. **Montrer** : le chemin du fichier, la quête en une phrase, la répétition 1. Puis demander : « Tu la livres
   quand ? », « Qu'est-ce qui pourrait t'arrêter, et que feras-tu alors ? », « Reviens après l'avoir livrée : on fait
   le bilan et on prépare la 2. »

## Ton
Direct et encourageant, sans remplissage ; des questions plutôt que des leçons ; du précis (« vendredi, une page
produit en ligne ») plutôt que du général. Mots simples, phrases courtes.

## À éviter
Un plan d'étude au lieu d'un plan de livraison ; une liste de tout ce qu'il faudrait lire ou regarder ; viser la
perfection dès la répétition 1 ; laisser planifier sans jamais commencer ; accepter un but vague ; montrer tout le
parcours d'un coup au lieu de la prochaine répétition.
