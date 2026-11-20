"""Rappel automatique mesuré sur un cerveau d'essai réaliste (fictif) : 213 nœuds (5 projets : boutique de thé en ligne,
chaîne YouTube de bricolage, recherche d'emploi, trading, PC Windows ; et la mémoire globale), 62 questions en français
naturel dont on connaît le bon souvenir (paraphrases, fautes, sans accents, verbes conjugués, 2-3 mots, trois phrases,
dates, noms, mots anglais, dossier du projet ou non) et 38 messages qui ne doivent rien rappeler.

Chaque message passe par le hook UserPromptSubmit lui-même (`hooks.run("prompt")`, ce que lance
`python -I -S brain.py hook prompt`, avec le JSON que Claude Code envoie sur stdin), dans une session neuve, depuis le
dossier de son projet ou un dossier neutre. Le test imprime hit@1, hit@3 et les faux rappels et les compare à des
planchers. L'horloge est figée au vendredi 20/11/2026 à 10 h (âge des souvenirs, « hier », « la semaine dernière ») :
mêmes chiffres à chaque lancement, quel que soit le jour.

Lancement : python tests/test_rappel.py            (sortie : « N vérifications OK, M échec(s) »)
            python tests/test_rappel.py --detail   (en plus : chaque question manquée et ce qui a été montré)
            python tests/test_rappel.py --mesure   (une ligne de chiffres, sans vérifications : `brain bench`)"""
import datetime as _dtm
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
NOW = (2026, 11, 20, 10, 0, 0)  # a Friday: « la semaine dernière » is 09/11-15/11, « le mois dernier » is October

# Floors of the benchmark (measured values: the test fails if recall gets worse). Hit counts are out of the 62
# questions, false recalls out of the 38 negatives; then the long messages added after the audit (8 questions, 16
# negatives).
FLOOR_HIT1, FLOOR_HIT3, MAX_FALSE = 56, 58, 2
FLOOR_LONG_HIT3, MAX_LONG_FALSE = 8, 1
FLOOR_OBS = 4  # observations noted at the end of a task, found by the 4 questions that only they answer

PROJECTS = [  # (key, title, description): the project folders are created under the test folder
    ("boutique", "Boutique Maison Yuzu", "Boutique en ligne Shopify de thé japonais (matcha, hojicha) et d'accessoires "
     "(théières en fonte, bols, fouets). Lancée en 2025, micro-entreprise."),
    ("youtube", "Chaîne YouTube L'Établi", "Chaîne YouTube de bricolage et de menuiserie pour débutants : une vidéo "
     "longue par semaine, plans PDF vendus à côté."),
    ("emploi", "Recherche d'emploi", "Recherche confidentielle d'un poste de chef de projet digital / e-commerce à Lyon "
     "ou en télétravail."),
    ("trading", "Trading", "Swing trading sur actions (PEA) et un peu de crypto, avec des règles de risque strictes."),
    ("pc", "Optimisation PC Windows", "Réglages, pannes résolues et entretien du PC fixe sous Windows 11 (jeu, montage vidéo)."),
]

LONG_IMPORT = (
    "Étapes pour entrer une commande fournisseur dans Shopify sans casser le stock. 1) Créer le bon de commande dans "
    "Produits > Bons de commande avec le fournisseur (Marukyu ou Atelier Sato) et la date d'arrivée prévue. 2) Saisir les "
    "quantités commandées et le coût unitaire en yens convertis au taux du jour du virement Wise. 3) À la réception du "
    "colis, compter les pièces et cliquer sur « Recevoir l'inventaire » : ne jamais modifier le stock à la main, sinon le "
    "coût moyen pondéré devient faux. 4) Ajouter les frais de port et de douane dans la colonne « Ajustements de coût » "
    "pour que la marge affichée soit la vraie. 5) Archiver le bon de commande et noter le numéro de suivi DHL dans le "
    "tableau des ventes. Erreur déjà faite en juin : stock modifié à la main, marge affichée de 71 % au lieu de 58 %.")

LONG_TOURNAGE = (
    "Liste de contrôle avant chaque tournage du samedi. La veille : charger les deux batteries de la caméra et le micro, "
    "vider la carte SD, imprimer les plans, préparer le bois débité à dimension pour ne pas perdre de temps à l'image. "
    "Le matin : éteindre le néon de l'atelier, allumer les deux panneaux LED à 5600 K, régler la balance des blancs sur "
    "une feuille blanche, vérifier le niveau du micro en parlant fort près de la scie. Pendant : faire un clap à chaque "
    "prise, filmer chaque étape en plan large puis en gros plan, dire à voix haute les cotes. Après : copier les rushs "
    "sur le deuxième SSD et sur le NAS avant de formater la carte. Oubli fréquent : le plan de coupe filmé du dessus.")

LONG_VALMONT = (
    "Entretien du 21/10/2026 chez Groupe Valmont avec la directrice marketing et le DSI. Questions posées : 1) Racontez "
    "un projet qui a mal tourné et ce que vous avez changé ensuite. 2) Comment arbitrez-vous entre le marketing qui veut "
    "aller vite et la technique qui veut faire propre ? 3) Quel budget maximum avez-vous géré seul ? 4) Comment "
    "gérez-vous un prestataire en retard ? 5) Avez-vous déjà encadré une équipe de plus de cinq personnes ? Ma réponse à "
    "la question 5 était faible (équipe de 4 seulement) : c'est le motif du refus. À préparer pour la prochaine fois : "
    "parler de la coordination des 9 personnes pendant la migration ERP, même sans lien hiérarchique.")

LONG_DIMANCHE = (
    "Routine du dimanche soir pour préparer la semaine de bourse. 1) Regarder la tendance du CAC 40 et du S&P 500 en "
    "hebdomadaire : si les deux sont sous leur moyenne mobile 50 jours, aucun nouvel achat. 2) Passer le filtre "
    "Zonebourse : actions au plus haut de 20 jours avec volume supérieur à la moyenne. 3) Garder cinq titres au plus dans "
    "la liste de surveillance et tracer les niveaux d'entrée et de stop sur TradingView. 4) Calculer la taille de chaque "
    "position avec la règle des 150 € de risque. 5) Poser les alertes de prix. 6) Relire le journal de la semaine "
    "passée et noter une seule chose à corriger. Durée : 45 minutes, pas plus.")

LONG_REINSTALL = (
    "Réinstallation propre de Windows 11, faite le 18/01/2026. Avant : sauvegarde complète avec Veeam, export des "
    "favoris, liste des logiciels (winget export), clé BitLocker notée. Création de la clé USB avec l'outil Media "
    "Creation Tool. Pendant l'installation : débrancher le deuxième SSD pour que le chargeur de démarrage n'aille pas "
    "dessus, supprimer toutes les partitions du SSD système, compte local d'abord. Après : pilotes de la carte mère "
    "depuis le site MSI (chipset AMD en premier), puis pilote Nvidia, puis Windows Update. Réglages à refaire : plan "
    "d'alimentation Performances élevées, démarrage rapide désactivé, optimisations plein écran désactivées, fichier "
    "d'échange à 16 Go. Durée totale : 2 h 30. Gain : démarrage passé de 31 à 14 secondes.")

