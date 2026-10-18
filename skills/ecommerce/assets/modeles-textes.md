# Modèles de textes prêts à adapter

À personnaliser à chaque fois : un texte copié tel quel se repère, et une plateforme pénalise les contenus en double.
Remplace chaque [CROCHET], supprime ce qui ne s'applique pas, puis passe le texte dans
`python scripts/relire_texte.py texte.txt --type fiche|email|post|annonce` avant de le publier : un 🔴 bloque, un ⚠
demande la preuve. Les règles derrière ces modèles sont dans les modules 03 (fiche), 04 (messages), 08 (e-mails,
avis), 10 (droit) et 16 (marketplaces).

## 1. Fiche produit (structure qui répond avant qu'on pose la question)

**Titre** (50 à 70 caractères) : [Produit] [attribut clé] – [usage ou bénéfice] [taille ou contenance]
> Ex. : Plaid en lin lavé 130 x 170 cm – doux dès le premier jour

**Accroche** (1 à 2 phrases, le résultat pour la personne) :
> [Ce que le produit change concrètement], sans [frein principal levé].

**Pourquoi il vous plaira** (3 à 5 puces, chacune = un bénéfice + sa preuve) :
- [Bénéfice] : [fait vérifiable : matière, mesure, test, certification et son numéro]
- [Bénéfice] : [fait vérifiable]
- [Bénéfice] : [fait vérifiable]

**Caractéristiques** : dimensions [cm], poids [g ou kg], matière ou composition [en %], couleurs, entretien
[température, séchage], origine [lieu de fabrication réel], contenu du colis.

**Livraison et retours** : expédié sous [X] jours ouvrés, livré en [X à Y] jours ([transporteur], suivi) ; livraison
[gratuite dès X € / X €] ; 14 jours pour changer d'avis (droit de rétractation) ; retour [gratuit / à vos frais :
X €] ; remboursement sous 14 jours.

**Questions fréquentes** (les vraies : messages reçus, avis, recherches « Autres questions posées »)
- [Question] → [réponse courte et exacte]

**Garanties** : garantie légale de conformité de 2 ans et garantie des vices cachés (détails dans nos CGV) ; [garantie
commerciale éventuelle : durée, conditions, démarches].

## 2. FAQ de la boutique (page dédiée, reprise en partie sur les fiches)

- **Quand vais-je recevoir ma commande ?** Expédition sous [X] jours ouvrés, livraison en [X à Y] jours en France
  métropolitaine ; vous recevez un numéro de suivi par e-mail.
- **Combien coûte la livraison ?** [Tarifs] ; affichée avant le paiement, jamais ajoutée ensuite.
- **Puis-je changer d'avis ?** Oui : vous avez 14 jours après réception pour vous rétracter, avec le bouton « Renoncer
  au contrat ici » [emplacement : pied de page, espace client] ou le formulaire de rétractation de nos CGV. Retour
  [gratuit / à vos frais], remboursement sous 14 jours.
- **Mon produit a un défaut, que faire ?** Écrivez-nous à [adresse e-mail] avec une photo : la garantie légale de
  conformité couvre les défauts pendant 2 ans (réparation ou remplacement, sinon remboursement).
- **Quels moyens de paiement ?** [Carte bancaire, PayPal…] ; paiement sécurisé par [prestataire], nous ne voyons jamais
  vos données bancaires.
- **Qui êtes-vous ?** [Prénom], [ville ou région], [ce que vous faites et depuis quand] ; [lien vers À propos].
- **En cas de litige ?** Contactez-nous d'abord ; à défaut, médiateur de la consommation : [nom, site, adresse].

## 3. E-mails automatiques (avec consentement ; un objet court, un seul appel à l'action)

