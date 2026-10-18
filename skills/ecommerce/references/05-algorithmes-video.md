# Module 05 — Algorithmes et vidéo courte : avoir des vues et des impressions vite

Sommaire : 1. Comment marche un algorithme de recommandation (prouvé par le code) · 2. Ce que ça change pour une
boutique · 3. Fiches par plateforme · 4. Formats · 5. Scripts et accroches · 6. Production · 7. Boucle d'analyse ·
8. Mythes · 9. Règles légales

## 1. Comment marche un algorithme de recommandation

Le code de production du fil « Pour vous » de X est public (dépôt xai-org/x-algorithm, mis à jour quasi chaque jour,
lu le 17/10/2026 ; versions de 2023 dans twitter/the-algorithm et the-algorithm-ml) ; Etsy décrit publiquement la même
mécanique ; l'entraînement en temps réel est documenté par ByteDance (dépôt bytedance/monolith). Le schéma commun
[FAIT pour X et Etsy ; CONSENSUS pour les autres plateformes] :

1. **Sélection des candidats** : d'un océan de contenus, quelques milliers par personne ; chez X, environ la moitié
   vient des comptes suivis.
2. **Filtres avant le score** : doublons, contenus déjà vus, trop vieux (48 h pour le fil de X), auteurs bloqués ou
   masqués, contenus non éligibles.
3. **Prédiction de plusieurs actions** pour chaque personne : environ 25 chez X en 2026 (J'aime, réponse, repartage,
   partage, envoi en message, copie du lien, clic, temps passé, abonnement… et « pas intéressé », masquer, bloquer,
   signaler).
4. **Somme pondérée** des probabilités prédites. Poids de production de X au 17/10/2026 (`home-mixer/params/param.rs`) :

   | Action prédite | Poids |
   |---|---|
   | J'aime | 0,66 |
   | Repartage | 1,0 |
   | Réponse | 5,0 (20 entre comptes qui se suivent mutuellement, sur un post original) |
   | Partage / envoi en message / copie du lien | 2,0 / 5,0 / **20,0** |
   | Abonnement à l'auteur | 4,0 |
   | Clic sur un lien externe | 0,2 |
   | « Pas intéressé » / masquer / bloquer | −52,3 / −58,8 / −31,2 |
   | Signalement | −234 |

   Les poids multiplient des **probabilités prédites**, pas des compteurs, et ils bougent souvent (le poids du J'aime
   est passé de 0,5 à 0,66 en octobre 2026) [FAIT — dépôt xai-org/x-algorithm].
5. **Signaux négatifs durables** : « voir moins souvent » divise le score d'un auteur par 5, avec un retour progressif
   sur 140 jours ; les signalements rapportés aux J'aime alimentent des étiquettes de compte [FAIT — twitter/the-algorithm].
6. **Diversité** : le 2e, 3e, 4e contenu d'un même auteur dans un fil est multiplié par 0,625 / 0,44 / 0,34 ; les
   contenus hors réseau par 0,75 ; les contenus trop semblables sont écartés [FAIT — X].
7. **Exploration des nouveaux contenus** : chez X, un post **original** d'un compte de **50 000 abonnés au plus**,
   publié depuis **moins de 2 heures** et vu **moins de 200 fois**, peut obtenir un créneau de test ; on le garde s'il
   déclenche des réactions [FAIT — X, seuils modifiés plusieurs fois en 2026].
8. **Temps réel** : les modèles apprennent en continu (agrégats sur 30 minutes ; entraînement en flux avec
   synchronisation à la minute dans Monolith) → les réactions des premiers spectateurs changent la diffusion en
   quelques minutes [FAIT pour le code ; que TikTok utilise Monolith tel quel : HYPOTHÈSE].
9. **Visibilité ≠ classement** : un contenu peut être limité aux abonnés, précédé d'un avertissement ou retiré, quel
   que soit son score.

## 2. Ce que ça change pour une boutique

