---
name: cuisine-moi
description: "Quand l'utilisateur veut être interrogé à fond sur un projet ou une décision avant de se lancer. Sur demande : /cerveau:cuisine-moi."
disable-model-invocation: true
metadata:
  triggers: >-
    « cuisine-moi sur mon projet » « cuisine-moi sur ce plan » « cuisine-moi sur ma boutique » « cuisine-moi sur ma
    map » « grille-moi » « grill me » « passe-moi sur le grill » « interroge-moi sur mon projet » « pose-moi toutes les
    questions » « challenge mon plan » « mets mon idée à l'épreuve » « questionne-moi sur ce plan » Ne pas utiliser pour
    une « recette de cuisine », ni pour un entretien d'embauche à préparer (cerveau:carriere-commerciale).
---

# Cuisine-moi : toutes les questions, une réponse conseillée à chaque fois

D'après la skill grilling de Matt Pocock (github.com/mattpocock/skills, skills/productivity/grilling, licence MIT :
`LICENSE`), réécrite en français.

But : arriver à une compréhension commune d'un projet (une boutique, une map Fortnite, une vidéo, un module de la
plateforme, une recherche d'emploi) **avant** d'agir, sans rien laisser de supposé en silence.

## Méthode

1. **L'arbre des décisions.** Chaque décision en ouvre d'autres (le public visé décide du prix, qui décide de la
   page produit…). Le dessiner dans sa tête, pas à l'écran.
2. **Par tours.** La *frontière* : les décisions dont tout ce qui précède est déjà tranché, donc posables maintenant
   sans deviner une réponse pas encore donnée. Poser toute la frontière en un tour, questions numérotées, puis
   attendre les réponses. Une question qui dépend d'une autre encore ouverte dans ce tour attend le tour suivant.
3. **Chaque question porte ma réponse conseillée**, tournée pour que « oui » l'accepte :

   ```
   ❓ **Q1 — <titre court>** : <la question, avec les choix possibles s'il y en a>

   ➡️ <ma réponse conseillée, et pourquoi en une ligne>

   ---

   ❓ **Q2 — …**
   ```

   Questions courtes, mots simples, une idée par question : l'utilisateur doit pouvoir répondre « 1 oui, 2 non :
   plutôt X, 3 oui ».
4. **Les faits, c'est mon travail ; les décisions, les siennes.** Ce qui se vérifie (un fichier, le code, une page,
   une règle d'Epic, un prix, ce que le cerveau sait déjà : `brain q "<sujet>"`) : je le cherche moi-même, au besoin
   avec un sous-agent, sans le demander. Pendant qu'il cherche, je pose les questions qui n'en dépendent pas. Ce qui
   est un choix (budget, goût, priorité, risque accepté) : je le pose et j'attends.
5. **Après chaque tour**, les réponses déplacent la frontière : je recalcule et je pose le tour suivant. Une réponse
   qui en contredit une autre : je le signale tout de suite, dans le tour suivant.
6. **Fini quand la frontière est vide** : chaque branche visitée, rien de supposé. Je résume alors en une liste
   courte (« Décidé : … · Reste ouvert : … · Prochaine action : … ») et je demande si on est d'accord.
   **Rien n'est fait avant ce « oui ».** Les décisions durables vont dans le cerveau (`brain add -t decision …`),
   avec l'accord de l'utilisateur.

## À éviter
- Une seule question par message quand plusieurs sont déjà posables (trop lent) ; dix questions dont la moitié
  dépend des autres (trop de suppositions).
- Une question sans réponse conseillée, ou une réponse conseillée non justifiée.
- Demander à l'utilisateur ce que je pouvais trouver seul.