# (key, type, project key or None, title, body, importance, age in days, options); options: status="archived",
# upd=<age of the last change>, dup=<key of the memory it nearly repeats>.
MEMORIES = [
    # ------------------------------------------------------------------ boutique
    ("b01", "fact", "boutique", "Délai de livraison du fournisseur Atelier Sato",
     "L'atelier Sato (Kyoto) expédie les théières en fonte sous 12 jours ouvrés, par DHL Express. Prévoir 3 semaines "
     "avant une promotion pour être livré à temps.", 4, 40, {}),
    ("b02", "fact", "boutique", "Délai de livraison du fournisseur Atelier Sato (ancien)",
     "L'atelier Sato livre en 21 jours ouvrés par bateau.", 3, 300, {"status": "archived"}),
    ("b03", "decision", "boutique", "Transporteur par défaut : Mondial Relay",
     "Depuis octobre 2026 les colis de moins de 2 kg partent en Mondial Relay (4,40 €) au lieu de Colissimo (6,90 €). "
     "Pourquoi : la marge sur les petits paniers était mangée par le port. Colissimo reste proposé en option pour la "
     "livraison à domicile.", 4, 35, {}),
    ("b04", "fact", "boutique", "Seuil de livraison gratuite",
     "Livraison offerte à partir de 49 € d'achat en France métropolitaine. Testé à 39 € en juin : le panier moyen a "
     "baissé, on est revenu à 49 €.", 3, 150, {}),
    ("b05", "fact", "boutique", "Code promo de bienvenue",
     "BIENVENUE10 : 10 % sur la première commande, envoyé par l'email de bienvenue Klaviyo. Non cumulable avec les "
     "soldes.", 3, 200, {}),
    ("b06", "decision", "boutique", "Thème Shopify : rester sur Dawn",
     "On garde le thème Dawn (gratuit) plutôt que d'acheter Impulse à 380 $. Pourquoi : Dawn est rapide et suffisant, "
     "les sections personnalisées couvrent nos besoins.", 3, 250, {}),
    ("b07", "learning", "boutique", "Images produit trop lourdes : passer en WebP",
     "Les photos produit en PNG de 3 Mo ralentissaient la page (LCP 4,8 s). Converties en WebP 1600 px à 82 % de "
     "qualité : LCP 2,1 s. Toujours exporter en WebP avant d'envoyer sur Shopify.", 3, 180, {}),
    ("b08", "fact", "boutique", "Marge cible par produit",
     "Marge brute visée : 62 % sur le thé, 48 % sur les accessoires (théières, bols). En dessous de 40 % on ne "
     "référence pas le produit.", 4, 220, {}),
    ("b09", "fact", "boutique", "Prix du matcha cérémonial 30 g",
     "Vendu 24,90 € TTC (achat 8,10 € chez Marukyu). Prix relevé de 22,90 à 24,90 € en septembre 2026 après la hausse "
     "du fournisseur.", 3, 60, {}),
    ("b10", "fact", "boutique", "Prix du matcha cérémonial 30 g (avant la hausse)",
     "Vendu 22,90 € TTC.", 3, 260, {"status": "archived"}),
    ("b11", "entity", "boutique", "Marukyu — fournisseur de matcha (Uji)",
     "Grossiste de thé à Uji. Contact : M. Tanaka. Minimum de commande 300 €. Paiement par virement Wise, 30 % à la "
     "commande.", 3, 240, {}),
    ("b12", "entity", "boutique", "Atelier Sato — théières en fonte (Kyoto)",
     "Petit atelier familial. Ferme en août. Commandes par email uniquement, en anglais. Minimum 10 pièces par modèle.",
     3, 245, {}),
    ("b13", "fact", "boutique", "Politique de retour",
     "Retours acceptés sous 14 jours, produit non ouvert, frais de retour à la charge du client sauf erreur de notre "
     "part. Remboursement sous 5 jours après réception.", 3, 230, {}),
    ("b14", "learning", "boutique", "Emails de panier abandonné : le 2e message fait l'essentiel",
     "Séquence Klaviyo en 3 emails (1 h, 24 h, 72 h). Le 2e, avec la photo du produit et sans réduction, récupère 9 % "
     "des paniers ; le 3e avec -5 % n'ajoute presque rien. Ne pas brader dès le premier message.", 3, 120, {}),
    ("b15", "fact", "boutique", "Avis clients : Judge.me",
     "Application Judge.me (gratuite) pour les avis. Email de demande d'avis envoyé 10 jours après la livraison. "
     "4,8/5 sur 212 avis en novembre 2026.", 3, 15, {}),
    ("b16", "decision", "boutique", "Pas de vente sur Amazon",
     "Décidé en mars 2026 : on ne vend pas sur Amazon. Pourquoi : commission de 15 %, guerre des prix et perte du "
     "contact client. On reste sur notre site et sur Etsy pour les bols artisanaux.", 3, 250, {}),
    ("b17", "fact", "boutique", "TVA et facturation",
     "Micro-entreprise passée à la TVA en janvier 2026 (seuil dépassé). TVA 5,5 % sur le thé, 20 % sur les accessoires. "
     "Factures générées par l'application Sufio.", 3, 300, {}),
    ("b18", "todo", "boutique", "Préparer la campagne de Noël",
     "Bannière, coffret découverte à 39 €, email le 25/11 et le 08/12. Commander les coffrets chez l'imprimeur avant le "
     "22/11.", 4, 10, {}),
    ("b19", "fact", "boutique", "Meilleure vente : coffret découverte matcha",
     "Le coffret découverte (matcha 30 g + fouet + bol) fait 31 % du chiffre d'affaires. Ne jamais le laisser en "
     "rupture.", 3, 90, {}),
    ("b20", "learning", "boutique", "Fiches produit : le titre SEO doit contenir le grammage",
     "Les fiches dont le titre contient le poids (« Matcha cérémonial 30 g ») se classent mieux sur Google que celles "
     "sans. Mettre aussi l'origine (Uji, Kagoshima) dans la méta-description.", 3, 140, {}),
    ("b21", "fact", "boutique", "Budget publicité Meta",
     "15 € par jour sur Meta Ads, uniquement en reciblage (visiteurs des 30 derniers jours). ROAS moyen 3,4. Les "
     "campagnes d'acquisition à froid ont été coupées en juillet : ROAS 0,9.", 3, 100, {}),
    ("b22", "reference", "boutique", "Tableau de bord des ventes",
     "Feuille Google Sheets « Ventes Maison Yuzu 2026 », un onglet par mois. Mise à jour chaque lundi depuis l'export "
     "Shopify.", 3, 200, {}),
    ("b23", "fact", "boutique", "Chiffre d'affaires d'octobre 2026",
     "Octobre 2026 : 6 480 € de ventes, 187 commandes, panier moyen 34,65 €. +18 % par rapport à septembre.", 3, 18, {}),
    ("b24", "fact", "boutique", "Chiffre d'affaires de septembre 2026",
     "Septembre 2026 : 5 490 € de ventes, 161 commandes, panier moyen 34,10 €.", 3, 48, {}),
    ("b25", "learning", "boutique", "Rupture de stock : activer « prévenez-moi »",
     "Quand un produit est épuisé, le bouton « Prévenez-moi du retour » (Klaviyo Back in Stock) récupère en moyenne "
     "22 % des demandes. À activer sur tous les produits.", 3, 110, {}),
    ("b26", "fact", "boutique", "Emballage : papier kraft et pas de plastique",
     "Colis en carton recyclé, calage en papier kraft froissé, ruban adhésif papier. Engagement affiché sur le site : "
     "zéro plastique.", 3, 280, {}),
    ("b27", "fact", "boutique", "Délai de préparation des commandes",
     "Commandes passées avant 13 h expédiées le jour même, sinon le lendemain. Pas d'expédition le samedi.", 3, 210, {}),
    ("b28", "learning", "boutique", "Photos produit : fond clair et lumière du jour",
     "Les photos prises près de la fenêtre, sur fond en lin clair, convertissent mieux que le fond noir (taux d'ajout "
     "au panier 7,1 % contre 5,3 %).", 3, 170, {}),
    ("b29", "decision", "boutique", "Programme de fidélité reporté à 2027",
     "Pas de programme de points pour l'instant : trop peu de clients récurrents (14 %). À revoir quand on dépassera "
     "300 commandes par mois.", 3, 75, {}),
    ("b30", "fact", "boutique", "Nom de domaine et hébergement des emails",
     "Domaine maison-yuzu.example acheté chez OVH, renouvelé en mars. Emails chez Google Workspace (une boîte).", 2, 290, {}),
    ("b31", "fact", "boutique", "Clients professionnels : remise de 20 %",
     "Les salons de thé et restaurants ont 20 % de remise à partir de 150 € de commande, sur devis. Trois clients pro "
     "actifs, dont le salon Hanami à Lyon.", 3, 130, {}),
    ("b32", "learning", "boutique", "Douane : frais sur les colis du Japon",
     "Au-dessus de 150 € de valeur, les colis du Japon paient droits de douane et TVA à l'import. Demander au "
     "fournisseur de déclarer le code SH 0902 (thé) : taux de 0 %, seule la TVA est due.", 4, 190, {}),
    ("b33", "fact", "boutique", "Objectif 2026 : 80 000 € de chiffre d'affaires",
     "Objectif annuel de 80 000 €. Fin octobre : 54 200 € cumulés. Il faut 12 900 € par mois sur novembre et décembre.",
     4, 17, {}),
    ("b34", "decision", "boutique", "Livraison : on passe à Mondial Relay",
     "Les petits colis partent désormais en point relais Mondial Relay, moins cher que Colissimo.", 3, 33, {"dup": "b03"}),
    ("b35", "fact", "boutique", "Retours et remboursements",
     "Le client a 14 jours pour renvoyer un article non ouvert. Les frais de renvoi sont pour lui. On rembourse dans "
     "les 5 jours.", 3, 100, {"dup": "b13"}),
    ("b36", "fact", "boutique", "Horaires du service client",
     "Réponse aux emails du lundi au vendredi, de 9 h à 17 h. Réponse sous 24 h. Pas de téléphone.", 2, 205, {}),
    ("b37", "learning", "boutique", "Shopify Flow : étiqueter les commandes à risque",
     "Automatisation Flow : toute commande de plus de 200 € avec une adresse de livraison différente de la facturation "
     "reçoit l'étiquette « à vérifier ». A évité deux fraudes en 2026.", 3, 85, {}),
    ("b38", "fact", "boutique", "Nouveau produit : hojicha en vrac 100 g",
     "Lancé le 03/11/2026 à 12,90 €. Thé torréfié de Kagoshima, peu de théine. 41 ventes la première semaine.", 3, 12, {}),
    ("b39", "todo", "boutique", "Renouveler le stock de fouets en bambou",
     "Il reste 18 chasen. Commander 100 pièces chez Marukyu avant fin novembre (délai de 3 semaines).", 3, 6, {}),
    ("b40", "fact", "boutique", "Paiements acceptés",
     "Shopify Payments (carte, Apple Pay) et PayPal. Paiement en 3 fois avec Alma à partir de 100 €.", 3, 215, {}),
    ("b41", "learning", "boutique", "Newsletter : envoyer le jeudi à 18 h",
     "Tests sur 8 envois : le jeudi à 18 h donne 41 % d'ouverture contre 33 % le mardi matin. Objet court, sans emoji.",
     3, 95, {}),
    ("b42", "fact", "boutique", "Blog : un article par mois",
     "Un article de blog par mois (recettes au matcha, guide des thés japonais). L'article « Comment préparer un matcha "
     "sans grumeaux » amène 38 % du trafic Google.", 3, 125, {}),
    ("b43", "learning", "boutique", "Procédure d'import des commandes fournisseur dans Shopify", LONG_IMPORT, 3, 155, {}),
    ("b44", "fact", "boutique", "Concurrents suivis",
     "Trois concurrents surveillés : Thés du Levant, Kumiko Tea, Palais Vert. Kumiko vend le même matcha 27 €.", 3, 160, {}),
    ("b45", "learning", "boutique", "Mondial Relay : étiquettes via Boxtal",
     "Les étiquettes Mondial Relay sont achetées sur Boxtal (pas de contrat direct). Import automatique des commandes "
     "Shopify, 4,40 € jusqu'à 1 kg.", 3, 30, {}),
    ("b46", "fact", "boutique", "Ancien thème : Debut",
     "La boutique tournait sur le thème Debut jusqu'en 2025.", 2, 420, {"status": "archived"}),
    # ------------------------------------------------------------------ youtube
    ("y01", "fact", "youtube", "Rythme de publication",
     "Une vidéo chaque dimanche à 18 h. Un Short le mercredi, tiré de la vidéo précédente.", 4, 200, {}),
    ("y02", "fact", "youtube", "Matériel de tournage",
     "Caméra Sony ZV-E10 avec objectif Sigma 16 mm f/1.4, micro Rode Wireless Go II, deux panneaux LED Neewer. Trépied "
     "Manfrotto.", 3, 300, {}),
    ("y03", "decision", "youtube", "Montage sur DaVinci Resolve",
     "On monte sur DaVinci Resolve (gratuit) et plus sur Premiere Pro : abonnement Adobe arrêté en février 2026 "
     "(26 € par mois économisés).", 3, 270, {}),
    ("y04", "learning", "youtube", "Miniatures : visage et 3 mots maximum",
     "Les miniatures avec mon visage, l'objet fini et 3 mots au plus font 7,4 % de taux de clic, contre 4,1 % pour "
     "celles avec beaucoup de texte. Fond jaune ou bleu vif.", 4, 150, {}),
    ("y05", "fact", "youtube", "Durée idéale d'une vidéo",
     "Les vidéos de 10 à 14 minutes ont la meilleure rétention (48 %). Au-delà de 20 minutes la rétention tombe à 31 %.",
     3, 140, {}),
    ("y06", "fact", "youtube", "Réglages d'export",
     "Export en 4K à 25 images par seconde, H.265, débit 45 Mb/s, audio AAC 320 kb/s. Fichier d'environ 4 Go pour 12 "
     "minutes.", 3, 260, {}),
    ("y07", "fact", "youtube", "Nombre d'abonnés",
     "12 400 abonnés au 15/11/2026. Objectif : 20 000 en juin 2027. +900 abonnés en octobre.", 3, 5, {}),
    ("y08", "fact", "youtube", "Nombre d'abonnés (juin 2026)",
     "8 900 abonnés au 01/06/2026.", 3, 172, {"status": "archived"}),
    ("y09", "entity", "youtube", "Sponsor : Outillage Durand",
     "Partenariat avec Outillage Durand (quincaillerie en ligne) : 450 € par vidéo sponsorisée, une intégration de 60 "
     "secondes, lien affilié à 8 %. Contact : Élodie Marchand. Contrat jusqu'en mars 2027.", 4, 80, {}),
    ("y10", "learning", "youtube", "Les 30 premières secondes décident de tout",
     "Montrer le résultat fini dès les 5 premières secondes puis annoncer les étapes. Les vidéos avec ce début gardent "
     "71 % des spectateurs à 30 s, contre 52 %.", 4, 130, {}),
    ("y11", "fact", "youtube", "Musique : Epidemic Sound",
     "Abonnement Epidemic Sound à 9,99 € par mois. Ne jamais utiliser une musique de la bibliothèque audio YouTube "
     "déjà entendue partout.", 3, 250, {}),
    ("y12", "decision", "youtube", "Pas de vidéo sur l'électricité",
     "On ne fait pas de tutoriel d'électricité (tableau, prises) : risque juridique et de sécurité. Renvoyer vers un "
     "professionnel.", 3, 190, {}),
    ("y13", "fact", "youtube", "Revenus de la chaîne en octobre 2026",
     "AdSense 312 €, sponsor 900 €, affiliation Amazon 87 €. Total 1 299 €.", 3, 16, {}),
    ("y14", "todo", "youtube", "Tourner la vidéo de l'établi pliant",
     "Plans à imprimer, acheter le contreplaqué de 18 mm. Tournage prévu le 23/11.", 3, 4, {}),
    ("y15", "learning", "youtube", "Son : enregistrer en 32 bits flottant",
     "Avec l'enregistreur Zoom F3 en 32 bits flottant, plus de saturation quand la scie circulaire démarre. "
     "Synchroniser avec un clap.", 3, 120, {}),
    ("y16", "fact", "youtube", "Titres : commencer par le bénéfice",
     "Format de titre qui marche : « Fabriquer X en un week-end (sans atelier) ». Moins de 60 caractères.", 3, 135, {}),
    ("y17", "reference", "youtube", "Banque d'idées de vidéos",
     "Liste Notion « Idées vidéos » : 46 idées classées par difficulté. Les trois prochaines : établi pliant, étagère "
     "murale invisible, restauration d'un rabot.", 3, 20, {}),
    ("y18", "learning", "youtube", "Chapitres : indispensables pour les tutoriels",
     "Ajouter des chapitres (00:00 Intro, etc.) augmente la durée de visionnage moyenne de 11 %. Les mettre dans la "
     "description, pas seulement en commentaire épinglé.", 3, 115, {}),
    ("y19", "fact", "youtube", "Description type d'une vidéo",
     "Trois lignes de résumé, liste du matériel avec liens affiliés, chapitres, lien vers les plans PDF (5 € sur "
     "Gumroad).", 3, 180, {}),
    ("y20", "fact", "youtube", "Plans PDF vendus sur Gumroad",
     "Les plans détaillés se vendent 5 € sur Gumroad. 214 ventes depuis janvier 2026. Le plan de l'établi rapporte le "
     "plus.", 3, 60, {}),
    ("y21", "learning", "youtube", "Commentaires : répondre dans les 2 premières heures",
     "Répondre à tous les commentaires dans les 2 heures après la sortie pousse la vidéo dans les recommandations.",
     3, 110, {}),
    ("y22", "decision", "youtube", "Shorts : recycler, ne pas tourner exprès",
     "Les Shorts sont découpés dans la vidéo longue (le moment le plus spectaculaire, 40 s). Tourner des Shorts dédiés "
     "prenait une demi-journée pour 200 abonnés.", 3, 90, {}),
    ("y23", "fact", "youtube", "Audience : 78 % d'hommes de 35 à 54 ans",
     "Public surtout masculin, 35-54 ans, France 81 %, Belgique 9 %, Québec 4 %. Regardé à 62 % sur télévision "
     "connectée.", 3, 70, {}),
    ("y24", "fact", "youtube", "Calendrier de sortie des vidéos",
     "Sortie de la vidéo longue tous les dimanches en fin d'après-midi (18 h).", 3, 60, {"dup": "y01"}),
    ("y25", "learning", "youtube", "Éclairage : éviter le néon de l'atelier",
     "Le néon de l'atelier fait scintiller l'image à 1/50 s. Éteindre le néon, deux panneaux LED à 5600 K, obturateur "
     "à 1/50.", 3, 240, {}),
    ("y26", "fact", "youtube", "Logiciel de miniatures : Canva",
     "Miniatures faites sur Canva Pro avec le modèle « Établi 2026 ». Police Anton, contour blanc de 12 px.", 3, 160, {}),
    ("y27", "learning", "youtube", "Préparation d'un tournage : liste de contrôle", LONG_TOURNAGE, 3, 145, {}),
    ("y28", "fact", "youtube", "Meilleure vidéo : l'établi à 50 €",
     "« Fabriquer un établi solide pour 50 € » : 412 000 vues, 6 100 abonnés gagnés. Sortie en avril 2026.", 3, 100, {}),
    ("y29", "fact", "youtube", "Jour de tournage : le samedi matin",
     "Tournage le samedi de 8 h à 12 h (lumière et calme dans l'atelier). Montage le lundi et le mardi soir.", 3, 195, {}),
    ("y30", "learning", "youtube", "Droits d'auteur : réclamation sur une musique",
     "Une réclamation Content ID sur la vidéo du 12/09 venait d'une musique libre mal déclarée. Contestée avec la "
     "licence Epidemic Sound : levée en 4 jours.", 3, 65, {}),
    ("y31", "todo", "youtube", "Relancer Outillage Durand pour la facture d'octobre",
     "Facture de 900 € envoyée le 02/11, pas encore payée. Relancer Élodie si rien au 25/11.", 3, 3, {}),
    ("y32", "fact", "youtube", "Sous-titres automatiques corrigés à la main",
     "Les sous-titres générés par YouTube sont relus et corrigés (noms d'outils). 15 minutes par vidéo.", 2, 175, {}),
    ("y33", "fact", "youtube", "Communauté : serveur Discord",
     "Serveur Discord « L'Établi » : 640 membres, un salon par projet. Modéré par Thomas.", 3, 55, {}),
    ("y34", "learning", "youtube", "La courbe de rétention chute aux transitions",
     "La rétention chute de 8 points à chaque transition musicale de plus de 5 secondes. Les couper à 2 secondes.",
     3, 105, {}),
    ("y35", "fact", "youtube", "Stockage des rushs",
     "Rushs gardés 6 mois sur le NAS Synology (2 disques de 8 To en miroir), puis supprimés sauf les projets finis "
     "exportés.", 3, 185, {}),
    ("y36", "fact", "youtube", "Idée de série : restaurer des outils anciens",
     "Série de 4 épisodes sur la restauration d'outils chinés en brocante (rabot, varlope, scie à dos). À lancer en "
     "janvier.", 3, 1, {}),
    ("y37", "fact", "youtube", "Ancienne caméra : Canon M50",
     "Les vidéos de 2024 étaient tournées avec un Canon M50.", 2, 500, {"status": "archived"}),
    # ------------------------------------------------------------------ emploi
    ("e01", "fact", "emploi", "Poste recherché",
     "Chef de projet digital / e-commerce, en CDI, à Lyon ou en télétravail complet. Pas de poste purement technique.",
     4, 220, {}),
    ("e02", "fact", "emploi", "Prétentions salariales",
     "Fourchette annoncée : 48 000 à 52 000 € brut annuel. Ne pas descendre sous 45 000 €.", 4, 200, {}),
    ("e03", "entity", "emploi", "Camille Arnaud — recruteuse au cabinet Talentis",
     "Chasseuse de têtes chez Talentis (Lyon). M'a contacté sur LinkedIn en septembre. Très réactive, préfère le "
     "téléphone.", 3, 70, {}),
    ("e04", "fact", "emploi", "Candidature Nordéa Logistique : entretien passé",
     "Entretien avec la DRH le 12/11/2026 pour le poste de chef de projet e-commerce. Bon contact. Deuxième tour avec "
     "le directeur digital prévu début décembre.", 4, 8, {}),
    ("e05", "fact", "emploi", "Candidature Groupe Valmont : refus",
     "Refus reçu le 28/10/2026 après le deuxième entretien : profil jugé trop junior en gestion d'équipe.", 3, 23, {}),
    ("e06", "learning", "emploi", "Entretien : préparer trois exemples chiffrés",
     "Méthode STAR avec trois exemples chiffrés (refonte du site : +27 % de conversion ; migration ERP livrée dans les "
     "délais ; équipe de 4). Les recruteurs retiennent les chiffres.", 4, 150, {}),
    ("e07", "fact", "emploi", "CV : version 2026 en une page",
     "CV refait en une page en mars 2026, modèle sobre. Fichier « CV_2026_chef-de-projet.pdf » dans Documents/Emploi.",
     3, 240, {}),
    ("e08", "fact", "emploi", "Préavis",
     "Préavis de 3 mois dans le poste actuel, négociable à 2 mois selon la RH.", 3, 210, {}),
    ("e09", "reference", "emploi", "Tableau de suivi des candidatures",
     "Feuille Google Sheets « Candidatures 2026 » : entreprise, poste, date, contact, statut. 23 candidatures et 6 "
     "entretiens au 15/11.", 3, 5, {}),
    ("e10", "learning", "emploi", "Lettre de motivation : trois paragraphes",
     "Structure qui marche : vous (leur besoin), moi (une preuve chiffrée), nous (ce que je ferai dans les 90 premiers "
     "jours). 200 mots maximum.", 3, 160, {}),
    ("e11", "learning", "emploi", "LinkedIn : le titre du profil compte",
     "Depuis que le titre est « Chef de projet e-commerce | Shopify, CRM, acquisition », les vues du profil ont doublé "
     "(de 40 à 85 par semaine).", 3, 130, {}),
    ("e12", "fact", "emploi", "Questions à poser en fin d'entretien",
     "Trois questions préparées : comment se mesure la réussite à 6 mois, la taille de l'équipe, le budget du projet.",
     3, 145, {}),
    ("e13", "decision", "emploi", "Refuser les postes à Paris en présentiel",
     "Pas de poste à Paris avec plus de 2 jours de présence par semaine. Raison : famille à Lyon, trajets trop lourds.",
     4, 190, {}),
    ("e14", "todo", "emploi", "Relancer Nordéa Logistique",
     "Si pas de nouvelles au 27/11, relancer la DRH par email.", 3, 2, {}),
    ("e15", "fact", "emploi", "Certification Google Analytics 4",
     "Certification GA4 obtenue le 14/09/2026. À mettre sur le CV et sur LinkedIn.", 3, 66, {}),
    ("e16", "fact", "emploi", "Point faible à travailler : l'anglais oral",
     "Niveau B2 à l'écrit, plus faible à l'oral. Cours sur Preply deux fois par semaine depuis octobre.", 3, 40, {}),
    ("e17", "entity", "emploi", "Julien Perrin — ancien collègue, recommandation",
     "Ancien responsable chez Bricomarché. D'accord pour être contacté comme référence. Joignable par LinkedIn.", 3, 120, {}),
    ("e18", "fact", "emploi", "Sites d'offres suivis",
     "Alertes actives sur Welcome to the Jungle et l'APEC : « chef de projet digital Lyon », « e-commerce manager "
     "télétravail ». Malt pour les missions freelance.", 3, 170, {}),
    ("e19", "learning", "emploi", "Négociation : annoncer la fourchette haute",
     "Annoncer d'abord 52 000 € : les deux dernières propositions sont arrivées à 49 000 et 50 000 €.", 3, 60, {}),
    ("e20", "fact", "emploi", "Disponibilités pour les entretiens",
     "Disponible le mardi et le jeudi après 17 h, ou le vendredi toute la journée (télétravail).", 3, 100, {}),
    ("e21", "fact", "emploi", "Salaire demandé",
     "Je demande entre 48 et 52 k€ brut par an ; plancher 45 k€.", 3, 90, {"dup": "e02"}),
    ("e22", "fact", "emploi", "Mission freelance possible : refonte du site des Jardins de Clara",
     "Devis envoyé le 05/11 : 3 200 € pour la refonte Shopify. Réponse attendue.", 3, 15, {}),
    ("e23", "fact", "emploi", "Situation actuelle",
     "En poste chez Bricomarché Digital comme chargé de projet web depuis 2021. Recherche confidentielle : ne rien "
     "publier sur LinkedIn.", 4, 215, {}),
    ("e24", "learning", "emploi", "Compte rendu de l'entretien Groupe Valmont", LONG_VALMONT, 3, 29, {}),
    ("e25", "fact", "emploi", "Simulation d'entretien du 08/11",
     "Points à améliorer : réponses trop longues (viser 2 minutes), mieux conclure chaque réponse.", 3, 12, {}),
    ("e26", "reference", "emploi", "Modèle d'email de relance après entretien",
     "Email court : remerciement, un point précis de l'échange, disponibilité. À envoyer 24 h après.", 3, 110, {}),
    # ------------------------------------------------------------------ trading
    ("t01", "decision", "trading", "Risque maximum : 1 % du capital par trade",
     "Jamais plus de 1 % du capital risqué par position (stop compris). Capital de trading : 15 000 €, donc 150 € de "
     "perte maximale par trade.", 5, 300, {}),
    ("t02", "decision", "trading", "Pas d'effet de levier",
     "Aucun levier ni produit dérivé (CFD, turbos). Raison : perte de 2 300 € en 2024 sur des CFD.", 5, 310, {}),
    ("t03", "fact", "trading", "Courtier actions : Bourse Direct (PEA)",
     "PEA chez Bourse Direct. Frais : 0,99 € jusqu'à 500 €, 1,90 € jusqu'à 2 000 €. Compte-titres ordinaire chez Trade "
     "Republic.", 3, 280, {}),
    ("t04", "decision", "trading", "Crypto : passage de Binance à Kraken",
     "Compte crypto transféré de Binance à Kraken en mai 2026. Pourquoi : frais plus clairs et retraits SEPA gratuits. "
     "Compte Binance fermé.", 3, 180, {}),
    ("t05", "fact", "trading", "Plateforme crypto : Binance",
     "Achat de bitcoin et d'ether sur Binance.", 3, 400, {"status": "archived"}),
    ("t06", "fact", "trading", "Stratégie : cassure au-dessus de la moyenne mobile 50 jours",
     "Swing trading : achat sur cassure d'un plus haut de 20 jours si le cours est au-dessus de la MM50 et que la MM50 "
     "monte. Sortie si clôture sous la MM20.", 4, 260, {}),
    ("t07", "fact", "trading", "Investissement mensuel programmé",
     "300 € par mois sur l'ETF MSCI World (CW8) dans le PEA, le 5 de chaque mois. Ne pas y toucher avant 2040.", 4, 290, {}),
    ("t08", "learning", "trading", "Ne pas trader les annonces de résultats",
     "Trois pertes sur quatre trades pris la veille de résultats trimestriels. Règle : pas de position ouverte 2 jours "
     "avant une publication.", 3, 140, {}),
    ("t09", "fact", "trading", "Fiscalité : flat tax de 30 %",
     "Plus-values du compte-titres et des cryptos : prélèvement forfaitaire unique de 30 %. PEA : exonéré d'impôt après "
     "5 ans (prélèvements sociaux de 17,2 %).", 3, 230, {}),
    ("t10", "reference", "trading", "Journal de trades",
     "Fichier Excel « Journal_trades_2026.xlsx » : date, titre, entrée, stop, sortie, R obtenu, capture d'écran. Rempli "
     "le soir même.", 3, 250, {}),
    ("t11", "fact", "trading", "Bilan des trades d'octobre 2026",
     "Octobre 2026 : 11 trades, 6 gagnants, +2,8 R au total, soit +420 €. Meilleur trade : Schneider Electric (+2,1 R).",
     3, 17, {}),
    ("t12", "fact", "trading", "Bilan des trades de septembre 2026",
     "Septembre 2026 : 8 trades, 3 gagnants, -1,2 R (-180 €). Trop de trades contre la tendance.", 3, 47, {}),
    ("t13", "learning", "trading", "Stop suiveur : sous le plus bas des 3 derniers jours",
     "Remonter le stop sous le plus bas des 3 dernières bougies journalières dès que le trade gagne 1 R. A transformé "
     "4 petits gains en gros gains.", 3, 120, {}),
    ("t14", "fact", "trading", "Liste de surveillance actuelle",
     "Titres suivis : Schneider Electric, Air Liquide, ASML, Hermès, Vinci. Crypto : bitcoin et ether uniquement.", 3, 9, {}),
    ("t15", "decision", "trading", "Crypto limitée à 10 % du patrimoine financier",
     "Maximum 10 % en cryptomonnaies, bitcoin et ether seulement, pas d'altcoins. Rééquilibrer si ça dépasse 15 %.", 4, 200, {}),
    ("t16", "learning", "trading", "Éviter de trader après une perte",
     "Après deux pertes consécutives : arrêt jusqu'au lendemain. Les trades de revanche ont un taux de réussite de 20 %.",
     4, 160, {}),
    ("t17", "fact", "trading", "Outils d'analyse",
     "Graphiques sur TradingView (abonnement Essential, 13 € par mois). Filtre d'actions sur Zonebourse. Alertes de "
     "prix sur TradingView.", 3, 240, {}),
    ("t18", "fact", "trading", "Horaires de trading",
     "Analyse le soir après 20 h, ordres placés avant l'ouverture. Jamais de trading en journée pendant le travail.", 3, 220, {}),
    ("t19", "fact", "trading", "Déclaration des comptes à l'étranger",
     "Trade Republic (Allemagne) et Kraken (États-Unis) à déclarer chaque année sur les formulaires 3916 et 3916-bis.",
     3, 150, {}),
    ("t20", "learning", "trading", "Taille de position : la calculer avec le stop",
     "Nombre d'actions = 150 € / (prix d'entrée - stop). Exemple : entrée à 100 €, stop à 95 € → 30 actions.", 3, 210, {}),
    ("t21", "fact", "trading", "Capital de trading",
     "15 000 € dédiés au swing trading dans le PEA. Le reste (ETF) n'est pas du capital de trading.", 3, 205, {}),
    ("t22", "decision", "trading", "Gestion du risque par position",
     "Je ne risque jamais plus d'un pour cent du capital sur un trade, stop inclus.", 3, 100, {"dup": "t01"}),
    ("t23", "todo", "trading", "Faire la déclaration des plus-values crypto",
     "Formulaire 2086 à remplir avant mai 2027. Exporter l'historique Kraken en CSV.", 3, 20, {}),
    ("t24", "fact", "trading", "Objectif de performance",
     "Objectif réaliste : +10 % par an sur le capital de trading, avec une perte maximale (drawdown) de 8 %.", 3, 195, {}),
    ("t25", "learning", "trading", "Routine du dimanche soir", LONG_DIMANCHE, 3, 165, {}),
    ("t26", "fact", "trading", "Bitcoin : prix de revient moyen",
     "Prix de revient moyen du bitcoin : 41 200 €. 0,18 BTC détenus, stockés sur un Ledger Nano S Plus.", 3, 110, {}),
    ("t27", "learning", "trading", "Ordre stop : toujours le placer chez le courtier",
     "Un stop mental n'a pas été respecté sur Worldline (-4 R). Toujours placer l'ordre stop réel au moment de "
     "l'entrée.", 4, 170, {}),
    ("t28", "fact", "trading", "Portefeuille crypto sécurisé : Ledger",
     "Les cryptos sont sur un Ledger Nano S Plus, gardé dans le coffre. Rien ne reste sur la plateforme.", 3, 175, {}),
    ("t29", "decision", "trading", "Arrêt du day trading",
     "Day trading arrêté en janvier 2026 : résultat négatif sur 6 mois et trop de stress. Swing trading uniquement.", 4, 300, {}),
    ("t30", "fact", "trading", "Dividendes réinvestis",
     "Les dividendes du PEA sont réinvestis dans l'ETF World chaque trimestre.", 2, 185, {}),
    # ------------------------------------------------------------------ pc
    ("p01", "fact", "pc", "Configuration du PC",
     "Ryzen 7 5800X3D, carte mère MSI B550 Tomahawk, 32 Go de DDR4 3600 CL16, RTX 4070, SSD NVMe Samsung 980 Pro 1 To, "
     "alimentation Corsair RM750x. Windows 11 Pro.", 4, 300, {}),
    ("p02", "learning", "pc", "Écran bleu WHEA : désactiver le PBO",
     "Écrans bleus WHEA_UNCORRECTABLE_ERROR au repos. Cause : Precision Boost Overdrive avec une courbe négative trop "
     "agressive (-30). Réglé en remettant le Curve Optimizer à -15.", 4, 200, {}),
    ("p03", "fact", "pc", "BIOS : profil XMP activé",
     "Profil XMP 1 activé (3600 MHz CL16). BIOS version 7C91vAH. Mise à jour faite le 02/04/2026.", 3, 230, {}),
    ("p04", "learning", "pc", "Micro-saccades en jeu : désactiver les optimisations plein écran",
     "Les saccades dans les jeux venaient des optimisations plein écran et de la barre de jeu Xbox. Désactivées : temps "
     "d'image stable.", 3, 150, {}),
    ("p05", "fact", "pc", "Plan d'alimentation",
     "Plan « Performances élevées » sur secteur. Mise en veille de l'écran après 10 minutes, jamais de veille "
     "prolongée.", 3, 210, {}),
    ("p06", "learning", "pc", "Pilotes graphiques : toujours passer par DDU",
     "Avant d'installer un nouveau pilote Nvidia : désinstaller l'ancien avec DDU en mode sans échec. L'installation "
     "par-dessus a causé des plantages en mars.", 3, 240, {}),
    ("p07", "fact", "pc", "Températures normales",
     "Processeur : 42 °C au repos, 78 °C en jeu. Carte graphique : 68 °C en charge. Au-delà de 85 °C sur le "
     "processeur, vérifier la pâte thermique.", 3, 180, {}),
    ("p08", "decision", "pc", "Sauvegarde : Veeam Agent au lieu de Macrium",
     "Sauvegarde hebdomadaire du disque système avec Veeam Agent (gratuit) vers le disque dur externe de 4 To. Macrium "
     "Reflect est devenu payant.", 3, 170, {}),
    ("p09", "fact", "pc", "Programmes au démarrage",
     "Seuls Discord, Steam et le pilote audio démarrent avec Windows. Tout le reste est désactivé dans le Gestionnaire "
     "des tâches. Démarrage en 14 secondes.", 3, 160, {}),
    ("p10", "learning", "pc", "Mise à jour Windows 24H2 : bug du Wi-Fi",
     "Après la mise à jour 24H2, le Wi-Fi Intel AX200 se déconnectait. Corrigé avec le pilote 23.60 du site d'Intel "
     "(pas celui de Windows Update).", 3, 90, {}),
    ("p11", "fact", "pc", "Ventilation du boîtier",
     "Boîtier Fractal Meshify 2 : 3 ventilateurs de 140 mm en façade, 1 à l'arrière. Courbe : 40 % jusqu'à 60 °C, "
     "100 % à 80 °C.", 3, 190, {}),
    ("p12", "learning", "pc", "SSD plein : nettoyer le dossier WinSxS",
     "Le SSD système était plein à 96 %. La commande Dism /Online /Cleanup-Image /StartComponentCleanup a libéré 11 Go, "
     "et le déplacement de la bibliothèque Steam sur le deuxième SSD 140 Go.", 3, 130, {}),
    ("p13", "fact", "pc", "Écran : 1440p 165 Hz",
     "Écran LG 27GP850 1440p 165 Hz, G-Sync activé, limite d'images à 162 par seconde dans le panneau Nvidia.", 3, 250, {}),
    ("p14", "decision", "pc", "Antivirus : Windows Defender seul",
     "Pas d'antivirus tiers : Defender suffit et les autres ralentissaient le démarrage. Malwarebytes gratuit en analyse "
     "ponctuelle.", 3, 260, {}),
    ("p15", "learning", "pc", "HAGS : le laisser désactivé",
     "La planification GPU à accélération matérielle (HAGS) provoquait des saccades dans DaVinci Resolve. Désactivée.",
     3, 140, {}),
    ("p16", "fact", "pc", "Mémoire virtuelle",
     "Fichier d'échange fixé à 16 Go sur le SSD système. Ne pas le désactiver : DaVinci plante sans.", 3, 145, {}),
    ("p17", "todo", "pc", "Changer la pâte thermique",
     "Pâte d'origine de 2023. À refaire avec de l'Arctic MX-6 avant l'été.", 2, 25, {}),
    ("p18", "learning", "pc", "Imprimante : file d'attente bloquée",
     "Quand l'imprimante Brother ne répond plus : redémarrer le service « Spouleur d'impression » et vider le dossier "
     "spool PRINTERS de System32.", 3, 100, {}),
    ("p19", "fact", "pc", "Licence Windows",
     "Windows 11 Pro, licence numérique liée au compte Microsoft. Réactivation possible après un changement de carte "
     "mère avec l'utilitaire de résolution des problèmes.", 3, 270, {}),
    ("p20", "learning", "pc", "Grésillements dans le casque : désactiver les améliorations audio",
     "Grésillements dans le casque : décocher « Améliorations audio » et passer en 24 bits 48 kHz.", 3, 120, {}),
    ("p21", "fact", "pc", "Deuxième SSD : jeux et rushs vidéo",
     "SSD Crucial P3 de 2 To en D: pour la bibliothèque Steam et les rushs vidéo en cours.", 3, 135, {}),
    ("p22", "learning", "pc", "Réinstallation propre de Windows : procédure", LONG_REINSTALL, 3, 300, {}),
    ("p23", "learning", "pc", "Installer un pilote Nvidia proprement",
     "Passer DDU en mode sans échec, puis installer le nouveau pilote (installation personnalisée, sans GeForce "
     "Experience).", 3, 80, {"dup": "p06"}),
    ("p24", "fact", "pc", "Réseau : IP fixe et DNS",
     "IP fixe 192.168.1.20, DNS Cloudflare 1.1.1.1 et 1.0.0.1. Freebox Pop, PC relié en Ethernet 2,5 Gb/s.", 3, 155, {}),
    ("p25", "learning", "pc", "Mode Jeu de Windows : le garder activé",
     "Le Mode Jeu de Windows 11 reste activé : il empêche Windows Update d'installer pendant une partie.", 2, 125, {}),
    ("p26", "decision", "pc", "Pas d'overclocking de la carte graphique",
     "Pas d'overclocking de la RTX 4070 : gain de 4 % pour 20 W de plus. Undervolt à 0,95 V à la place : -8 °C.", 3, 115, {}),
    ("p27", "learning", "pc", "Clavier qui ne répond plus après la veille",
     "Décocher « Autoriser l'ordinateur à éteindre ce périphérique » sur les concentrateurs USB racine.", 3, 105, {}),
    ("p28", "fact", "pc", "Outils de diagnostic installés",
     "HWiNFO64 (capteurs), CrystalDiskInfo (santé des disques), LatencyMon (latence), OCCT (tests de stabilité).", 3, 185, {}),
    ("p29", "learning", "pc", "Démarrage rapide : à désactiver",
     "Le démarrage rapide de Windows empêchait les mises à jour du BIOS de s'appliquer et gênait le double amorçage. "
     "Désactivé dans les options d'alimentation.", 3, 195, {}),
    ("p30", "fact", "pc", "Mises à jour Windows retardées",
     "Mises à jour de fonctionnalités retardées de 30 jours, mises à jour de qualité en pause 7 jours après leur "
     "sortie.", 2, 165, {}),
    # ------------------------------------------------------------------ global (no project)
    ("g01", "user", None, "Profil : Karim, 38 ans, Lyon",
     "Karim, 38 ans, vit à Lyon. Chargé de projet web en poste, tient à côté une boutique en ligne de thé japonais et "
     "une chaîne YouTube de bricolage. N'est pas développeur.", 5, 320, {}),
    ("g02", "feedback", None, "Toujours répondre en français, sans jargon",
     "Réponses en français simple. Expliquer chaque terme technique en une phrase. Pourquoi : je ne suis pas "
     "développeur.", 5, 320, {}),
    ("g03", "feedback", None, "Réponse courte d'abord, détail sur demande",
     "Commencer par la réponse en 3 lignes au plus, proposer le détail ensuite. Pourquoi : je lis souvent sur "
     "téléphone.", 4, 300, {}),
    ("g04", "feedback", None, "Ne jamais supprimer un fichier sans demander",
     "Avant toute suppression ou écrasement de fichier, demander confirmation. Pourquoi : perte d'un dossier de photos "
     "en 2025.", 5, 310, {}),
    ("g05", "feedback", None, "Format des prix : 12,90 €",
     "Prix avec une virgule, deux décimales et une espace avant le symbole €. Jamais « 12.9€ ».", 3, 280, {}),
    ("g06", "feedback", None, "Tutoiement",
     "Me tutoyer. Ton direct, pas de formules de politesse à rallonge.", 3, 315, {}),
    ("g07", "feedback", None, "Proposer un plan avant de modifier plusieurs fichiers",
     "Quand une demande touche plus de deux fichiers, lister d'abord ce qui va changer et attendre mon accord.", 4, 200, {}),
    ("g08", "user", None, "Créneaux de travail sur les projets personnels",
     "Travaille sur ses projets personnels le soir après 20 h 30 et le samedi matin.", 3, 290, {}),
    ("g09", "user", None, "Appareils : PC fixe Windows 11 et iPhone 14",
     "PC fixe sous Windows 11 au bureau de la maison, iPhone 14 pour tout le reste. Pas de Mac.", 3, 295, {}),
    ("g10", "fact", None, "Comptes Google",
     "Compte Google Workspace de la boutique pour Sheets et Drive. Compte Google personnel séparé pour YouTube.", 3, 270, {}),
    ("g11", "fact", None, "Vacances à Lisbonne en mai 2027",
     "Semaine du 8 au 15 mai 2027 à Lisbonne, appartement dans l'Alfama. Vol Transavia depuis Lyon déjà réservé.", 3, 30, {}),
    ("g12", "fact", None, "Voiture : contrôle technique et révision",
     "Peugeot 308 de 2019. Contrôle technique valable jusqu'au 14/03/2027. Révision faite le 06/10/2026 au garage "
     "Martin.", 3, 45, {}),
    ("g13", "fact", None, "Impôts : prélèvement à la source",
     "Taux de prélèvement à la source : 11,2 %. Déclaration du chiffre d'affaires de la micro-entreprise chaque "
     "trimestre à l'URSSAF.", 3, 180, {}),
    ("g14", "reference", None, "Comptable : cabinet Lefèvre",
     "Experte-comptable : Sophie Lefèvre, cabinet Lefèvre & associés à Villeurbanne. Bilan annuel 890 € HT.", 3, 260, {}),
    ("g15", "fact", None, "Assurance habitation",
     "MAIF, échéance le 1er février, 31 € par mois.", 2, 275, {}),
    ("g16", "learning", None, "Estimer une tâche : multiplier par deux",
     "Mes estimations de temps sont toujours trop courtes : doubler la durée prévue avant de m'engager sur une date.",
     3, 230, {}),
    ("g17", "fact", None, "Abonnements mensuels",
     "Shopify 36 €, Klaviyo 20 €, Canva Pro 11,99 €, Epidemic Sound 9,99 €, TradingView 13 €, Google Workspace 6,90 €. "
     "Total d'environ 98 € par mois.", 3, 50, {}),
    ("g18", "feedback", None, "Un tableau plutôt qu'un long paragraphe pour comparer",
     "Pour comparer deux options ou plus : un tableau court. Pourquoi : plus rapide à lire.", 3, 240, {}),
    ("g19", "feedback", None, "Dates au format jour/mois/année",
     "Écrire les dates comme 15/11/2026, jamais au format américain.", 3, 250, {}),
    ("g20", "fact", None, "Banque professionnelle : Qonto",
     "Compte professionnel Qonto pour la micro-entreprise. Carte virtuelle pour les abonnements.", 3, 265, {}),
    ("g21", "fact", None, "Salle de sport",
     "Abonnement Basic-Fit, séances le lundi et le jeudi à 7 h.", 2, 220, {}),
    ("g22", "todo", None, "Cadeau de Noël pour Inès",
     "Vélo 20 pouces, à commander avant le 05/12.", 3, 7, {}),
    ("g23", "learning", None, "Sauvegarder avant toute mise à jour importante",
     "Avant une mise à jour de Windows, de Shopify (thème) ou de DaVinci : sauvegarde d'abord. Deux mauvaises "
     "surprises en 2025.", 4, 255, {}),
    ("g24", "fact", None, "Gestionnaire de mots de passe : Bitwarden",
     "Tous les identifiants sont dans Bitwarden. Double authentification avec l'application Aegis.", 3, 285, {}),
    ("g25", "decision", None, "Un seul projet par soir",
     "Pour ne pas s'éparpiller : boutique le lundi et le mardi, chaîne YouTube le mercredi et le samedi, trading le "
     "dimanche soir.", 4, 140, {}),
    ("g26", "fact", None, "Objectif 2027 : vivre de la boutique et de la chaîne",
     "Objectif : 3 000 € nets par mois cumulés boutique et YouTube fin 2027 pour quitter le salariat.", 4, 150, {}),
    ("g27", "feedback", None, "Parler simplement, en français",
     "Écrire en français courant et éviter les mots techniques non expliqués.", 3, 120, {"dup": "g02"}),
    ("g28", "fact", None, "Fournisseur d'accès à Internet : Free",
     "Freebox Pop, fibre. Assistance au 3244.", 2, 300, {}),
    ("g29", "learning", None, "Relire chaque commande avant de valider",
     "Dans Claude Code, lire la commande proposée avant d'accepter, surtout si elle contient rm, del ou format.", 4, 210, {}),
    ("g30", "fact", None, "Imprimante 3D : Bambu Lab A1 mini",
     "Sert pour les gabarits de l'atelier. Filaments PLA et PETG.", 2, 135, {}),
    ("g31", "todo", None, "Prendre rendez-vous chez la comptable pour le bilan",
     "À faire avant le 15/12.", 3, 9, {}),
    ("g32", "user", None, "Langues parlées",
     "Français langue maternelle, anglais niveau B2, arabe parlé.", 2, 305, {}),
    ("g33", "reference", None, "Dossier des documents administratifs",
     "Dossier « Administratif » sur Google Drive : impôts, URSSAF, assurances, classés par année.", 3, 245, {}),
    ("g34", "learning", None, "Notion : une base par projet",
     "Une base Notion par projet (boutique, chaîne, emploi) plutôt qu'une seule page fourre-tout : on retrouve tout "
     "plus vite.", 3, 175, {}),
    # « orphans »: saved without a project although they belong to one (written from another folder)
    ("o01", "fact", None, "Klaviyo : segment des clients VIP",
     "Segment « VIP » : clients avec 3 commandes ou plus, ou plus de 150 € dépensés. 64 personnes. Reçoivent les "
     "nouveautés 48 h avant les autres.", 3, 55, {}),
    ("o02", "learning", None, "Idée : vendre des kits de bricolage en lien avec la chaîne",
     "Des abonnés demandent des kits prêts à monter (bois débité et quincaillerie). À tester avec le kit de l'étagère "
     "murale, vendu sur une petite boutique Shopify séparée.", 3, 28, {}),
    ("o03", "fact", None, "Alerte de prix sur l'action Hermès",
     "Alerte TradingView posée à 2 150 € sur Hermès (cassure du plus haut de 20 jours).", 3, 6, {}),
    ("o04", "learning", None, "DaVinci Resolve plante à l'export : mettre à jour le pilote Nvidia Studio",
     "Les plantages à l'export H.265 ont cessé avec le pilote Nvidia Studio 565.90 (et non le pilote Game Ready).", 3, 38, {}),
    ("o05", "fact", None, "Entretien Nordéa : salle et accès",
     "Les locaux de Nordéa Logistique sont au 12 quai Perrache, 4e étage. Se présenter à l'accueil avec une pièce "
     "d'identité.", 3, 9, {}),
]