| Principe prouvé | Application |
|---|---|
| Les actions « lourdes » pèsent bien plus qu'un J'aime | Écrire pour l'**envoi** (« montre ça à… »), l'enregistrement (tuto, liste), la réponse (vraie question) et le temps passé |
| Un « pas intéressé » coûte des dizaines de J'aime | Jamais d'accroche trompeuse ni de promo répétitive ; tenir la promesse des 2 premières secondes |
| Décote par auteur et par similarité | **1 idée nouvelle = 1 vidéo** : pas de séries de variantes quasi identiques publiées en rafale |
| Fenêtre de test des premières heures | Publier quand la cible est en ligne, rester disponible pour répondre dans la première heure, ne pas publier 3 contenus à la fois |
| Originalité exigée partout | Images tournées soi-même, sans filigrane d'une autre application, sans repost de contenu tiers |
| Le lien externe n'est pas pénalisé explicitement (X) mais pèse peu | La valeur dans la vidéo d'abord, le lien ensuite (bio, commentaire épinglé, nom de domaine court affiché) |

## 3. Fiches par plateforme (état au 18/10/2026)

**TikTok**
- Signaux officiels : interactions (vidéos regardées en entier, aimées, partagées, commentées, recherches), infos de
  la vidéo (légende, sons, hashtags), réglages de l'appareil (poids faible) ; le nombre d'abonnés et les succès passés
  ne sont pas des facteurs directs [FAIT — Newsroom TikTok, 2020].
- Non éligibles au fil « Pour toi » : contenu non original ou réutilisé sans apport (filigrane d'autrui), incitations
  « like pour like » ; un compte qui en publie beaucoup peut devenir non éligible en entier ; le statut s'affiche dans
  les statistiques et peut faire l'objet d'un appel [FAIT — règles communautaires 2025 et 2026].
- **Auto-promotion** : activer le réglage de divulgation sur toute vidéo qui promeut sa propre entreprise ou ses
  produits ; sans lui, visibilité réduite (version du 24/09/2026) [FAIT].
- Actions : divulgation activée ; contrôle de l'éligibilité de chaque vidéo dans les statistiques ; mots que la cible
  recherche dans la légende et le texte à l'écran (TikTok est aussi un moteur de recherche) [HYPOTHÈSE].
- TikTok Shop (ouvert en France depuis le 31/03/2025) : vitrine et affiliation de créateurs dans l'application
  (module 16).

**Instagram et Facebook (Meta)**
- Signaux clés selon Adam Mosseri (janvier 2025) : temps de visionnage ; J'aime rapportés à la portée (surtout auprès
  des abonnés) ; **envois en message rapportés à la portée** (surtout pour toucher des non-abonnés) [FAIT rapporté].
- Originalité : les reposts sont remplacés par l'original dans les recommandations ; un compte qui republie 10 fois ou
  plus en 30 jours en est exclu ; règle étendue aux photos et carrousels le 30/04/2026 [FAIT rapporté].
- **Trial reels** : Reels montrés d'abord à des non-abonnés, statistiques après 24 h → tester un angle sans risque
  pour le compte [FAIT rapporté, 12/2024].
- Hashtags : 5 au plus ; ils n'augmentent pas la portée selon Mosseri [FAIT rapporté]. Publications des comptes pro
  publics indexables par Google depuis le 10/07/2025.
- Actions : chaque angle d'abord en trial reel ; écrire pour l'envoi ; 3 à 5 mots-clés descriptifs ; compte pro
  public ; jamais de republication de contenu tiers.

**YouTube Shorts**
- Règles anti-spam : manipulation d'engagement, spam de commentaires, contenu créé seulement pour faire sortir de
  YouTube, production de masse automatisée ou par IA, contenu repris sans apport, clickbait trompeur ; monétisation :
  contenu « inauthentique » (répétitif, produit en masse) exclu (règle du 15/07/2025) [FAIT].
- Action : chaque Short apporte sa valeur (démo, test, conseil) avant le lien ; pas de séries quasi identiques.

**Pinterest**
- Interdits : bourrage de mots-clés hors sujet, redirection de Pins existants vers une nouvelle destination, contenu
  répétitif, liens vers des pages non originales [FAIT — règles communautaires]. Catalogue et Pins produit réservés aux
  marchands approuvés (politique de retour visible ; ni affiliés ni grossistes) ; nouvelles règles marchands au
  12/11/2026 [FAIT].
