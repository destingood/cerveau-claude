# Module 13 — Boutique à 0 € absolu (et passage vers une plateforme)

Objectif : vendre sans aucun coût fixe — seules des commissions sur les ventes réalisées — puis passer à une
plateforme payante quand les ventes le justifient. La conformité (module 10) s'applique à tous les chemins.

## 1. Les chemins à 0 €

| Chemin | Coût fixe | Commission | Pour qui | Limites |
|---|---|---|---|---|
| **A. Marketplaces d'abord** (module 16) | 0 € (Etsy : 0,18 € par annonce) | Selon la plateforme | Tester un produit vite ; seconde main ; créations ; produit démontrable (TikTok Shop) | Peu de marque, règles strictes, frais à intégrer dans le prix |
| **B. Site statique gratuit + liens de paiement** (section 2) | 0 € (sous-domaine gratuit) | Stripe : 1,5 % + 0,25 € par carte standard de l'EEE (premium 2,8 %, hors EEE 3,15 % + 0,25 €, +2 % en cas de conversion de devise) ; liens de paiement sans frais en plus [FAIT* — stripe.com, 10/2026 ; taux premium à confirmer dans le tableau de bord] | 1 à 15 produits, marque propre, SEO et GEO dès le premier jour | À construire (Claude génère le site) ; pas de gestion de stock avancée |
| **C. Prévente en financement participatif** (Ulule) | 0 € | 8 % TTC en cas de succès ; frais de paiement payés par les contributeurs | Produit nouveau à financer avant fabrication | Campagne de 2 à 6 semaines ; livraison à tenir |
| **D. Réseaux + catalogue WhatsApp + lien de paiement** | 0 € | Frais du lien | Artisans, commerce de proximité, clients qui écrivent déjà | Manuel ; pas de vitrine trouvée par les moteurs |
| **E. Plateformes avec offre gratuite** (Square Online, SumUp, Big Cartel, Payhip…) | 0 € (Ecwid : plus d'offre gratuite en inscription directe, Starter à 5 $/mois) | Square 1,4 % + 0,25 € (cartes de l'EEE) ; SumUp 2,5 % ; Payhip 5 % par vente ; Big Cartel 0 % (frais Stripe ou PayPal) | Petit catalogue | Big Cartel : 5 produits ; pages Big Cartel et Payhip anciennes [FAIT* — à revérifier au jour du choix] |

À exclure : **GitHub Pages**, dont les conditions interdisent l'usage pour l'e-commerce et les transactions
commerciales [FAIT — documentation GitHub].

**Shopify** : essai de 3 jours, puis 1 € par mois pendant 3 mois [FAIT* — shopify.com, 10/2026 ; forfaits concernés à
lire sur la page tarifs], ensuite Basic à 36 € par mois (27 € par mois en annuel) [FAIT* — blog Shopify France 2026 ; un
autre article dit 29 € : relire shopify.com/fr/tarifs] ; sans Shopify Payments, frais de transaction de 2 % par vente
sur Basic (1 % sur Grow, 0,6 % sur Advanced) ; plan Starter indisponible pour les nouvelles boutiques [FAIT* — aide
Shopify]. Taux de Shopify Payments : à lire dans l'admin (Paramètres › Paiements), les articles publics se
contredisent. Bon tremplin quand le produit est validé : 3 mois presque gratuits pour installer la boutique complète.

## 2. Chemin B pas à pas : site statique + liens de paiement Stripe

1. **Compte Stripe** — création, vérification d'identité et compte bancaire : par l'utilisateur (🔴). Claude explique
   chaque écran.