# ---------------------------------------------------------------------------------------------- test messages
# (id, category, current folder (project key or None), message, [expected keys, the main one first], note)
QUESTIONS = [
    # A. paraphrases that share few words with the memory
    ("A1", "paraphrase", "boutique", "en combien de temps le Japon nous envoie les théières ?", ["b01", "b12"], ""),
    ("A2", "paraphrase", None, "à partir de quel montant le port est offert sur le site ?", ["b04"], ""),
    ("A3", "paraphrase", "youtube", "quel logiciel j'utilise pour monter mes vidéos ?", ["y03"], ""),
    ("A4", "paraphrase", None, "combien je peux perdre au maximum sur une position ?", ["t01", "t22"], ""),
    ("A5", "paraphrase", "pc", "mon ordi plante avec un écran bleu, c'était quoi la solution déjà ?", ["p02"], ""),
    ("A6", "paraphrase", None, "c'est quand déjà le voyage au Portugal ?", ["g11"], "connaissance du monde : Lisbonne = Portugal"),
    ("A7", "paraphrase", "emploi", "combien je demande comme rémunération ?", ["e02", "e21"], ""),
    ("A8", "paraphrase", None, "est-ce que tu peux effacer des fichiers sans me prévenir ?", ["g04"], ""),
    ("A9", "paraphrase", "boutique", "quelle appli on utilise pour récolter les témoignages des acheteurs ?", ["b15"], "synonymes du lexique"),
    ("A10", "paraphrase", "trading", "sur quelle plateforme j'achète mes cryptos maintenant ?", ["t04"], "ne doit pas ressortir l'archivé t05"),
    # B. conjugated verbs and plurals
    ("B1", "conjugaison", "boutique", "les clients peuvent renvoyer leurs achats pendant combien de jours ?", ["b13", "b35"], ""),
    ("B2", "conjugaison", "youtube", "on publie les vidéos quel jour ?", ["y01", "y24"], ""),
    ("B3", "conjugaison", "pc", "j'avais désinstallé les pilotes graphiques comment déjà ?", ["p06", "p23"], ""),
    ("B4", "conjugaison", "trading", "quels titres je surveille en ce moment ?", ["t14"], ""),
    ("B5", "conjugaison", "emploi", "j'ai été refusé par quelle entreprise ?", ["e05", "e24"], ""),
    ("B6", "conjugaison", None, "mes abonnements me coûtent combien par mois ?", ["g17"], ""),
    ("B7", "conjugaison", "boutique", "quelles marges on vise sur les théières ?", ["b08"], ""),
    # C. typos
    ("C1", "faute", "boutique", "c'est quoi le code promo de bienvenu", ["b05"], ""),
    ("C2", "faute", "youtube", "c koi les reglages d'exportt pour youtube", ["y06"], ""),
    ("C3", "faute", "pc", "temperatures normal du procesuer", ["p07"], ""),
    ("C4", "faute", None, "prix du macha cérémonial", ["b09"], ""),
    ("C5", "faute", "trading", "ma stratégie de cassure avec la moyene mobile", ["t06"], ""),
    ("C6", "faute", "emploi", "quand est mon prochain entrtien chez nordea", ["e04", "e14", "o05"], ""),
    # D. no accents, phonetic spelling, text-message style
    ("D1", "sans accent", "pc", "les saccade en jeu c etait quoi le reglage", ["p04"], ""),
    ("D2", "sans accent", "boutique", "delai de preparation des commande", ["b27"], ""),
    ("D3", "sans accent", None, "quel est mon taux de prelevement a la source", ["g13"], ""),
    ("D4", "sans accent", "youtube", "kel materiel pr le tournage", ["y02"], ""),
    ("D5", "sans accent", "boutique", "boutik : frais de port mondial relay", ["b03", "b34", "b45"], ""),
    # E. 2-3 words
    ("E1", "court", "boutique", "politique de retour", ["b13", "b35"], ""),
    ("E2", "court", "trading", "flat tax", ["t09"], ""),
    ("E3", "court", "pc", "profil XMP", ["p03"], ""),
    ("E4", "court", "youtube", "sponsor Durand", ["y09", "y31"], ""),
    ("E5", "court", None, "contrôle technique", ["g12"], ""),
    ("E6", "court", "emploi", "préavis", ["e08"], ""),
    # F. three sentences
    ("F1", "long", "boutique", "Je prépare la newsletter de la semaine prochaine. Je ne sais plus quel jour et quelle heure "
     "marchaient le mieux pour l'envoi. Tu peux me rappeler ce qu'on avait trouvé ?", ["b41"], ""),
    ("F2", "long", "youtube", "Je dois faire la miniature de la prochaine vidéo sur l'établi pliant. J'hésite à mettre beaucoup "
     "de texte dessus. Qu'est-ce qui marchait le mieux d'après nos tests ?", ["y04"], ""),
    ("F3", "long", "pc", "Mon disque C est presque plein et Windows m'affiche des alertes. J'avais déjà eu ce problème il y a "
     "quelques mois. Comment j'avais libéré de la place ?", ["p12"], ""),
    ("F4", "long", "emploi", "J'ai un entretien jeudi avec le directeur digital. Je voudrais préparer mes réponses. Quels exemples "
     "chiffrés j'avais retenus pour me présenter ?", ["e06"], ""),
    ("F5", "long", "trading", "J'ai pris deux pertes de suite ce matin sur Vinci et Hermès. J'ai envie de me refaire tout de "
     "suite. C'est quoi ma règle dans ce cas ?", ["t16"], ""),
    ("F6", "long", None, "Je fais le point sur mes finances perso. Je voudrais vérifier combien j'investis chaque mois en bourse. "
     "Et sur quel support ?", ["t07"], ""),
    # G. date questions
    ("G1", "date", "emploi", "qu'est-ce qui s'est passé la semaine dernière pour ma recherche d'emploi ?", ["e04", "e09"],
     "semaine du 09 au 15/11 : e04 écrit le 12/11, e09 le 15/11"),
    ("G2", "date", "boutique", "combien on a vendu le mois dernier ?", ["b23"], "octobre, pas septembre (b24)"),
    ("G3", "date", "trading", "mon bilan de trading de septembre", ["t12"], "pas octobre (t11)"),
    ("G4", "date", "youtube", "qu'est-ce que j'ai noté hier sur la chaîne ?", ["y36"], "seul souvenir écrit la veille"),
    ("G5", "date", "boutique", "quel produit on a lancé début novembre ?", ["b38"], ""),
    ("G6", "date", None, "c'était quand la révision de la voiture ?", ["g12"], ""),
    # H. names
    ("H1", "nom", None, "c'est qui Camille Arnaud ?", ["e03"], ""),
    ("H2", "nom", None, "le contact chez Marukyu", ["b11"], ""),
    ("H3", "nom", "youtube", "combien paie Élodie par vidéo ?", ["y09"], ""),
    ("H4", "nom", None, "Sophie Lefèvre", ["g14"], ""),
    ("H5", "nom", None, "Julien Perrin peut me recommander ?", ["e17"], ""),
    # I. English terms
    ("I1", "anglais", "boutique", "what's our free shipping threshold?", ["b04"], ""),
    ("I2", "anglais", "boutique", "le ROAS des pubs Meta", ["b21"], ""),
    ("I3", "anglais", "trading", "ma règle pour le trailing stop", ["t13"], ""),
    ("I4", "anglais", "youtube", "le CTR des thumbnails", ["y04"], ""),
    ("I5", "anglais", "pc", "le backup du disque système", ["p08"], ""),
    ("I6", "anglais", "boutique", "les reviews clients", ["b15"], "synonyme du lexique : review → avis"),
    # J. project context
    ("J1", "projet", "youtube", "combien d'abonnés ?", ["y07"], ""),
    ("J2", "projet", "pc", "le seuil de livraison gratuite de la boutique", ["b04"], "souvenir d'un autre projet que le dossier courant"),
    ("J3", "projet", "boutique", "objectif de l'année", ["b33"], "même mot dans 4 projets : le dossier courant doit trancher"),
    ("J4", "projet", "trading", "objectif de l'année", ["t24"], ""),
    ("J5", "projet", "youtube", "mes revenus du mois d'octobre", ["y13"], ""),
]