- Actions : mots-clés exacts sans bourrage ; une nouvelle URL = un nouveau Pin ; visuels verticaux avec texte ;
  pages d'arrivée originales ; canal lent mais durable (déco, mode, cadeaux, DIY, mariage).

**X** : mécanisme en section 1 ; posts originaux (seuls éligibles au créneau de test) ; échanges avec les comptes
mutuels de la niche ; canal secondaire pour la plupart des boutiques grand public françaises.

**Reddit** (code de 2017, archivé ; usage actuel non vérifié) : « hot » = log10(votes nets) + âge ÷ 45 000 s → 12,5 h
d'écart valent un facteur 10 de votes : la fraîcheur compte énormément ; commentaires « best » = borne inférieure de
Wilson → 10 votes positifs sur 10 passent devant 50 sur 55. Actions : publier aux heures actives de la communauté,
répondre tôt et utilement, aucune promo qui attire des votes négatifs.

**Google** : utilise des données d'interaction agrégées (clics satisfaits ou non) [FAIT — Google ; fuite de 2024 avec
la mise en garde de Google] → un title qui tient sa promesse et une page qui répond tout de suite (module 06).

## 4. Formats e-commerce à tester [CONSENSUS praticiens — à valider par tes données]

| Format | Mécanique | Exemple |
|---|---|---|
| Démonstration « satisfaisante » | Rétention par le geste | Gros plan du produit en action |
| Problème → solution | Identification | Le geste raté, puis le geste réussi avec le produit |
| Avant / après | Preuve visuelle | Même cadre, même lumière |
| Point de vue (POV) | Projection | « POV : tu découvres que… » |
| Test de résistance | Curiosité, preuve | Mesures en cm, kg, minutes |
| 3 erreurs ou 3 astuces | Utilité, enregistrements | Erreurs d'usage courantes |
| Coulisses | Confiance | Préparation des colis, choix du fournisseur |
| Réponse à un commentaire | Communauté, réponses | Vidéo en réponse à une vraie question |
| Comparatif honnête | Décision | Critères mesurés, sans dénigrer |
| Contenu client (UGC) | Preuve sociale | Avec accord écrit du client |
| Carrousel (Instagram, TikTok) | Enregistrements, envois | Empilement de valeur, problème puis preuve, astuces nommées, démonstration |

Piliers : 3 à 5 thèmes (éduquer, inspirer, divertir) avec une part fixée ; rétro-ingénierie à la main de 10 à 20
comptes de la niche (leurs 10 % de contenus les plus performants) — jamais de collecte automatisée.

## 5. Script type (20 à 35 secondes)

| Temps | Bloc | Contenu |
|---|---|---|
| 0–2 s | Accroche | Image du résultat + texte à l'écran |
| 2–8 s | Problème | Situation vécue par la cible |
| 8–22 s | Démonstration | Produit en action, plans courts |
| 22–28 s | Preuve | Mesure, comparaison, retour client réel |
| 28–35 s | Appel à l'action | « Lien en bio » ou « détails dans le profil », sans fausse urgence |

**Banque d'accroches (modèles à remplir, jamais mensongers)** : « Arrête de [erreur courante] avec ton [objet]. » ·
« J'ai testé [produit] pendant [durée]. Résultat : » · « Ce que personne ne t'explique sur [problème]. » ·
« POV : [situation de la cible]. » · « [Résultat mesuré] en [durée], sans [contrainte]. » · « Tu fais encore [geste]
comme ça ? » · « Le [objet] qui règle [problème] en [durée]. » · Accroches visuelles : chute, débordement, déchirure,
geste raté → réussi.

À bannir : « Tague un ami », « Commente OUI », vulnérabilité fabriquée, une phrase par ligne, tics d'écriture IA
(« Ce n'est pas X, c'est Y », « Le résultat ? », « Dites adieu à »).

## 6. Production

