# Module 03 — Site, tunnel de vente, conversion

Sommaire : 1. Architecture · 2. Thème et performance · 3. Fiche produit · 4. Tunnel organique · 5. Capture et pop-ups
· 6. Panier, formulaires, checkout · 7. Conversion à faible trafic · 8. Rédaction · 9. Psychologie utile ·
10. Recette avant lancement · 11. Construire via connecteur

Sans plateforme payante : module 13 (boutique à 0 €). Les principes de ce module s'y appliquent aussi.

## 1. Architecture minimale

| Page | Rôle |
|---|---|
| Accueil | Promesse, preuve, produits héros, catégories |
| Collection(s) | Hub de catégorie, cible SEO commerciale (module 06) |
| Produit | Conversion |
| Panier (tiroir) | Rassurer, proposer 1 complément pertinent |
| Checkout natif | Paiement |
| Livraison et retours | Délais réels, 14 jours de rétractation, procédure, **bouton de rétractation en ligne** (module 10) |
| FAQ | Objections réelles (les mêmes questions servent aux assistants IA, module 07) |
| À propos | Qui vend, pourquoi, d'où part le stock |
| Contact | E-mail, formulaire, délai de réponse |
| Mentions légales, CGV, Confidentialité, Cookies | Obligations légales (module 10) |

Navigation courte (5 à 7 entrées) [CONSENSUS] ; recherche interne activée au-delà d'une vingtaine de produits.

## 2. Thème et performance

- Thème officiel gratuit (Horizon est désormais le thème phare de Shopify ; vérifier le recommandé au moment du
  projet). Chaque app ajoutée doit justifier le JavaScript qu'elle injecte.
- Seuils « bons » des Core Web Vitals [FAIT — web.dev] : LCP ≤ 2,5 s, INP ≤ 200 ms, CLS ≤ 0,1, au 75e centile.
  Contrôle gratuit : PageSpeed Insights, en mobile.
- Images compressées et dimensionnées ; vidéo hors du premier écran ou lancée au clic ; peu de polices.
- Pas de pop-up plein écran à l'arrivée sur mobile : gêne l'utilisateur et va contre les recommandations de Google
  sur les interstitiels intrusifs [CONSENSUS] ; aucun script qui détourne le bouton Retour (règle anti-spam de
  Google, module 06).

## 3. Fiche produit à forte conversion