# Messages that must recall nothing: the audit's 14 (id, current folder, message), then the 24 off-topic and
# near-miss sentences that `brain bench` used in the audit (copied: this set must not move with bench's lists).
NEGATIVES = [
    ("N1", None, "quelle est la capitale de l'Australie ?"),
    ("N2", "boutique", "ok merci c'est parfait"),
    ("N3", None, "écris-moi un poème sur l'automne"),
    ("N4", None, "combien coûte un abonnement Netflix ?"),
    ("N5", "boutique", "quel est le délai de livraison d'Amazon Prime ?"),
    ("N6", None, "explique-moi comment fonctionne un moteur électrique"),
    ("N7", None, "traduis « bonjour, comment allez-vous » en espagnol"),
    ("N8", None, "quel temps fait-il à Marseille demain ?"),
    ("N9", None, "donne-moi une recette de gâteau au chocolat"),
    ("N10", "pc", "vas-y continue"),
    ("N11", None, "quel est le prix d'un billet de train Lyon-Paris ?"),
    ("N12", "pc", "comment installer Linux sur un vieux portable ?"),
    ("N13", None, "qui a gagné le match hier soir ?"),
    ("N14", "emploi", "corrige les fautes dans ce texte : je suis aller au marché acheter des légume"),
    ("X0", None, "quelle heure est-il à Tokyo maintenant ?"),
    ("X1", None, "donne moi une recette de crêpes"),
    ("X2", None, "traduis ce texte en anglais stp"),
    ("X3", None, "combien font 12 fois 8"),
    ("X4", None, "écris un poème sur la mer"),
    ("X5", None, "quel temps fera-t-il demain à paris"),
    ("X6", None, "explique moi la photosynthèse"),
    ("X7", None, "c'est quoi la capitale de l'australie"),
    ("X8", None, "fais une blague"),
    ("X9", None, "ok merci c'est parfait"),
    ("X10", None, "vsy continue"),
    ("X11", None, "corrige l'orthographe de ce paragraphe"),
    ("X12", None, "liste les planètes du système solaire"),
    ("X13", None, "qui a gagné la coupe du monde 1998"),
    ("X14", None, "convertis 30 euros en dollars"),
    ("X15", None, "raconte moi une histoire courte"),
    ("X16", None, "combien coûte un abonnement Netflix ?"),
    ("X17", None, "quel est le délai de livraison d'Amazon Prime ?"),
    ("X18", None, "comment configurer le wifi de ma box ?"),
    ("X19", None, "quel est le prix du bitcoin aujourd'hui ?"),
    ("X20", None, "à quelle heure ferme la poste ?"),
    ("X21", None, "c'est quoi un bon thème WordPress ?"),
    ("X22", None, "comment faire un export Excel en CSV ?"),
    ("X23", None, "quel transporteur pour une lettre recommandée ?"),
]