2. **Un lien de paiement par produit** (Payment Links), réglé ainsi [FAIT — spécification de l'API Stripe du
   30/09/2026] :
   - bouton « Payer » (`submit_type: pay`) et texte sous le bouton (`custom_text.submit`) rappelant l'obligation de
     paiement et le droit de rétractation ;
   - case d'acceptation des CGV obligatoire (`consent_collection.terms_of_service: required`), CGV renseignées dans le
     compte ;
   - collecte de l'adresse de livraison et tarifs de livraison ;
   - paramètres UTM dans l'URL du lien pour savoir d'où vient chaque vente : Stripe accepte les cinq `utm_*` (150
     caractères au plus) mais se contente de les recopier dans l'URL de redirection après paiement (choisir la
     redirection vers une page du site) ; le tableau de bord n'affiche que les vues et les ventes par lien [FAIT* —
     documentation Stripe] → **un lien par canal** (ex. « bougie-tiktok », « bougie-pinterest ») pour lire les ventes
     par canal sans outil.
3. **Le site** — Claude génère un site statique léger (HTML et CSS, sans framework) : accueil, une page par produit
   (avec `Product` et `Offer` en JSON-LD), FAQ, livraison et retours, À propos, contact, mentions légales, CGV,
   confidentialité, page « renoncer au contrat ici » ; `sitemap.xml` et `robots.txt` ; vérifié par
   `python scripts/audit_site.py`.
4. **Hébergement gratuit** : Cloudflare Pages (500 déploiements par mois, 20 000 fichiers, 25 Mio par fichier ; aucune
   restriction commerciale mentionnée) [FAIT — documentation Cloudflare]. Adresse gratuite en `*.pages.dev` ; acheter
   un nom de domaine (quelques euros par an) dès les premières ventes : c'est le seul coût qui vaut d'être avancé.
5. **Obligations à couvrir sur le site** (le paiement Stripe ne les remplit pas toutes) : informations
   précontractuelles complètes avant le lien (art. L221-5) ; récapitulatif (affiché par la page de paiement) ;
   **bouton de rétractation** (art. L221-21 et D221-5 : fonction « renoncer au contrat ici », champs nom, prénom,
   contrat et e-mail, bouton « confirmer la rétractation », accusé de réception sur support durable avec contenu,
   date et heure) → formulaire HTML du site relié à une fonction gratuite qui envoie l'accusé par e-mail [HYPOTHÈSE
   technique ; vérifier que l'intitulé exact des boutons est respecté] ; médiateur ; mentions légales. Contrôle :
   `python scripts/audit_site.py <site> --conformite`.
6. **Visibilité** : Search Console + sitemap ; Bing Webmaster Tools ; fiches gratuites Google : risque de refus avec
   une page de paiement externe (l'aide Merchant Center demande un achat « directement depuis votre site sans
   redirection », tout en admettant les paiements tiers sécurisés) [FAIT*, contradiction] → tester sur 2 ou 3 produits
   avant d'envoyer tout le catalogue (flux : `scripts/audit_catalogue.py --flux`) ; puis les canaux du module 00.
7. **Mesure** : UTM sur chaque lien ; rapports du prestataire de paiement ; mesure d'audience sans traceur, ou
   exemptée de consentement selon la CNIL (module 10).

## 3. Chemin A : marketplaces

Module 16. Commencer par une seule marketplace, 3 à 10 annonces soignées, 14 jours de mesure.

## 4. Quand passer à une plateforme

| Signal | Décision |
|---|---|
| Plus de commandes que le traitement manuel ne le supporte (préparation, suivi, e-mails) | Plateforme avec gestion des commandes et e-mails automatiques |
| Catalogue de plus de 15 produits ou variantes nombreuses | Plateforme (collections, filtres, stock) |
| Les commissions des marketplaces dépassent le coût d'un abonnement | Calcul avec `scripts/unit_economics.py --fixes-mois <abonnement>` : nombre de commandes qui le paient |
| Besoin de flows e-mail, d'avis, de fiches gratuites synchronisées | Plateforme |

**Migration propre** : garder les mêmes URL ou poser des redirections 301 ; exporter les avis et la liste e-mail
(consentements compris) ; garder le même nom, logo et description partout (module 07) ; noter la décision dans le
cerveau (`brain add -t decision …`).
