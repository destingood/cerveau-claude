# Guide pas à pas : construire « Arène Prestige » dans UEFN (débutant)

Compte 3 à 5 heures pour une première version jouable, dont la moitié pour la décoration de l'arène.
Il te faut un **PC Windows** (UEFN ne tourne pas sur Mac, console ou téléphone).

---

## Étape 0 — Installer UEFN

1. Installe l'**Epic Games Launcher**, connecte-toi avec ton compte Fortnite.
2. Onglet **Fortnite** → installe **Unreal Editor for Fortnite** (UEFN).
3. Crée un **compte créateur** : <https://create.fortnite.com> → « Creator Portal ».
   Pour **publier** (rendre l'île jouable par tout le monde), il faut s'inscrire au programme
   créateurs (vérification d'identité, âge minimum fixé par Epic). Tu peux tout construire et
   tester avant d'être inscrit.

## Étape 1 — Créer le projet

1. Lance UEFN → **New Project** → choisis le modèle **Blank** (île vide) → nom : `ArenePrestige`.
2. Menu **Window → World Settings / Island Settings** (« Paramètres de l'île »), règle :

| Réglage | Valeur |
|---|---|
| Max Players | 16 |
| Teams | Free For All (chacun pour soi) |
| Allow Building | **None** (aucune construction) |
| Environment Damage | Off |
| Infinite Ammo / Infinite Reserve Ammo | On |
| Respawn | On, temps de réapparition 2 s |
| Spawn Immunity Time | 2 s (évite les tués à l'apparition) |
| Eliminated Player's Items | Delete (pas de loot au sol) |
| Round time limit / Eliminations to end | **Off** (c'est le code Verse qui gère les manches) |
| Start with Pickaxe | On |
| Join in progress | **Spawn** (les joueurs rejoignent une partie en cours : indispensable pour la rétention) |

## Étape 2 — L'arène

Fais une arène **compacte** : environ 60 × 60 m pour 8 à 16 joueurs. Si elle est trop grande, les joueurs se cherchent et s'ennuient.

- Utilise les **prefabs** et **galleries** (onglet Content Browser → Fortnite → Prefabs).
- Il faut 3 niveaux de hauteur, des couvertures basses, aucun long couloir à sniper et aucun coin où se cacher indéfiniment.
- Place **12 à 16 `Player Spawner`** répartis partout (pas tous au même endroit).
- Place **à l'écart de l'arène** (ou sur une plateforme visible depuis le spawn) :
  - 1 **`Button`** : le bouton PRESTIGE. Mets son texte d'interaction sur « PRESTIGE ».
  - Un panneau (Billboard device) qui explique : « Finis le pass (palier 30) puis appuie ici ».

## Étape 3 — Les devices

Dans le Content Browser → **Fortnite → Devices**, glisse dans la map :

### a) 10 × `Item Granter` (un par arme de l'arsenal)

Pour CHACUN :
- **Item List** : ajoute l'arme de base (voir tableau ci-dessous) à la rareté de ton choix.
- **On Grant Action** : **Clear All Items** (l'ancienne arme disparaît quand on passe à la suivante).
- **Equip Granted Item** : Yes (ou « First Item »).
- **Grant on Game Start** : No (c'est le Verse qui donne les armes).
- Renomme le device dans l'Outliner (ex. `Granter_01_Etincelle`) pour t'y retrouver.

| # | Nom dans le jeu | Arme de base conseillée | Effet signature (Verse) |
|---|---|---|---|
| 1 | Étincelle | Pistolet | — |
| 2 | Croc de Givre | Mitraillette (SMG) | Élan : vitesse après chaque élimination |
| 3 | Rafale Solaire | Fusil d'assaut | Surcharge : +25 bouclier |
| 4 | Marteau d'Orage | Fusil à pompe | Vampire : +30 PV |
| 5 | Écho | Fusil tactique / DMR | Butin : XP x2 |
| 6 | Nova | Mitrailleuse lourde | Surcharge : +25 bouclier |
| 7 | Faucheuse | 2ᵉ fusil à pompe | Vampire : +30 PV |
| 8 | Aiguille | Fusil de précision (sniper) | Butin : XP x2 |
| 9 | Tempête | Arme explosive (lance-grenades, etc.) | Élan : vitesse |
| 10 | Dernier Mot | Pistolet faible / arme difficile | — (la dernière doit être dure à réussir) |

> Les armes disponibles dans UEFN changent selon les saisons de Fortnite : prends ce qui existe dans
> ta version, en gardant l'idée « on commence facile, on finit difficile ».

### b) 1 × `Movement Modulator`
- **Speed multiplier** : 1.5, **Duration** : 3 s. C'est l'effet « Élan ».

### c) Pas d'autre device obligatoire
Le HUD, l'XP, le pass, le prestige et les manches sont entièrement gérés par le Verse.

## Étape 4 — Ajouter le code Verse

1. Menu **Verse → Verse Explorer**.
2. Clic droit sur le dossier du projet → **Create New Verse File** → choisis **Empty** → nomme-le
   `arene_donnees`. Ouvre-le (VS Code s'ouvre), **efface tout** et colle le contenu de
   [`verse/arene_donnees.verse`](verse/arene_donnees.verse).
3. Pareil pour un 2ᵉ fichier `arene_prestige` avec [`verse/arene_prestige.verse`](verse/arene_prestige.verse).
4. Enregistre, puis dans UEFN : menu **Verse → Build Verse Code** (Ctrl+Shift+B).
   - ✅ « Build succeeded » : passe à l'étape 5.
   - ❌ Erreur : copie **le message d'erreur complet** (fichier + numéro de ligne) et envoie-le-moi,
     je te donne la correction. (Le code n'a pas pu être compilé ici, car UEFN n'existe que sur Windows. Une ou deux petites
     corrections de syntaxe au premier build sont possibles, c'est normal.)
   - Cas connu : si l'erreur porte sur `GetSecondsSinceEpoch`, remplace le contenu de la
     fonction `JourActuel()` par la seule ligne `0`. Les bonus quotidiens seront coupés, le reste
     marchera.

## Étape 5 — Placer et relier le device Verse

1. Dans le Content Browser, cherche **`arene_prestige_device`** (dans le dossier de ton projet,
   « CreativeDevices ») et glisse-le dans la map (n'importe où, il est invisible en jeu).
2. Sélectionne-le → panneau **Details** :
   - **Arsenal** : il y a déjà 10 lignes (les noms). Pour chaque ligne, clique sur **Donneur** et choisis
     l'Item Granter correspondant (1 → `Granter_01_Etincelle`, etc.). Tu peux renommer les armes ici.
   - **PointsApparition** : clique sur **+** autant de fois que tu as de Player Spawners et relie-les tous.
   - **ModulateurVitesse** : relie le Movement Modulator.
   - **BoutonPrestige** : relie le Button.
   - **DureeMancheSecondes** : 420 (7 min max). **PauseEntreManchesSecondes** : 8.

## Étape 6 — Tester

1. Bouton **Launch Session** (en haut) → Fortnite s'ouvre sur ton île.
2. **Start Game**. Vérifie :
   - [ ] Le HUD apparaît à gauche (prestige, palier, arme, série).
   - [ ] Tu reçois l'arme 1 à l'apparition.
   - [ ] Une élimination fait passer à l'arme 2 et affiche « +XP ».
   - [ ] Le palier 1 se débloque vite (100 XP = 4 éliminations).
   - [ ] La dernière arme fait gagner la manche, annonce, XP, nouvelle manche.
   - [ ] **Après avoir été éliminé et être réapparu**, tes éliminations comptent toujours.
     Si ce n'est pas le cas, signale-le : la correction consiste à rebrancher l'écoute des éliminations à chaque apparition.
3. Pour tester à plusieurs : invite des amis dans ta session privée (le code d'invitation de la
   session UEFN), ou ajoute des **Guard Spawners** comme cibles. Attention : le code ne donne
   l'XP que pour les éliminations de **joueurs**, pas de gardes.
4. **Note sur la sauvegarde** : en test UEFN, la progression peut repartir de zéro à chaque session.
   Elle n'est vraiment conservée que sur l'île publiée.

## Étape 7 — Publier

1. **Project → Create New Release / Publish** → remplis :
   - **Titre** : court, clair, avec le mot-clé recherché. Ex. *« GUN GAME PRESTIGE 🔫 NO BUILD »*.
   - **Description** : 3 lignes : le mode, la progression (« 30 paliers + 10 prestiges »), sans construction.
   - **Tags** : *gun game*, *no build*, *ffa*, *pvp*.
   - **Miniature** 1920×1080 : voir [DESIGN.md](DESIGN.md#la-miniature).
   - **Classification d'âge** : remplis le questionnaire honnêtement (violence cartoon).
2. La validation par Epic prend de quelques heures à quelques jours.
3. Une fois en ligne : **Creator Portal → Analytics**. Ce sont ces chiffres qui te diront si ça marche
   (voir DESIGN.md, section « Mesurer »).

## Modifier le code plus tard sans casser les sauvegardes

- Tu peux changer librement : les noms d'armes, l'XP, les titres, le nombre d'armes, les effets.
- Dans `sauvegarde_joueur` (fichier `arene_donnees.verse`) : **ajoute** des champs si besoin (avec une
  valeur par défaut). **Ne supprime et ne renomme jamais** un champ existant après publication.