# Long messages added after the audit, to measure the rule for long messages (search._long_refusal) on both sides: the
# audit's 38 negatives are all short. Three sentences each, like the audit's F questions; the negatives share words with
# the brain (job interview, series of episodes, a plan to propose, a price) but are about something else.
LONG_QUESTIONS = [
    ("K1", "long", "boutique", "Un client m'écrit que son colis est arrivé abîmé. Il veut être remboursé. On fait comment "
     "d'habitude pour les retours ?", ["b13", "b35"], ""),
    ("K2", "long", "youtube", "Je viens de finir le montage de la vidéo sur l'étagère. Je dois l'exporter ce soir. Quels "
     "réglages j'utilise d'habitude ?", ["y06"], ""),
    ("K3", "long", "pc", "Mon PC fait des petits grésillements dans le casque quand je joue. Ça m'était déjà arrivé l'année "
     "dernière. Comment j'avais réglé ça ?", ["p20"], ""),
    ("K4", "long", "trading", "Je veux acheter des actions Air Liquide demain. Le prix d'entrée serait 180 € avec un stop à "
     "172 €. Combien d'actions je peux prendre avec ma règle ?", ["t20", "t01", "t22"], ""),
    ("K5", "long", "emploi", "Une recruteuse m'a appelé pour un poste à Paris. Il faudrait être au bureau quatre jours par "
     "semaine. Qu'est-ce que j'avais décidé pour ce genre de poste ?", ["e13"], ""),
    ("K6", "long", None, "Je dois envoyer mes papiers à la comptable pour le bilan. Je ne me souviens plus de son nom. C'est "
     "quel cabinet déjà ?", ["g14", "g31"], ""),
    ("K7", "long", "boutique", "Je veux relancer les gens qui ont laissé un panier sans payer. J'hésite à leur offrir une "
     "réduction tout de suite. Qu'est-ce qui marchait le mieux dans nos tests ?", ["b14"], ""),
    ("K8", "long", "pc", "Après la dernière mise à jour, mon Wi-Fi se coupe tout le temps. Je crois que ça m'est déjà "
     "arrivé. Tu te souviens de ce qu'on avait fait ?", ["p10"], ""),
]
LONG_NEGATIVES = [
    ("L1", "boutique", "Ma sœur veut ouvrir un salon de thé à Annecy. Elle me demande combien coûte un local commercial "
     "en centre-ville. Tu peux lui faire une estimation rapide ?"),
    ("L2", "pc", "Mon père a un vieux portable qui rame beaucoup. Il l'utilise seulement pour ses mails et la météo. Est-ce "
     "que ça vaut le coup de lui en acheter un neuf ?"),
    ("L3", "youtube", "Je regarde une série sur Netflix en ce moment. Les épisodes durent presque une heure. Tu connais "
     "d'autres séries policières du même genre ?"),
    ("L4", None, "Je voudrais apprendre à faire du pain maison. Il me faut quelle farine et combien de temps de levée ? "
     "J'ai un four classique, pas de machine à pain."),
    ("L5", "trading", "Mon beau-frère me parle d'un placement immobilier en SCPI. Il dit que ça rapporte 5 % par an sans "
     "rien faire. C'est sérieux ou c'est une arnaque ?"),
    ("L6", "emploi", "Ma cousine passe un entretien d'embauche pour un poste d'infirmière lundi. Elle stresse beaucoup. "
     "Tu as des conseils pour qu'elle se détende avant ?"),
    ("L7", None, "On part en week-end à la montagne avec les enfants. Il va faire froid là-haut. Qu'est-ce qu'il faut "
     "absolument mettre dans la valise ?"),
    ("L8", "boutique", "Je dois écrire un discours pour le mariage de mon meilleur ami. Je veux quelque chose de drôle mais "
     "touchant. Tu peux me proposer un début ?"),
    ("L9", None, "Mon fils a un exposé sur les volcans à préparer pour lundi. Il doit faire un plan en trois parties. Tu "
     "peux lui proposer des idées simples ?"),
    ("L10", "pc", "Ma femme voudrait changer de forfait téléphone. Elle paie 25 € par mois chez Orange. Tu connais des "
     "offres moins chères avec autant de données ?"),
    ("L11", "youtube", "J'ai vu un documentaire sur les pyramides hier soir. Ils expliquaient comment les blocs étaient "
     "taillés. C'est vrai qu'on ne sait toujours pas comment ils faisaient ?"),
    ("L12", None, "Je cherche une recette de soupe pour ce soir. J'ai des poireaux, des pommes de terre et des carottes. "
     "Tu peux me donner les étapes ?"),
    ("L13", "trading", "Mon collègue me demande comment fonctionne une assurance vie. Il hésite avec un livret A. Tu peux "
     "m'expliquer simplement la différence ?"),
    ("L14", "emploi", "Mon neveu cherche un stage de troisième dans une entreprise. Il aimerait découvrir le métier de "
     "cuisinier. Comment il peut faire sa demande ?"),
    ("L15", "boutique", "Je voudrais offrir des fleurs à ma mère pour son anniversaire. Elle habite à Marseille. Tu "
     "connais un site qui livre le jour même ?"),
    ("L16", None, "Le chauffage de mon appartement fait un bruit bizarre la nuit. Le propriétaire ne répond pas. "
     "Qu'est-ce que je peux faire légalement ?"),
]

