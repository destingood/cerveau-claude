# Plan pour relancer ton île Fortnite (que dans Fortnite)

Objectif : plus de **vues** (impressions), plus de **clics**, des joueurs qui **restent**, puis des **ventes**.

Discover (la page d'accueil de Fortnite) fonctionne comme une chaîne :

```
Impressions ──> Clics (CTR) ──> Temps de jeu ──> Retour J1/J7 ──> Plus d'impressions
                                     │
                                     └──> Ventes (V-Bucks)
```

Si un maillon casse, tout s'arrête. Avec peu de vues et aucune vente, il faut réparer **dans cet ordre** :

| # | Quoi | Fichier | Temps |
|---|------|---------|-------|
| 1 | Vignette, titre, description, tags | [`page-ile.md`](page-ile.md) | 2 h |
| 2 | Progression sauvegardée + HUD + accueil | [`verse/progression_ile.verse`](verse/progression_ile.verse) | 1 h |
| 3 | Boutique avec les pièces gratuites | [`verse/boutique_pieces.verse`](verse/boutique_pieces.verse) | 30 min |
| 4 | Boutique en V-Bucks | [`verse/boutique_vbucks.verse`](verse/boutique_vbucks.verse) | 1 h |
| 5 | Publier avec un test A/B de vignette, puis suivre les chiffres | ce fichier, section 5 | 10 min/jour |

---

## 1. La page de l'île
Tout est dans [`page-ile.md`](page-ile.md) : le cahier des charges de la vignette, des modèles de titre et de description, les tags et les règles d'Epic à respecter.

## 2. Installer le code dans UEFN

1. Ouvre ton projet dans UEFN, puis **Verse > Verse Explorer**.
2. Clic droit sur le nom du projet, puis **Add new Verse file to project**. Choisis **Verse Device**, nomme-le `progression_ile` et colle le contenu de [`verse/progression_ile.verse`](verse/progression_ile.verse) en remplaçant tout.
3. Fais pareil pour `boutique_pieces` et `boutique_vbucks`.
4. **Verse > Build Verse Code** (Ctrl+Shift+B). S'il y a une erreur, copie-la-moi telle quelle et je la corrige.
5. Dans le **Content Browser**, dossier `CreativeDevices` de ton projet, fais glisser **un seul** exemplaire de chaque appareil dans la map.

### Régler `progression_ile` (panneau Details)
- **ObjectifPrincipal** : une phrase qui dit au joueur quoi faire, adaptée à ton jeu.
- **SourcesDePoints** : ajoute une ligne par action qui doit rapporter des points. Pour chaque ligne, place un **Trigger Device** relié à l'événement (fin de manche, checkpoint, élimination via un Elimination Manager, etc.).
- **Accolade** : place un **Accolades Device** et sélectionne-le. Il donne l'XP officielle Fortnite à chaque niveau, si ton île y a droit.
- **EffetMonteeNiveau** : un Trigger relié à un son ou à des VFX de victoire.

### Régler `boutique_pieces`
- **Progression** : sélectionne l'appareil `progression_ile`.
- **Articles** : une ligne par objet. Pour chacune, place un **Button Device** (le comptoir) et un **Item Granter** (l'objet donné), puis règle **Prix** et **NiveauMinimum**.
- Conseil : mets 1 objet pas cher (30 à 50 pièces, achetable dans les 5 premières minutes) et 1 objet de rêve bien visible (500 pièces et plus, ou un niveau minimum).

### Régler `boutique_vbucks`
- Importe 3 icônes carrées dans le dossier racine `Content` : `T_IconePieces`, `T_IconeVIP`, `T_IconePack`.
- **Progression** : sélectionne `progression_ile`.
- **BoutonsBoutique** : un Button Device au spawn, très visible, par exemple un PNJ marchand ou un comptoir doré.
- Avant de publier, coche **achats intégrés** dans le questionnaire de classification (IARC) du portail Creator. Sinon l'île est refusée à la modération.
- Pas encore prêt à vendre ? Mets tout `boutique_vbucks.verse` en commentaire : l'île reste valide.

### Tester avant de publier
- **Launch Session** : vérifie que le HUD s'affiche, que les points montent et que le niveau passe.
- Quitte la session, relance-la : le niveau et les pièces doivent être **gardés**.
- Les achats en V-Bucks se testent dans une session non publiée : c'est le mode aperçu des outils d'Epic, aucun vrai V-Buck n'est débité.

> Attention à la persistance : une fois l'île publiée, ne **supprime jamais** un champ de `donnees_joueur` et ne change pas son type, sinon les sauvegardes des joueurs cassent. On peut seulement **ajouter** des champs.

## 3. Les 60 premières secondes (à faire dans la map)
- Le joueur apparaît **directement dans l'action**, ou à 5 secondes maximum de l'action. Pas de lobby vide.
- **Supprime ou raccourcis** les longs textes de tutoriel : le HUD affiche déjà l'objectif.
- **Première récompense en moins d'une minute** : place une source de points facile juste à côté du spawn.
- Le comptoir de la boutique de pièces et celui de la boutique VIP doivent être **visibles depuis le spawn**.
- Teste sur **mobile ou manette** : textes lisibles, boutons faciles à atteindre.

## 4. Vendre sans faire fuir les joueurs
- Ne propose **jamais** un achat de force : la boutique s'ouvre seulement si le joueur va au comptoir. Une invite d'achat automatique serait soumise à des règles spéciales d'Epic.
- Si ton jeu est **PvP** : vends du confort ou du cosmétique, pas de la puissance. Les joueurs qui perdent contre des acheteurs partent, et ta rétention chute.
- L'achat d'entrée est à **100 V-Bucks**. Le **Pack de départ** est l'offre « évidente » : c'est le meilleur rapport, et il est placé en premier dans la boutique.
- Jusqu'au **31 janvier 2027**, tu gardes 100 % des V-Bucks de ces ventes. Ensuite, 50 % (annonce Epic de septembre 2025).

## 5. Publier et suivre les chiffres

### À la publication
- Mets **2 vignettes différentes** dans *Promotional Materials* pour lancer un **test A/B** (expliqué dans [`page-ile.md`](page-ile.md)).
- Écris des notes de mise à jour claires.

### Ce qu'il faut regarder (Creator Portal, onglet Analytics)

| Indicateur | Où | Bon signe | Si c'est mauvais |
|---|---|---|---|
| Impressions | Impressions | En hausse après la mise à jour | Revois les tags et la régularité des mises à jour |
| CTR | CTR (active le *benchmark*) | Au-dessus du benchmark de ta catégorie | Change de vignette (test A/B) |
| Temps de jeu moyen | Plays / Engagement | Au moins 10 min | Revois les 60 premières secondes et les sources de points |
| Rétention J1 | Retention | En hausse après la persistance | Bonus de retour, objectifs plus longs |
| Ventes | Revenus / transactions | Au moins 1 vente pour 100 joueurs | Rends la boutique plus visible, ajuste le Pack de départ |

**Une seule grosse modification à la fois**, puis 5 à 7 jours d'attente avant de juger. Sinon, impossible de savoir ce qui a marché.

### Rythme conseillé
- **Semaine 1** : nouvelle vignette (test A/B), titre, tags, persistance et HUD. Publication.
- **Semaine 2** : boutique de pièces, puis boutique V-Bucks. Publication.
- **Ensuite** : une mise à jour de contenu par semaine (nouvel objet, nouvelle zone, événement), avec une note de mise à jour.

---

### Limites
- Je n'ai **pas pu ouvrir tes analytics** (elles demandent ton compte Epic) : ce plan est général. Envoie une capture des graphiques et le code de l'île pour une version sur mesure.
- Le code Verse est écrit d'après la doc officielle d'Epic, mais je **n'ai pas pu le compiler ici** (UEFN tourne seulement sur Windows). Si UEFN affiche une erreur, colle-la-moi.
