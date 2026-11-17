# Fiche 05 — Publier et lancer (les deux semaines de test)

Objectif : arriver à la publication avec tout prêt, parce que Discover teste une nouvelle île pendant deux semaines au
plus et juge sur ce qu'il voit à ce moment-là (fiche 02).
Sources : Fortnite Developer Program, Publishing from the Creator Portal, Links, Engagement Payout, règles des
développeurs (lus le 14/11/2026).

## 1. Avant de pouvoir publier

- Rejoindre le Fortnite Developer Program : **18 ans au moins**, et soit un achat en argent réel par Epic Payments dans
  les 365 derniers jours (cartes cadeaux et solde exclus), soit 20 $ dépensés et utilisés dans Fortnite sur la même
  période, sur n'importe quelle plateforme [FAIT].
- Choisir son code créateur : 3 à 16 caractères (lettres, chiffres, `_`, `-`, `.`) ; c'est le nom public et le `@nom`
  de l'adresse fortnite.com ; il ne change qu'une fois par an [FAIT]. Le choisir comme une marque : il apparaît dans
  chaque lien de map.
- Paiements en argent : entretien fiscal et compte Hyperwallet ; en V-Bucks : portefeuille développeur [FAIT].
- Moins de 18 ans : publier passe par un adulte qui remplit ces conditions. Conditions d'âge du compte, double
  authentification, vérification d'identité : [NON VÉRIFIÉ — absentes de la page actuelle].

## 2. La liste de la veille

| Point | Contrôle |
|---|---|
| Titre, description, How to Play, tags, genre | `fiche.py` sans bloquant (fiche 03) |
| Cinq images aux bonnes dimensions | `medias.py` sans bloquant |
| Variante B des miniatures prête | Pour lancer le test A/B dès les premières impressions |
| Premier combat en moins d'une minute, file d'attente réglée | Trois testeurs qui ne connaissent pas la map (fiche 04) |
| 30 images par seconde sur la plateforme la plus faible | Règle 1.14 |
| Accolades réglées | Une toutes les 2 à 10 minutes (fiche 04) |
| Page web prête (facultatif) | `page_ile.py ile.json --controle` (fiche 06) |
| Liens de suivi créés | Onglet Links du portail : un lien nommé par canal (section 4) |

## 3. Visibilité et date

- Trois choix : **Listed** (Discover et recherche), **Unlisted** (ni Discover ni recherche, jouable par code), ou
  publication manuelle plus tard, programmable [FAIT].
- Tester en **Unlisted** avec des amis ne lance pas la fenêtre de test de Discover [HYPOTHÈSE — l'île n'y apparaît
  pas]. Passer en Listed seulement quand la liste ci-dessus est verte.
- Epic : « Wait until your submission is published before sharing promotional media externally. » [FAIT]
- Choisir le jour : celui où on peut répondre, corriger un bug et publier une mise à jour dans la semaine.

## 4. Les premiers joueurs, sans payer

Ce qui compte pendant le test, ce sont des joueurs qui restent (fiche 02), pas un pic de curieux qui repartent.

- **Liens de suivi** : un lien par canal (Discord, TikTok, YouTube, page web), mesuré en parties et joueurs actifs,
  dix liens par graphique au plus [FAIT — Links]. Le lien ne compte pas pour les joueurs de l'Union européenne dans
  l'attribution du paiement à l'engagement [FAIT — Engagement Payout] ; il reste utile pour savoir d'où ils viennent.
- **Le code d'île partout** : Epic demande de l'inclure dans chaque contenu (« always include your island code »)
  [FAIT — Developer Marketing Playbook].
- **Vidéo courte** et **réseaux** : un clip de vrai jeu, le code à l'écran. Rédaction : skill `cerveau:youtube`
  (titres, Shorts) ou `anthropic-skills:video`.
- **Communautés** : un serveur Discord, les notes de mise à jour publiées [FAIT — Developer Marketing Playbook].
- **Communautés Fortnite** : des salons et des publications visibles dans Fortnite et sur fortnite.com [FAIT].

Règles de la promotion hors de Fortnite (règles des développeurs, section 3) [FAIT] :

- la mention **« This is not sponsored, endorsed, or administered by Epic Games, Inc. »** de façon visible sur tout
  support de promotion ;
- pas de logo Fortnite ou Epic Games (le logo « Developed in Fortnite » selon ses règles d'usage) ; seulement des
  tenues qui appartiennent à Epic ;
- pas de publicité télé ou sur un réseau publicitaire sans accord écrit d'Epic ; permis : ses propres sites et
  réseaux, et des annonces texte dans les moteurs de recherche, mais jamais sur les mots « Fortnite » ou « Epic Games » ;
- un influenceur payé est signalé clairement ; en France, mention « Publicité » ou « Collaboration commerciale » (loi
  n° 2023-451 du 9 juin 2023, art. 5) ;
- ne jamais viser les moins de 13 ans ; un concours se tient entièrement hors de l'île, et rien de ce qui se passe hors
  de l'île ne change le jeu dedans.

Interdit, quelle que soit la forme : faux comptes, robots, échanges de favoris ou de recommandations, copies de son
île pour occuper plus de place [FAIT — règles 1.9 et 1.9.1 ; aucune règle ne nomme les robots, mais gonfler les mesures
relève de la manipulation de visibilité].

## 5. Les deux semaines

| Jour | À faire |
|---|---|
| J0 | Publication en Listed ; lancement du test A/B ; `tendances.py suivre <code>` (premiers chiffres quand l'île passe 5 joueurs uniques) |
| J1 à J3 | Bugs bloquants seulement. Ne pas changer de titre ni de miniature : le test A/B le fait mieux |
| J3 | Premier `diagnostic.py entonnoir` avec les références du menu Benchmarks |
| J7 | Une correction, celle du goulot. Republier avec des notes de mise à jour |
| J14 | Bilan : `tendances.py suivre`, `diagnostic.py`, comparaison avec la niche (`comparer … --json`) ; décision : continuer, refaire la fiche, ou changer de concept |

- Le tableau « Discover Performance Snapshot » (impressions, clics, taux de clic, durée de session, part des sessions
  de plus de 10 minutes) n'apparaît qu'au-delà de 5 000 impressions Discover en un jour [FAIT] ; avant, les chiffres
  viennent d'Analytics.
- Epic's Picks : candidature possible une fois l'île publiée et publique (fiche 02).
