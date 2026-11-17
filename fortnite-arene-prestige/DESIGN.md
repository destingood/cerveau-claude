# Arène Prestige : design, rétention et Discovery

## Le concept en une phrase

**Gun Game sans construction, pour 2 à 16 joueurs.** Chaque élimination te donne l'arme suivante, le premier qui
termine les 10 armes gagne. Les manches s'enchaînent sans retour au lobby, et toute ta progression
(pass de 30 paliers, 10 prestiges, séries) est sauvegardée.

Pourquoi ce format : le Gun Game se comprend en 5 secondes, une manche dure 5 à 7 minutes, et on a envie
de « refaire une dernière ». Ce sont exactement les qualités qu'il faut pour du temps de jeu et du
retour de joueurs.

---

## Comment marche « l'algorithme » (sans mythe)

La page Discover de Fortnite met en avant les îles qui **gardent leurs joueurs**. Ce qu'Epic montre
aux créateurs dans les Analytics du Creator Portal, et ce qui pèse dans la mise en avant :

1. **Le taux de clic (CTR)** : sur ceux qui voient ta miniature, combien cliquent. → C'est la **miniature et le titre**.
2. **Le temps de jeu par joueur** : combien de minutes ils restent. → C'est la **boucle de jeu**.
3. **La rétention J1 / J7** : combien reviennent le lendemain et la semaine suivante. → C'est la **progression**.
4. **Le nombre de joueurs simultanés.** C'est la conséquence des trois premiers.

Ce que ça veut dire concrètement : aucune ligne de code ne « trompe » l'algorithme. Le code
ci-dessous sert à **rendre le jeu agréable à rejouer**. C'est la seule chose qui fait monter ces
chiffres durablement.

---

## Les mécaniques de rétention dans le code, et pourquoi

