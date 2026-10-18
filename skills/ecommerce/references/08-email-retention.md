# Module 08 — E-mails, avis, fidélisation, parrainage

Un client acquis à la sueur doit racheter et en amener d'autres : sans pub, la rétention est le canal le moins cher.

## 1. Outils à 0 €

- **Shopify Messaging** (anciennement Shopify Email) : les 10 000 premiers e-mails de chaque mois sont gratuits, puis
  facturation au volume [FAIT — fiche de l'app sur l'App Store Shopify, consultée le 18/10/2026]. Les automatisations
  natives (panier abandonné, bienvenue) suffisent pour démarrer.
- **Hors Shopify (chemin 0 €, module 13)** : un service d'e-mailing avec plan gratuit (quotas journaliers ou plafond
  de contacts) — comparer au moment du besoin [À VÉRIFIER : quotas en vigueur] ; à défaut, la liste se constitue quand
  même (formulaire du site, export des commandes) et les e-mails partent à la main, un par un, tant que le volume est
  faible.
- **Avis** : Judge.me, plan « Forever Free » avec avis produits et boutique illimités, avis photo et vidéo, demandes
  d'avis automatisées [FAIT — fiche App Store Shopify, consultée le 18/10/2026] ; la synchronisation des avis avec
  Google Shopping est payante [FAIT — tarifs Judge.me].
- Shopify Messaging n'est pas inclus dans un plan Starter ; SMS et WhatsApp y sont payants.

## 2. Consentement (CPCE, art. L34-5 ; CNIL)

- Particuliers : prospection par e-mail ou SMS seulement avec consentement préalable (case non précochée, finalité
  claire).
- Exception : clients ayant déjà acheté, pour des produits ou services analogues, avec possibilité de s'opposer dans
  chaque message.
- Une création de compte sans achat ne fait pas de la personne un client : le consentement reste requis (exemple de
  la CNIL, délibération SAN-2021-008).
- Lien de désinscription fonctionnel dans chaque e-mail ; identité de l'expéditeur claire.

## 3. Capter dès le premier visiteur

| Aimant | Pour quelle boutique | Coût |
|---|---|---|
| Guide utile (entretien, choix de la bonne taille, erreurs à éviter) | Produits techniques, cadeaux, beauté | Temps |
| Quiz « trouve ton produit » (3 à 5 questions, résultat par e-mail) | Catalogue de plus de 5 produits | Temps |
| Accès anticipé à un lancement ou à une édition limitée réelle | Marques, créateurs, drops | 0 € |
| Code de bienvenue | Toutes ; il coûte de la marge : le calculer (`scripts/unit_economics.py`) | Marge |
| Liste d'attente produit (précommande avec date annoncée) | Validation d'un produit (module 15) | 0 € |

Emplacements : section d'inscription du thème (pied de page, page dédiée), page de remerciement après achat, bio des
réseaux. Pas de pop-up plein écran à l'arrivée sur mobile (module 03).

## 4. Flows par ordre de priorité

| Flow | Déclencheur | Séquence de départ [HYPOTHÈSE à tester] | Objectif |
|---|---|---|---|
| Panier ou checkout abandonné | Checkout non finalisé | 1 h, 24 h, 72 h | Lever l'objection (frais, délais, retours, questions), sans fausse urgence |
| Bienvenue | Inscription | J0 promesse et aimant ; J2 histoire et preuve ; J5 produits héros ou guide | Première commande |
| Post-achat | Commande | Confirmation et mode d'emploi ; conseils d'usage ; demande d'avis quelques jours après la réception (selon le temps d'usage du produit) | Satisfaction, avis, réachat |
| Réachat ou accessoire | Fin du cycle d'usage (consommable, recharge) | 1 rappel utile | Deuxième commande |
| Réactivation | Pas d'achat depuis 1 à 2 cycles d'usage (60 à 90 jours selon le produit) | 2 e-mails | Retour |
| Réassort | Produit attendu de retour en stock (inscription volontaire) | 1 e-mail | Vente récupérée |
| Extinction | 90 à 180 jours sans ouverture ni clic | 1 dernier e-mail, puis retrait de la liste | Délivrabilité |

Plus tard : navigation abandonnée (seulement pour un visiteur identifié qui a consenti aux traceurs), anniversaire,
clients fidèles. Premier achat et réachat reçoivent des post-achats différents.

Règles : un e-mail = une idée = un appel à l'action ; objet clair, qui correspond au contenu (jamais de faux « Re: »
ou « Fwd: ») ; texte court, lisible sur mobile ; aucune fausse urgence (« dernière chance » seulement si c'est vrai) ;
mesure : taux de clic et ventes attribuées, pas seulement l'ouverture (faussée par la protection de la vie privée des
messageries).

## 5. Avis clients

- Collecte : e-mail après réception ; inviter les photos et vidéos ; répondre à chaque avis.
- **Même invitation pour tous les acheteurs** (jamais de tri pour écarter les mécontents) ; demande neutre, sans
  « 5 étoiles » ni texte pré-rédigé ; aucune contrepartie pour un avis Google ou Trustpilot ; jamais de remboursement
  conditionné à la modification d'un avis ; réponse publique sans aucune donnée personnelle ; réutilisation d'un avis
  avec l'accord de son auteur, sans fusionner deux avis [CONSENSUS — règles des plateformes d'avis].
- Ni sélection des seuls avis positifs, ni avis inventé, ni avis modifié, ni avis contre récompense présenté comme
  spontané (C. conso., art. L121-4, 27° et 28°).
- Informations obligatoires [FAIT — C. conso., art. L111-7-2 et D111-17 à D111-19, décret n° 2017-1436] : à proximité
  des avis, la date de publication (et de mise à jour), la date de l'expérience de consommation et l'existence ou non
  d'un contrôle ; dans une rubrique dédiée, le fonctionnement du contrôle ; information de l'auteur en cas de refus de
  publication.
- Avis négatif : répondre avec des faits et une solution ; c'est une preuve de sérieux pour les futurs acheteurs et une
  source de corrections (fiche, emballage, délais).
- Balisage AggregateRating seulement si les avis sont réels et visibles sur la page (module 06).

## 6. Fidélisation et parrainage à 0 €

- **Parrainage simple** : un code par client ambassadeur (créé à la main ou par le module de remises de la
  plateforme) ; récompense double (parrain et filleul) calculée sur la marge, pas sur le prix. Boucle : déclencheur
  (colis reçu, avis laissé, 2e achat) → partage en un clic avec un message pré-rédigé → achat du filleul →
  récompense ; règles anti-fraude écrites. Un ambassadeur qui publie son lien signale la contrepartie [HYPOTHÈSE de
  prudence, loi n° 2023-451].
- **Contenu après achat** : entretien, usages, astuces — c'est aussi du contenu vidéo réutilisable (module 05).
- **Communauté légère** : canal de diffusion (Instagram, WhatsApp) ou groupe si la niche s'y prête ; pas de messages
  promotionnels à des personnes qui ne l'ont pas demandé.
- **Avantage sur le 2e achat**, calculé sur la marge (module 02).
- **Contenu client (UGC)** : demander l'autorisation écrite avant toute réutilisation d'une photo ou d'une vidéo de
  client.

## 7. Mesure

Revue mensuelle : part du CA venant des e-mails, taux de réachat à 60 et 90 jours, note moyenne et nombre d'avis,
désinscriptions par envoi. Les tests d'objet ou de contenu ne concluent qu'avec des volumes suffisants (module 03).