# Observations noted at the end of tasks (`brain obs`): (project key or None, days ago, hour, text). No memory says the
# same, so the questions below can only be answered from them; the negatives must not recall them either.
OBSERVATIONS = [
    ("boutique", 2, 15, "🔴 Le fournisseur de sachets kraft Embalpack est écarté : délai de 6 semaines, trop long pour Noël"),
    ("boutique", 8, 11, "🟡 Test du mousseur électrique Hario : mousse trop légère, pas retenu pour la boutique"),
    ("boutique", 4, 18, "🔴 Les coffrets de Noël seront fermés par un ruban rouge, sans papier cadeau"),
    ("youtube", 4, 21, "🟡 Vidéo de l'étagère murale : montage terminé, il reste l'étalonnage des couleurs"),
    ("youtube", 9, 20, "🟢 Commentaire épinglé ajouté sous la vidéo de l'établi pliant"),
    ("pc", 8, 22, "🔴 Le pilote audio Realtek 6.0.9 coupe le son : revenu à la version 6.0.1, ne pas le mettre à jour"),
    ("pc", 3, 21, "🟡 Filtre à poussière du boîtier nettoyé, températures redescendues de 4 °C"),
    ("emploi", 6, 19, "🟡 Candidature envoyée chez Rhône Digital pour le poste de responsable e-commerce"),
    ("emploi", 11, 20, "🟢 Profil LinkedIn mis à jour avec la certification GA4"),
    ("trading", 5, 21, "🟡 Semaine sans trade : marché sans tendance claire, rien acheté"),
    ("trading", 12, 20, "🔴 Ordre stop oublié sur Air Liquide : placé le lendemain, à ne plus refaire"),
    (None, 3, 9, "🟡 Rendez-vous chez le dentiste déplacé au mercredi 3 décembre"),
]
# (id, current folder, message, a piece of the observation that answers it)
OBS_QUESTIONS = [
    ("O1", "boutique", "pourquoi on a écarté le fournisseur de sachets Embalpack ?", "Embalpack"),
    ("O2", "pc", "quelle version du pilote audio Realtek je dois garder ?", "Realtek"),
    ("O3", "emploi", "j'ai déjà postulé chez Rhône Digital ?", "Rhône Digital"),
    ("O4", "boutique", "le mousseur Hario, on l'a gardé finalement ?", "Hario"),
]