| Mécanique | Ce qu'elle vise | Détail |
|---|---|---|
| **Palier 1 en ~3 min** | Rétention de la 1re session | Le joueur reçoit une récompense dès sa 1re manche : il a déjà « commencé » quelque chose. |
| **Coût des paliers progressif** (100 → 825 XP) | Temps de jeu | Le début va vite, la fin demande de l'investissement. Pass complet ≈ 7 h. |
| **Manches enchaînées sans lobby** | Temps de jeu | On ne quitte pas l'île entre deux manches, donc pas de « point de sortie » naturel. |
| **Pause de 8 s avec annonce + XP** | « Encore une » | Le moment où on voit sa barre d'XP monter, juste avant la manche suivante. |
| **Séries x3 / x5 / x10** | Moments forts | Messages à l'écran + bonus d'XP. |
| **Prime sur le leader** (+50 XP) | Équilibre | Ceux qui sont derrière ont une raison de chasser le leader, et personne ne décroche. |
| **Effets signature des armes** | Identité, variété | Vampire, Surcharge, Élan, Butin : chaque arme se joue différemment. |
| **1re victoire du jour** (+300 XP) | Rétention J1 | Une raison concrète de revenir chaque jour. |
| **Série de connexions** (50 → 350 XP sur 7 jours) | Rétention J7 | Récompense la régularité, plafonnée à 7 jours. |
| **Bonus « bon retour »** (+200 XP après 3 jours d'absence) | Réactivation | Celui qui revient est accueilli, pas puni. |
| **Prestige** (10 niveaux, étoiles, +5 % d'XP chacun) | Long terme (~70 h) | Le pass recommence, mais le joueur garde un statut visible et va plus vite. |
| **Titres tous les 5 paliers** | Statut | « Recrue » → « Légende de l'Arène ». |
| **Bouclier de départ plafonné à 50** | Équité | Avantage léger. Un nouveau joueur peut toujours battre un vétéran, sinon les nouveaux partent. |
| **XP de manche seulement avec au moins 1 élimination** | Anti-AFK | Empêche de farmer en restant immobile (et les fermes d'AFK sont mal vues par Epic). |

### Rythme vérifié par simulation

Script [`outils/simulateur_progression.py`](outils/simulateur_progression.py), avec un joueur moyen qui fait 4 éliminations par manche dans un lobby de 10 :

| Objectif | Prestige 0 | Prestige 9 |
|---|---|---|
| Palier 1 | ~3 min | ~2 min |
| Palier 5 | ~23 min | ~17 min |
| Palier 10 | ~1 h | ~50 min |
| Palier 30 (pass complet) | ~7 h | ~5 h 20 |
| **Prestige 10** | **~70 h au total** | |

Pour changer le rythme, modifie `CoutPalier` dans `arene_donnees.verse` **et** dans le simulateur,
relance-le, puis compare.

---

## Les « armes originales » : ce qui est vrai

UEFN ne permet pas (simplement) de créer une arme avec un nouveau modèle 3D et une nouvelle balistique.
Chaque arme de l'arsenal combine donc trois choses :
- une **arme Fortnite de base** (donnée par un Item Granter), avec la rareté que tu choisis ;
- un **nom original** affiché dans le HUD ;
- un **effet signature codé en Verse**, qui se déclenche à chaque élimination (Vampire, Surcharge, Élan, Butin).

Pour aller plus loin plus tard : nouveaux effets en Verse (explosion à l'élimination avec un Explosive
Device, marquage du leader avec un Map Indicator, etc.).

---

## La miniature

C'est le facteur n°1 du taux de clic, et c'est là que la plupart des maps échouent.

- 1920×1080, **lisible en tout petit** (sur téléphone, la vignette fait 3 cm).
- Un seul personnage en action, une arme bien visible, **3 mots maximum** en très gros (ex. « GUN GAME PRESTIGE »).
- Couleurs saturées, contraste fort, fond simple.
- Interdit (risque de refus ou de retrait) : faux logos Epic, promesses de V-Bucks, « XP gratuite »,
  images trompeuses.
- Change de miniature si le taux de clic stagne après une semaine. C'est le levier le plus rapide.

---

## Règles Epic à respecter (sinon l'île peut être retirée)

- **Aucune récompense en échange d'un like, d'un favori ou d'un abonnement**, et pas de « like pour débloquer ».
- Pas de promesse d'XP Fortnite officielle ni de V-Bucks.
- Pas de map conçue pour rester AFK. Le code donne déjà l'XP de manche seulement avec au moins 1 élimination.
- Remplis honnêtement la classification d'âge.
- Pas de contenu, de nom ou d'image copiés d'une autre marque ou d'un autre jeu.

---

## Mesurer, puis améliorer

Après publication, regarde chaque semaine dans **Creator Portal → Analytics** :

| Chiffre | Repère indicatif | Si c'est bas |
|---|---|---|
| CTR (impressions → parties) | viser plus de 5 % | Nouvelle miniature et titre plus clair |
| Durée moyenne de session | viser plus de 15 min | Arène plus petite, plus de spawns, manche plus courte (`DureeMancheSecondes`) |
| Rétention J1 | viser plus de 10 % | Palier 1 encore plus rapide, bonus quotidien plus visible |
| Rétention J7 | viser plus de 3 % | Ajouter des objectifs hebdo (voir ci-dessous) |

Ces repères sont des ordres de grandeur pour se situer, pas des chiffres officiels d'Epic.

### Prochaines améliorations possibles (dans l'ordre d'impact)

1. **Défis quotidiens** (« 15 éliminations au fusil à pompe », « gagne une manche ») : plus de raisons de revenir.
2. **Classement** de la session (Verse UI) : plus de compétition.
3. **Variantes de manche** : « tout le monde au sniper », « sans bouclier ». La variété garde les joueurs plus longtemps.
4. **Saisons** : remettre le pass à zéro tous les 1 à 2 mois avec un nouvel arsenal (le prestige reste).
5. **Mise à jour régulière** : une île mise à jour régulièrement revient dans les recommandations.

---

## Limites à connaître

- **Le code n'a pas été compilé** (UEFN n'existe que sur Windows). Il suit l'API Verse documentée, mais une ou deux corrections au premier build sont possibles. Envoie-moi l'erreur.
- **Personne ne peut garantir qu'une map perce.** Il y a des dizaines de milliers d'îles. Ce projet te donne une base
  solide et mesurable. Le succès vient ensuite de la miniature, de l'arène et de l'itération sur les chiffres.
- Le pseudo des joueurs ne peut pas être manipulé comme du texte en Verse. Il n'apparaît que dans l'annonce du vainqueur.