**Premier écran mobile**
1. Titre = bénéfice + produit (pas de bourrage de mots-clés).
2. Preuve : note et nombre d'avis réels, seulement s'ils existent.
3. Prix TTC ; prix de référence légal en cas de promotion.
4. 3 bénéfices concrets (méthode CAB : Caractéristique → Avantage → Bénéfice).
5. Variantes claires (peu d'options : loi de Hick) ; bouton d'ajout au panier contrasté.
6. Délai de livraison réaliste (« expédié depuis l'UE » seulement si c'est vrai), retours, moyens de paiement.

**Sous le premier écran**
- Vidéo de démonstration (15 à 30 s) ; problème → solution ; mode d'emploi en 3 étapes.
- Caractéristiques en unités métriques (cm, kg, ml, W), contenu de la boîte, compatibilités.
- Comparatif honnête avec les alternatives, sans dénigrer un concurrent nommé.
- FAQ de 8 à 10 objections réelles (tirées des messages et des avis).
- Avis et contenus clients réels, publiés avec accord.
- Informations de sécurité exigées en vente à distance (règlement (UE) 2023/988, art. 19) : fabricant, personne
  responsable dans l'UE si le fabricant est hors UE, identification du produit, avertissements en français.
- Garanties légales ; garantie commerciale éventuelle présentée à part.
- Produits complémentaires.

**Règles d'écriture** : ne recopie ni ne traduis jamais la description du fournisseur (dupliquée partout, souvent non
conforme, visée par les règles anti-spam de Google si c'est fait en masse) ; réécris à partir des caractéristiques
vérifiées ; aucun fait inventé (un fait manquant devient « [?] » et il est signalé) ; texte dans la langue du pays de
vente.

## 4. Tunnel organique type

Vidéo, communauté, marketplace ou fiche gratuite → lien (avec UTM) → page produit ou collection dédiée → panier
(tiroir + 1 complément) → checkout natif (paiements express) → page de remerciement (inscription, partage,
parrainage) → flows e-mail (module 08).

Règle (modèle « possédé / loué / emprunté ») : tout canal **loué** (réseaux, marketplaces) ou **emprunté** (créateurs,
presse, partenaires) doit renvoyer vers un canal **possédé** (site, liste e-mail, communauté), le seul qui ne dépend
pas d'un algorithme.

## 5. Capture d'e-mails et pop-ups

- Aimant utile (module 08, section 3) ; un seul champ (e-mail) ; case de consentement non précochée ; finalité claire.
- Déclenchement : après 30 à 60 s, ou à 25-50 % de défilement, ou à l'intention de sortie (ordinateur), ou au clic ;
  une fois par session ; un refus mémorisé 7 à 30 jours ; jamais dans le checkout [CONSENSUS].
- Mobile : bandeau en bas d'écran plutôt que fenêtre plein écran.
- « Non merci » sans culpabilisation ; jamais de compte à rebours ajouté « pour l'urgence ».

## 6. Panier, formulaires, checkout

- Frais de livraison et délais affichés **avant** le panier ; seuil de livraison offerte visible (« encore X € »).
- Achat sans création de compte ; paiements express (Shop Pay, Apple Pay, Google Pay, PayPal selon la plateforme).
- Formulaires : libellés visibles ; validation à la sortie du champ ; erreurs précises affichées près du champ sans
  effacer la saisie ; claviers adaptés et remplissage automatique ; cibles tactiles de 44 px au moins ; une seule
  colonne [CONSENSUS].
- Réassurance au bon endroit : retours, paiement sécurisé, contact, près du bouton.
- Bouton final explicite (« Commander avec obligation de paiement » ou équivalent sans ambiguïté, module 10).

## 7. Conversion à faible trafic

Avec peu de visites, un test A/B ne conclut presque jamais (tailles d'échantillon : module 09, section 4). Ordre :
1. **Qualitatif** : enregistrements de sessions et cartes de chaleur (Microsoft Clarity, gratuit ; depuis le
   31/10/2025 il exige un signal de consentement pour les visiteurs de l'EEE, à relier au bandeau cookies — la CNIL
   exige le consentement) ; 5 personnes de la cible qui achètent en pensant à voix haute ; sondage post-achat
   « Qu'est-ce qui a failli vous faire renoncer ? ».
2. **Grille LIFT** : proposition de valeur ; pertinence (la page tient la promesse de la source) ; clarté ; urgence
   réelle ; anxiété (freine) ; distraction (freine).
3. **Changements séquentiels** : un changement majeur à la fois, mesuré sur 1 à 2 semaines complètes, qualifié
   d'indicatif ; page à traiter choisie par la grille PIE (module 09).
4. **Test A/B** : seulement quand le volume le permet.

## 8. Rédaction

- **Diagnostic d'abord** : texte creux (réécrire), vraie voix à restaurer (retoucher), ou une seule ligne à changer.
- **Triple filtre par ligne** : peut-on se la représenter ? la prouver ? un concurrent pourrait-il l'écrire mot pour
  mot ? Une allégation non prouvée ne s'écrit pas : nommer la preuve qui la débloquerait (export d'avis, test,
  certificat) — art. L121-2.
- Cadres : PAS (problème, agitation, solution), AIDA, Hook-Story-Offer ; bénéfices avant caractéristiques ; chiffres
  précis et vérifiables ; mots exacts des clients (module 15).
- **Tics d'écriture IA à bannir** : « Ce n'est pas X, c'est Y », « Pas de X, pas de Y », « Le résultat ? »,
  « Dites adieu à », tirets cadratins en série dans les textes courts.
- **Relecture en 7 passes** : clarté, voix, « et alors ? », preuve, précision, émotion, zéro risque juridique.
- Français clair, phrases courtes ; vouvoiement ou tutoiement cohérent avec la marque.

## 9. Psychologie utile (et ce qui est proscrit)

| Retenu | Application |
|---|---|
| Effet du « gratuit » | Seuil de livraison offerte |
| Gradient d'objectif | Barre « encore X € » dans le panier |
| Règle pic-fin | Déballage soigné, e-mail après réception |
| Effet Zeigarnik | Rappel de panier abandonné |
| Réciprocité | Guide ou conseil vraiment utile offert |
| Effet « pratfall » | « Pas le moins cher, mais… » |
| Comptabilité mentale | Coût par utilisation |
| Loi de Hick | Peu de variantes, un choix par défaut clair |

Proscrits : option payante cochée par défaut ; ancrage sur un prix de référence non conforme (art. L112-1-1) ; faux
compteurs de visiteurs ou de stock (art. L121-4, 7°) ; leurre sans offre réelle. Sans source fiable : « règle des 7
contacts », « une perte pèse deux fois plus qu'un gain » appliqué tel quel.

## 10. Recette avant lancement

- Mot de passe de la boutique retiré ; aucun noindex oublié ; `python scripts/audit_site.py <url>` sans ✗.
- Commande test de bout en bout (paiement, e-mail de confirmation, remboursement test).
- Image de partage (Open Graph) correcte : tester l'aperçu en envoyant le lien dans une messagerie.
- Tunnel testé dans les navigateurs intégrés d'Instagram, de Facebook et de TikTok (les clics des vidéos y arrivent).
- Pages légales et bouton de rétractation présents (gate du module 10) ; livraison et retours déclarés (module 06).

## 11. Construire via connecteur (action directe)

Ordre : copie du thème (non publiée) → sections et contenus → produits en brouillon → pages légales → commande test →
lot présenté pour validation 🟠 → publication (module 12).

Sur Shopify, le champ « prix avant réduction » (compare-at price) affiche un prix barré : il est soumis à
l'art. L112-1-1 du Code de la consommation.