# ------------------------------------------------------------------------------------------ frozen clock
class _Date(_dtm.date):
    @classmethod
    def today(cls):
        return cls(*NOW[:3])


class _DateTime(_dtm.datetime):
    @classmethod
    def now(cls, tz=None):
        d = cls(*NOW)
        return d.astimezone(tz) if tz is not None else d

    @classmethod
    def today(cls):
        return cls(*NOW)


def freeze_clock():
    """brainkit reads the clock through the datetime module at call time (`_dt.date.today()`, `_dt.datetime.now()`):
    replacing its two classes before brainkit is imported fixes « today » for the whole run."""
    _dtm.date, _dtm.datetime = _Date, _DateTime


# ------------------------------------------------------------------------------------------ the test brain
CONFIG = {"auto_map": {"enabled": False}, "eco": {"auto": False}, "backup": {"enabled": False}, "pc": {"enabled": False},
          "promptlib": {"auto": False}, "journal": {"enabled": True, "rattrapage_le": "2026-11-20T08:00:00"}}


def stamp(age, i):
    """Date of writing `age` days before NOW, at a varied hour."""
    day = _dtm.date(*NOW[:3]) - _dtm.timedelta(days=age)
    return _dtm.datetime.combine(day, _dtm.time(9 + i % 9, (i * 7) % 60, 0)).isoformat(timespec="seconds")


def isolate(tmp):
    """Everything under tmp (memories, Claude settings, home folder): never the real PC."""
    for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_IMPL", "BRAIN_PLUS", "BRAIN_BG", "BRAIN_TASK"):
        os.environ.pop(k, None)
    os.environ.update(BRAIN_HOME=str(tmp / "brain"), CLAUDE_CONFIG_DIR=str(tmp / "claude"), HOME=str(tmp / "home"),
                      USERPROFILE=str(tmp / "home"), PYTHONDONTWRITEBYTECODE="1")
    for d in ("brain", "claude", "home", "neutre", "projets"):
        (tmp / d).mkdir(parents=True, exist_ok=True)


def build_world(tmp):
    """The test brain, written as `brain add` writes (automatic tags, a link to the 2 closest memories), oldest first,
    then dated in the past. → {"ids": {key: id}, ...} with the folders and the graph as written."""
    from brainkit import graph
    from brainkit.common import CONFIG_FILE, GRAPH_FILE, write_json
    from brainkit.store import Brain, clean_tags
    write_json(CONFIG_FILE, CONFIG)
    ids = {}
    with Brain.edit() as b:
        b.cache_similar()
        for i, (key, title, body) in enumerate(PROJECTS):
            (tmp / "projets" / key).mkdir(parents=True, exist_ok=True)
            n = b.add("project", title, body, source="utilisateur", meta={"path": str(tmp / "projets" / key)}, nid=key)
            n["created"] = n["updated"] = stamp(330 - i, i)
            ids[key] = n["id"]
        for i, (key, ntype, proj, title, body, imp, age, opts) in enumerate(sorted(MEMORIES, key=lambda m: -m[6])):
            n = b.add(ntype, title, body, tags=clean_tags(graph.concept_tags(f"{title}\n{body}")),
                      project=ids[proj] if proj else None, importance=imp, source="claude")
            if opts.get("status") != "archived":
                for _, m in b.similar(title, body, None, exclude=n["id"], threshold=0.5)[:2]:
                    b.link(n["id"], m["id"], "relates")
            n["created"] = stamp(age, i)
            n["updated"] = stamp(opts.get("upd", age), i)
            if opts.get("status"):
                n["status"] = opts["status"]
            ids[key] = n["id"]
        b.dirty = True
    from brainkit import observations
    for proj, age, hour, text in OBSERVATIONS:
        at = _dtm.datetime.combine(_dtm.date(*NOW[:3]) - _dtm.timedelta(days=age), _dtm.time(hour, 30))
        observations.add([text], project=ids[proj] if proj else None, now=at)
    return {"ids": ids, "rev": {v: k for k, v in ids.items()}, "graph": GRAPH_FILE, "base": GRAPH_FILE.read_bytes(),
            "neutre": tmp / "neutre", "projets": tmp / "projets"}


# ------------------------------------------------------------------------------------------ the hook, as Claude Code runs it
MEM_HEADER = "🧠 Souvenirs liés"
OBS_HEADER = "🗒️ Observation"
MEM_ID = re.compile(r"`([a-z0-9][a-z0-9\-]*)`\s*$")


def hook(event, payload):
    """`brain.py hook <event>` in this process: the same function (hooks.run), the JSON on stdin, one JSON object on
    stdout. → (exit code, additionalContext)."""
    from brainkit import hooks
    real_in, real_out = sys.stdin, sys.stdout
    sys.stdin = io.TextIOWrapper(io.BytesIO(json.dumps(payload, ensure_ascii=False).encode("utf-8")), encoding="utf-8")
    sys.stdout = buf = io.StringIO()
    hooks._EMITTED = False
    try:
        code = hooks.run(event)
    finally:
        sys.stdin, sys.stdout = real_in, real_out
    out = buf.getvalue()
    obj = json.JSONDecoder().raw_decode(out.lstrip())[0] if out.strip() else {}
    return code, (obj.get("hookSpecificOutput") or {}).get("additionalContext") or ""


