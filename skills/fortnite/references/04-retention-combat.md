# Fiche 04 — Rétention d'une map de combat : les dix premières minutes, puis le retour

Objectif : construire la map pour les mesures que Discover regarde (fiche 02). Epic ne publie pas de guide de
rétention propre aux maps de combat [NON VÉRIFIÉ qu'il n'en existe aucun] : les faits viennent de ses pages Project
Analytics, Matchmaking Queue Controls et Accolades ; le reste est marqué [HYPOTHÈSE] et se valide par la mesure.

## 1. La grille de lecture d'Epic : trois seuils de rebond

| Seuil | Lecture d'Epic [FAIT — Project Analytics] | Où chercher dans une map de combat |
|---|---|---|
| Rebond à 2 min | Miniature « not representative of the in-island experience », ou problème technique à l'entrée | Chargement, file d'attente, premier écran ; la miniature promet-elle ce format ? |
| Rebond à 5 min | « initial experience is not engaging » | Temps avant le premier combat, lobby vide, règles incomprises |
| Rebond à 10 min | La « engagement loop » ne retient pas | Enchaînement des manches, équilibrage, raison de rejouer |

La durée de session exclut le lobby, le chargement et les mises en relation ratées [FAIT] : seul le jeu compte.

## 2. De l'arrivée au premier combat

[HYPOTHÈSE, sauf mention] Chaque point se vérifie sur le rebond à 2 et 5 minutes.

- Un joueur doit tirer ou construire dans la première minute. Pas de couloir, pas de panneau à lire, pas de vote long.
- Les consignes passent par les lignes « How to Play » de l'écran de chargement [FAIT : elles s'y affichent], pas par
  un mur de texte dans la map.
- Équipement donné d'office, ou choisi en un geste. Réapparition immédiate.
- Rien de ce que montre la miniature ne doit manquer : armes et appareils de l'image présents dans l'île [FAIT —
  Thumbnail Image Policies].
- 30 images par seconde au moins, sur toutes les plateformes [FAIT — règle 1.14] : tester sur console d'ancienne
  génération et sur mobile avant de publier.

## 3. Le lobby vide (le piège d'une map neuve)

Une map de combat sans adversaire n'a pas de jeu. Réglages de file d'attente d'Epic [FAIT — Matchmaking Queue
Controls] : joueurs maximum, joueurs minimum, cible de joueurs en prolongation, durée principale et durée de
prolongation de la file. Leur but : « prioritize fuller matches over short queue times » ; Epic conseille pourtant
des attentes minimales, même si deux minutes sont permises. Un groupe plus petit que l'équipe reste dans la même équipe.

- Petit maximum de joueurs au lancement (1v1, 2v2, 4 à 8 joueurs) : la partie se remplit avec peu de monde
  [HYPOTHÈSE]. Exemple d'Epic pour un 5v5 (Ballistic) : maximum 10, minimum 4, cible en prolongation 6 [FAIT].
- Quelque chose à faire seul en attendant : cibles, parcours d'édition, entraînement à la visée, avec bascule
  automatique en combat à l'arrivée d'un adversaire [HYPOTHÈSE].
- La file : l'onglet Gameplay du portail ne montre les centiles d'attente que si le réglage par défaut (5 secondes) a
  été changé [FAIT].

## 4. La boucle : pourquoi lancer la manche suivante

[HYPOTHÈSE] À valider sur le rebond à 10 minutes et la durée de session.

- Manches courtes, relance automatique, aucun retour au lobby entre deux manches.
- Score visible en permanence et en fin de manche (éliminations, série, précision).
- Équilibrage : un débutant écrasé dix fois part. Rotation des adversaires, équipes rééquilibrées, zones tirées au sort.
- Variété sans menu : la map change un paramètre à chaque manche plutôt que de demander un vote.

## 5. Jouer à plusieurs (signal Social Play)

Epic mesure les invitations, les retours en groupe et la part du temps joué en groupe [FAIT — How Discover Works ;
mesures annoncées « soon » dans le portail]. Pour une map de combat [HYPOTHÈSE] : tailles d'équipe qui acceptent un duo
ou un trio sans le séparer, revanche en un geste, salons privés entre amis.

## 6. XP et accolades

- « All players should get accolades when playing a full game », attribuées à l'action principale : dans un free for
  all, les éliminations [FAIT — Using Accolades Devices].
- Rythme : une toutes les 2 à 10 minutes en moyenne ; à moins d'une seconde d'écart, « might seem like spam » ; la
  plupart atteignables en quelques heures de jeu [FAIT].
- L'XP passe par un calibrage après publication ; depuis la v40.30, les petites îles en donnent une partie avant le
  calibrage complet [FAIT — notes de version 40.30].
- Ne jamais annoncer l'XP dans la fiche ni sur la miniature (fiche 03).

## 7. Revenir le lendemain (J1) et la semaine suivante (J7)

- Epic : « give players a reason to keep coming back », des systèmes qui accueillent les nouveaux et récompensent ceux
  qui reviennent [FAIT — critères d'Epic's Picks] ; « Keep your island fresh with regular updates » [FAIT — Developer
  Marketing Playbook]. Aucun rythme n'est donné.
- Pistes [HYPOTHÈSE] : statistiques gardées d'un jour à l'autre, classement de la semaine, rotation de zones ou
  d'équipements annoncée dans la map, mise à jour à jour fixe.
- Les favoris : le dispositif « Creator Profile Link » permet de mettre le créateur en favori depuis l'île [FAIT —
  billet du 26/03/2025]. Interdit : toute tactique trompeuse pour obtenir un favori ou une recommandation [FAIT —
  règle 1.9]. Leur poids dans Discover : [NON VÉRIFIÉ].
- Langues : Fortnite en prend 17 en charge ; traduire la fiche et les textes de l'île élargit le public [FAIT —
  Developer Marketing Playbook].

## 8. Vérifier avant de publier

Faire jouer la map à des gens qui ne la connaissent pas, sans rien leur expliquer, et noter : temps jusqu'au premier
combat, moment où ils décrochent, première question posée. Trois testeurs muets valent mieux qu'un avis.
Après publication : `diagnostic.py entonnoir` (fiche 07) dit laquelle de ces sections reprendre.