- **Rythme** : régulier et soutenable — par exemple 1 vidéo par jour sur la plateforme principale pendant 30 jours,
  chacune avec une idée nouvelle ; la régularité compte plus que la perfection [HYPOTHÈSE à calibrer]. Pas de rafales
  de variantes (section 2).
- **Par lots** : une séance = 6 à 10 idées différentes tournées ; montage le même jour.
- **Recyclage multi-plateforme** : réexporter sans filigrane ; **remonter chaque version avec une musique dont la
  licence couvre la plateforme visée** (les sons « commerciaux » de CapCut ne valent que pour CapCut et TikTok ; ses
  sons standard sont réservés à un usage non commercial) [FAIT — conditions de CapCut] ; bibliothèques musicales
  commerciales des comptes professionnels de chaque plateforme.
- **Outils gratuits** : caméra du téléphone, lumière du jour, micro-cravate bon marché ; montage : CapCut (attention à
  sa licence sur tes contenus), DaVinci Resolve (gratuit, sans les fonctions d'IA) ; visuels : Canva gratuit (usage
  commercial permis, sauf sa musique « populaire »).
- **Planification** : outils natifs des plateformes (planificateurs de TikTok, Meta, Pinterest, YouTube Studio) ; le
  cerveau prépare légendes, mots-clés et calendrier (module 14).
- **Lien en bio** : TikTok l'ouvre à partir de 1 000 abonnés ou avec un compte professionnel enregistré (Profil ›
  Modifier le profil › Liens), pas dans tous les pays [FAIT* — aide TikTok, page non datée] ; ailleurs, conditions à
  lire dans « Modifier le profil » ; plan B : nom de domaine court affiché dans la vidéo.

## 7. Boucle d'analyse (hebdomadaire)

| Indicateur | Lecture |
|---|---|
| % de spectateurs encore présents après 3 s | Qualité de l'accroche |
| Durée moyenne de visionnage, taux de complétion | Qualité du rythme |
| Envois et partages pour 1 000 vues | Potentiel de diffusion hors abonnés |
| Enregistrements pour 1 000 vues | Utilité perçue |
| Visites du profil → clics sur le lien (UTM) | Intention |
| Sessions et ventes par UTM | Résultat business |
| Présence dans Google (propriétés TikTok, Instagram, YouTube de la Search Console) | Vues gagnées hors plateforme |

Règles de décision [HEURISTIQUES] : abandonner un angle après 5 vidéos sous la médiane de rétention du compte ; bonne
rétention mais peu de clics → retravailler l'appel à l'action et la page d'arrivée ; décliner en série (idées
nouvelles, même angle) ce qui génère le plus d'envois. Consigner chaque semaine dans le cerveau (`brain obs`).

## 8. Mythes à corriger

1. « 1 signalement annule 468 J'aime », « 1 réponse vaut 27 J'aime » : faux, les poids portent sur des probabilités.
2. « Les abonnés ne comptent pas » : pas un facteur direct sur TikTok, mais la moitié du fil de X vient des comptes
   suivis et le hors-réseau y est décoté.
3. « X pénalise les liens » : aucune pénalité explicite dans le code.
4. « Plus on poste, plus on touche » : chaque contenu supplémentaire d'un même auteur est décoté.
5. « La golden hour de 60 minutes » : aucune source ; ce qui est documenté, c'est l'apprentissage en quelques minutes
   et les fenêtres de test des premières heures.
6. « Les hashtags font la portée » : faux.
7. « Google n'utilise pas les clics » : faux.

## 9. Règles légales

- Créateurs rémunérés (argent ou produit offert) : mention « Publicité » ou « Collaboration commerciale » claire
  (ou mention équivalente adaptée au format) pendant toute la promotion (loi n° 2023-451, art. 5-2) ; « Images
  retouchées » (silhouette ou visage modifiés) et « Images virtuelles » (visage ou silhouette produits par IA) :
  art. 5, I.
- Personnes, avis ou images générées par IA : jamais présentés comme de vrais clients (C. conso., art. L121-4, 28°).
- Musique et images : droits pour un usage commercial sur chaque plateforme (section 6).
- Aucune automatisation des publications, J'aime, commentaires ou messages (conditions des plateformes, module 14).