### 3.1 Bienvenue (juste après l'inscription)
**Objet** : Bienvenue chez [Boutique] ([ce qui a été promis à l'inscription])
> Bonjour [Prénom],
> Merci de nous avoir rejoints. Comme promis : [guide, code de bienvenue réel et ses conditions, accès anticipé].
> Ce que nous faisons : [une phrase sur le produit et pour qui].
> Notre meilleure porte d'entrée : [produit] – [bénéfice principal]. [Voir le produit]
> À bientôt, [Prénom], [Boutique]
> Pour ne plus recevoir nos e-mails : [lien de désinscription]

### 3.2 Bienvenue, J+2 (l'histoire et la preuve)
**Objet** : Pourquoi nous fabriquons [produit] comme ça
> [3 à 5 phrases : le problème que vous avez vécu, ce que vous avez changé, comment c'est fait, avec une photo
> d'atelier ou de préparation.] Ce qu'en disent nos clients : « [extrait d'avis réel, avec accord] » – [Prénom], [date].

### 3.3 Panier abandonné (1 h après, puis 24 h après au plus)
**Objet** : Votre panier vous attend
> Bonjour [Prénom], vous avez laissé [produit] dans votre panier. Il est toujours disponible. [Reprendre ma commande]
> Une question avant de commander (taille, délai, matière) ? Répondez simplement à cet e-mail.

Deuxième relance (24 h) : répondre à l'objection la plus fréquente (livraison, retours, taille) ; aucune fausse
urgence (« plus que 2 » seulement si c'est vrai à l'instant de l'envoi).

### 3.4 Après l'achat
- **Expédition** : numéro de suivi, délai, contact.
- **J+2 après réception** : conseil d'usage ou d'entretien qui évite la déception.
- **J+7 à J+14 après réception : demande d'avis** (section 4).
- **Réachat** (selon le cycle du produit) : [produit complémentaire ou recharge], sans pression.

## 4. Demande d'avis (neutre, la même pour tous les acheteurs)

**Objet** : Votre avis sur [produit]
> Bonjour [Prénom],
> Vous avez reçu [produit] il y a quelques jours. Votre avis aide d'autres personnes à choisir, qu'il soit positif ou
> non : [lien vers la page d'avis].
> Un souci avec votre commande ? Répondez à cet e-mail, nous le réglons.
> Merci, [Prénom], [Boutique]

Interdits : demander une note précise, trier les clients avant de les inviter, offrir une contrepartie, conditionner un
remboursement à la modification d'un avis.

## 5. Réponse publique à un avis négatif (sous 48 h, sans donnée personnelle)

> Bonjour [Prénom ou pseudo], merci d'avoir pris le temps d'écrire. [Reconnaître le problème précis, sans se justifier
> longuement.] [Ce qui a été fait ou proposé : échange, remboursement, correction de la fiche.] Nous vous avons écrit
> pour régler cela. [Ce qui change désormais pour tous les clients.] [Prénom], [Boutique]

## 6. Messages individuels (un par un, personnalisés ; jamais en masse)

### 6.1 Réseau proche, au lancement
> Salut [Prénom] ! Je lance [Boutique] : [produit] pour [qui], fait [comment]. Si tu connais quelqu'un que ça pourrait
> aider, ou si tu veux me donner ton avis franc sur la page ([lien]), ça m'aiderait beaucoup. Merci !

### 6.2 Micro-créateur (collaboration)
> Bonjour [Prénom], j'ai vu votre vidéo sur [sujet précis] : [ce qui vous a plu, concrètement]. Je fabrique [produit]
> pour [public commun]. Seriez-vous d'accord pour le tester ? Je vous l'envoie sans engagement de publication. Si vous
> en parlez, ce sera avec la mention « Collaboration commerciale », comme la loi l'exige pour un produit offert.
> [Prénom], [Boutique], [lien]

Au-delà de 1 000 € HT d'avantages par objectif, contrat écrit obligatoire (module 10).

### 6.3 Boutique complémentaire (partenariat)
> Bonjour [Prénom], je tiens [Boutique] ([produit]) ; nos clientes et clients se ressemblent sans que nous soyons
> concurrents. Je vous propose [encart réciproque dans les colis / jeu-concours commun avec règlement / article croisé].
> Qu'en pensez-vous ? Je peux vous envoyer un exemple concret.

Vérifier avant les encarts dans les colis que les conditions de la marketplace l'autorisent (module 16).

### 6.4 Presse locale ou blog spécialisé
**Objet** : [Ville] : [fait nouveau et vérifiable, en une ligne]
> Bonjour [Prénom], [en 3 phrases : qui, quoi, pourquoi maintenant, le lien avec la ville ou le sujet du média].
> Photos libres de droits et échantillon disponibles. [Prénom], [téléphone], [lien vers un dossier de presse d'une page]

## 7. Contribution utile dans une communauté (Reddit, forum, groupe)

> [Réponse complète à la question posée, avec l'expérience vécue : étapes, erreurs à éviter, mesures.]
> [Si la règle du groupe l'autorise et seulement si on le demande : « je fabrique ce type de produit, je peux vous
> mettre le lien en message ».]

Jamais de lien dans le premier message, jamais le même texte dans plusieurs groupes.

## 8. Annonces de marketplace (statut professionnel déclaré)

**Titre** : [Marque] [type de produit] [modèle] [taille] [couleur] [état]
> Ex. : Veste en jean [Marque] taille 38 bleu délavé – très bon état

**Description** :
> [État exact avec défauts visibles en photo.] Dimensions à plat : [aisselle à aisselle, longueur] cm. Matière :
> [composition]. [Pourquoi cet article : coupe, usage.] Envoi sous [X] jours, emballage [réemployé, protégé].
> Vendeur professionnel : [Boutique].

Photos : 5 au moins, lumière du jour, fond neutre, étiquette, détails, défauts.

## 9. Page « Renoncer au contrat ici » (fonction de rétractation, depuis le 19/06/2026)

**Intitulé du lien ou du bouton** : Renoncer au contrat ici
> Vous avez commandé chez [Boutique] il y a moins de 14 jours (après réception) ? Vous pouvez renoncer à votre achat.
> Nom : [champ] · Prénom : [champ] · Numéro de commande : [champ] · Adresse e-mail pour l'accusé de réception : [champ]
> **[Bouton : Confirmer la rétractation]**

**Accusé de réception** (envoyé tout de suite par e-mail) :
> Bonjour [Prénom], nous avons bien reçu le [date] à [heure] votre rétractation pour la commande [numéro] : [contenu
> de la demande]. Pour le retour : [adresse, modalités, frais]. Remboursement sous 14 jours après réception de votre
> demande (nous pouvons attendre le retour du produit). [Boutique], [coordonnées]

Libellés exacts et contenu : module 10 (art. L221-21 et D221-5) ; contrôle : `audit_site.py --conformite`.

## 10. Mode agence : premier message à une boutique (B2B, adresse professionnelle)

**Objet** : [Boutique] : [un constat précis vu sur le site]
> Bonjour [Prénom], en regardant [Boutique], j'ai remarqué [constat vérifiable : fiches sans livraison affichée,
> robots des assistants IA bloqués, titres en double…]. Cela peut coûter [effet concret, sans chiffre inventé]. Je
> vous propose un audit gratuit de 15 minutes, sans engagement : je vous envoie le rapport, vous en faites ce que vous
> voulez. [Prénom], [entreprise], [site]
> Vous ne souhaitez plus recevoir de message de ma part ? Répondez « stop ».

Un message par boutique, lié à son activité, avec droit d'opposition (module 11). Rapport : `audit_site.py --complet
--rapport audit.md` puis `assets/modele-rapport-audit.md`.