def shown(ctx):
    """Ids of the memories injected under « 🧠 Souvenirs liés : », in their order."""
    out, inside = [], False
    for line in (ctx or "").splitlines():
        if line.startswith(MEM_HEADER):
            inside = True
        elif inside and line.startswith("- ["):
            m = MEM_ID.search(line)
            if m:
                out.append(m.group(1))
        else:
            inside = False
    return out


def noted(ctx):
    """Observation lines injected under « 🗒️ Observation notée en fin de tâche : »."""
    out, inside = [], False
    for line in (ctx or "").splitlines():
        if line.startswith(OBS_HEADER):
            inside = True
        elif inside and line.startswith("- "):
            out.append(line)
        else:
            inside = False
    return out


def cwd_of(world, proj):
    return world["projets"] / proj if proj else world["neutre"]


def ask(world, text, proj, sid):
    """One message in a new session, from its project folder (or a neutral one). → (keys shown, context)."""
    code, ctx = hook("prompt", {"session_id": sid, "cwd": str(cwd_of(world, proj)), "hook_event_name": "UserPromptSubmit",
                                "prompt": text})
    world["graph"].write_bytes(world["base"])  # recall counters back to zero: every message meets the same brain
    return [world["rev"].get(i, i) for i in shown(ctx)], ctx, code


def run_all(world, tag="rappel"):
    """Every message in its own new session (`tag`-<id>). → ({id: keys shown}, {id: context}, ids whose exit code was
    not 0)."""
    res, ctxs, bad = {}, {}, []
    for pid, proj, text in [(q[0], q[2], q[3]) for q in QUESTIONS + LONG_QUESTIONS] + NEGATIVES + LONG_NEGATIVES \
            + [(o[0], o[1], o[2]) for o in OBS_QUESTIONS]:
        res[pid], ctxs[pid], code = ask(world, text, proj, f"{tag}-{pid}")
        bad += [pid] if code else []
    return res, ctxs, bad


def scores(res, questions=QUESTIONS, negatives=NEGATIVES, ctxs=None):
    """→ (hit@1, hit@3, negatives that recalled something: a memory, or an observation when `ctxs` is given)."""
    h1 = sum(1 for q in questions if res[q[0]][:1] and res[q[0]][0] in q[4])
    h3 = sum(1 for q in questions if any(k in q[4] for k in res[q[0]][:3]))
    return h1, h3, [n[0] for n in negatives if res[n[0]] or (ctxs and noted(ctxs[n[0]]))]


def main():
    detail, mesure = "--detail" in sys.argv, "--mesure" in sys.argv
    tmp = Path(tempfile.mkdtemp(prefix="cerveau-rappel-test-"))
    isolate(tmp)
    freeze_clock()
    sys.path.insert(0, str(CODE))
    from brainkit.common import remove_tree
    ok, fail = [], []

    def check(cond, label, info=""):
        (ok if cond else fail).append(label)
        if not cond:
            print(f"✗ {label}" + (f" — {str(info)[-700:]}" if info else ""))

    world = build_world(tmp)
    res, ctxs, bad = run_all(world)
    h1, h3, false = scores(res, ctxs=ctxs)
    _, lh3, lfalse = scores(res, LONG_QUESTIONS, LONG_NEGATIVES, ctxs)
    found_obs = [o[0] for o in OBS_QUESTIONS if any(o[3] in x for x in noted(ctxs[o[0]]))]
    obs_elsewhere = [q[0] for q in QUESTIONS + LONG_QUESTIONS if noted(ctxs[q[0]])]
    n, nn, ln, lnn = len(QUESTIONS), len(NEGATIVES), len(LONG_QUESTIONS), len(LONG_NEGATIVES)
    if mesure:  # read by `brain bench`
        print(f"MESURE hit1={h1} hit3={h3} n={n} faux={len(false)} neg={nn} long={lh3} nlong={ln} faux_long={len(lfalse)} "
              f"neg_long={lnn} obs={len(found_obs)} nobs={len(OBS_QUESTIONS)}")
        remove_tree(tmp, wait=30)
        return 0
    pct = lambda a, b: f"{100 * a / b:.0f} %"  # noqa: E731
    print(f"Rappel par le hook (questions naturelles) : hit@1 {h1}/{n} ({pct(h1, n)}) · hit@3 {h3}/{n} ({pct(h3, n)})"
          f" · faux rappels {len(false)}/{nn}" + (f" ({', '.join(false)})" if false else ""))
    cats = {}
    for pid, cat, _, _, exp, _ in QUESTIONS:
        c = cats.setdefault(cat, [0, 0])
        c[0] += any(k in exp for k in res[pid][:3])
        c[1] += 1
    print("  hit@3 par catégorie : " + " · ".join(f"{c} {a}/{b}" for c, (a, b) in cats.items()))
    print(f"Messages longs ajoutés (trois phrases) : hit@3 {lh3}/{ln} · faux rappels {len(lfalse)}/{lnn}"
          + (f" ({', '.join(lfalse)})" if lfalse else ""))
    print(f"Observations de fin de tâche : {len(found_obs)}/{len(OBS_QUESTIONS)} retrouvées · montrées à côté d'une autre "
          f"question : {len(obs_elsewhere)}" + (f" ({', '.join(obs_elsewhere)})" if obs_elsewhere else ""))
    missed = [(pid, res[pid]) for pid, _, _, _, exp, _ in QUESTIONS if not any(k in exp for k in res[pid][:3])]
    lmissed = [(pid, res[pid]) for pid, _, _, _, exp, _ in LONG_QUESTIONS if not any(k in exp for k in res[pid][:3])]
    if detail:
        for pid, got in missed + lmissed:
            q = next(x for x in QUESTIONS + LONG_QUESTIONS if x[0] == pid)
            print(f"  ✗ {pid} « {q[3][:90]} » attendu {q[4]} · montré {got or 'rien'}")
        for pid in false + lfalse:
            text = next(x[2] for x in NEGATIVES + LONG_NEGATIVES if x[0] == pid)
            print(f"  ✗ {pid} (hors sujet) « {text[:90]} » · montré {res[pid] + noted(ctxs[pid])}")
        for pid in obs_elsewhere:
            print(f"  · {pid} : observation montrée {noted(ctxs[pid])}")

    # The world itself: the clock brainkit reads is the frozen one, the expected answers exist and are recallable.
    from brainkit import common, dates
    check(common.now_iso() == "2026-11-20T10:00:00" and dates.query_range("hier") == (_dtm.date(2026, 11, 19),) * 2,
          "horloge figée : brainkit voit le vendredi 20/11/2026 à 10 h", (common.now_iso(), dates.query_range("hier")))
    nodes = json.loads(world["base"].decode("utf-8"))["nodes"]
    active = [x for x in nodes.values() if x.get("status", "active") == "active"]
    check(len(nodes) == 213 and len(active) == 207, "cerveau d'essai : 213 nœuds, 207 actifs (6 archivés)",
          (len(nodes), len(active)))
    lost = [k for q in QUESTIONS + LONG_QUESTIONS for k in q[4]
            if nodes[world["ids"][k]].get("status", "active") != "active"]
    check(not lost, "chaque souvenir attendu est actif", lost)
    check(not bad, "hook : code de sortie 0 à chaque message", bad)
    from brainkit import publish
    leaks = publish.secrets_in(CODE, [Path(__file__).resolve().relative_to(CODE).as_posix()])
    check(not leaks, "ce fichier est publié : ni clé, ni mot de passe, ni adresse e-mail dedans", leaks)
    # The measure through the hook, against the floors.
    check(h1 >= FLOOR_HIT1, f"hit@1 par le hook ≥ {FLOOR_HIT1}/{n}", (h1, missed))
    check(h3 >= FLOOR_HIT3, f"hit@3 par le hook ≥ {FLOOR_HIT3}/{n}", (h3, missed))
    check(len(false) <= MAX_FALSE, f"faux rappels ≤ {MAX_FALSE}/{nn}", [(p, res[p]) for p in false])
    check(not [p for p in false if not p.startswith("X")], "les 14 messages hors sujet de l'audit ne rappellent rien",
          [(p, res[p]) for p in false])
    check(lh3 >= FLOOR_LONG_HIT3, f"messages longs : hit@3 ≥ {FLOOR_LONG_HIT3}/{ln}", lmissed)
    check(len(lfalse) <= MAX_LONG_FALSE, f"messages longs hors sujet : faux rappels ≤ {MAX_LONG_FALSE}/{lnn}",
          [(p, res[p]) for p in lfalse])
    # Observations: found when no memory answers, never twice in a session, never on a message about something else.
    check(len(found_obs) >= FLOOR_OBS, f"observations de fin de tâche retrouvées par le hook ≥ {FLOOR_OBS}/{len(OBS_QUESTIONS)}",
          {o[0]: noted(ctxs[o[0]]) for o in OBS_QUESTIONS})
    o1 = OBS_QUESTIONS[0]
    ask(world, o1[2], o1[1], "rappel-obs-session")
    _, again, _ = ask(world, o1[2], o1[1], "rappel-obs-session")
    check(noted(ctxs[o1[0]]) and not noted(again), "même question deux fois dans une session : l'observation une seule fois",
          noted(again))
    _, ctx, _ = ask(world, "on a fait quoi avant-hier ?", "boutique", "rappel-obs-date")
    check(any("Embalpack" in x for x in noted(ctx)), "question seulement datée (« avant-hier ») : l'observation de ce jour-là",
          ctx)
    # Keywords: the end-of-task instruction asks for them, and a memory given the words of a future question is recalled
    # by it (A3: « logiciel » and « vidéos » appear nowhere in « Montage sur DaVinci Resolve »).
    from brainkit import hooks
    from brainkit.store import Brain
    check("--keys" in hooks.STOP_REASON, "consigne de fin de tâche : demande des mots-clés (--keys) à l'enregistrement",
          hooks.STOP_REASON)
    a3 = next(q for q in QUESTIONS if q[0] == "A3")
    with Brain.edit() as b:
        b.nodes[world["ids"]["y03"]].setdefault("meta", {})["keys"] = "logiciel de montage vidéo"
        b.dirty = True
    keyed, _, _ = ask(world, a3[3], a3[2], "rappel-cles-A3")  # (ask puts the graph back as it was)
    check(res["A3"] == [] and keyed[:1] == ["y03"], "mots-clés écrits sur le souvenir : la question qui le ratait le trouve",
          (res["A3"], keyed))
    # Same answer from the real process (`python -I -S brain.py hook prompt`, Python implementation), on two questions
    # and a negative whose answer does not depend on the day.
    env = dict(os.environ, BRAIN_IMPL="python")
    for pid in ("E2", "H2", "N1"):
        q = next((x for x in QUESTIONS if x[0] == pid), None)
        proj, text = (q[2], q[3]) if q else next((x[1], x[2]) for x in NEGATIVES if x[0] == pid)
        data = {"session_id": f"processus-{pid}", "cwd": str(cwd_of(world, proj)), "hook_event_name": "UserPromptSubmit",
                "prompt": text}
        r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), "hook", "prompt"], capture_output=True,
                           input=json.dumps(data).encode("utf-8"), cwd=str(cwd_of(world, proj)), env=env, timeout=120)
        out = r.stdout.decode("utf-8", "replace")
        obj = json.JSONDecoder().raw_decode(out.lstrip())[0] if out.strip() else {}
        got = [world["rev"].get(i, i) for i in shown((obj.get("hookSpecificOutput") or {}).get("additionalContext"))]
        world["graph"].write_bytes(world["base"])
        check(r.returncode == 0 and not r.stderr.strip() and got == res[pid],
              f"processus réel du hook : même rappel qu'en direct ({pid})", (r.returncode, r.stderr[-300:], got, res[pid]))
    if not remove_tree(tmp, wait=30):
        print(f"(dossier pas effacé : {tmp})")
    print(f"\n{len(ok)} vérifications OK, {len(fail)} échec(s)")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
