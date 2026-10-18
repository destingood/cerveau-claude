# Module 16 — Marketplaces : vendre là où les acheteurs sont déjà

Les marketplaces prêtent leur trafic (canal « loué ») : c'est souvent le chemin le plus court vers les premières
ventes, et le cœur du chemin 0 € (module 13). En échange : commissions, règles strictes, peu de marque. Les frais
changent souvent : relis la page officielle avant de calculer (`scripts/unit_economics.py --commission-pct …`).

## 1. Règles communes

- **Statut professionnel obligatoire** dès que l'activité est professionnelle (Vinted Pro, Leboncoin Pro, comptes
  professionnels eBay et Etsy) ; se présenter comme un particulier est une pratique trompeuse (module 10).
- **Photos et textes originaux** : photos prises soi-même, titres qui reprennent les mots tapés par les acheteurs
  (marque, modèle, taille, couleur, état, usage), descriptions honnêtes en unités métriques.
- **Prix comparé port compris** : la plupart des classements tiennent compte du prix total.
- **Réactivité et notes** : temps de réponse, délais tenus, litiges évités pèsent sur la visibilité.
- **Ne pas détourner les acheteurs hors de la plateforme** pour éviter les frais : souvent interdit par les conditions
  [À VÉRIFIER pour chaque plateforme avant tout encart dans les colis].
- **Fiscalité** : les plateformes déclarent leurs vendeurs (DAC7 : dès 30 ventes ou plus de 2 000 € par an) et
  prélèveront cotisations et impôt à la source à partir de 2027 (module 09).
- **Aucune automatisation** (publication, relance, collecte) : interdite par leurs conditions (module 14).

## 2. Fiches par marketplace (état au 18/10/2026)

| Marketplace | Frais | Ce qui compte pour la visibilité | Pièges | Statut |
|---|---|---|---|---|
| **Vinted Pro** | Inscription et publication gratuites ; l'acheteur paie une protection acheteurs ; commission vendeur [À VÉRIFIER : sources contradictoires] | Tri par pertinence : requête, préférences et historique de l'acheteur, date de mise en ligne ; **à pertinence égale, les articles des particuliers passent devant ceux des Pros** (CGU, art. 3.5, version archivée) | Canal d'appoint pour un pro ; immatriculation (SIRET) et vérification d'identité | [FAIT pour le texte archivé ; version en vigueur À VÉRIFIER] |
| **Leboncoin Pro** | Compte pro gratuit et obligatoire ; jusqu'à 50 annonces offertes en « Biens de consommation », puis payant ou abonnement ; option sans frais d'insertion avec paiement sécurisé et commission | Paramètres de classement publiés par la plateforme (obligation du règlement (UE) 2019/1150) : à lire avant de recommander | Services et animaux payants | [FAIT pour les frais ; classement NON VÉRIFIÉ] |
| **eBay.fr (pro)** | Pourcentage selon la catégorie sur le total (port et TVA compris), plus 0,35 € par commande ; frais réglementaires ; conversion de devise à 3,25 % à partir du 02/12/2026 ; frais majorés si la performance du vendeur est insuffisante | « Meilleurs résultats » : pertinence pour la requête, localisation, format, **prix port compris**, conditions (retours), historique ; notes détaillées, taux de défauts ; doublons d'annonces interdits ; indexation jusqu'à 24 h | Performance vendeur surveillée | [FAIT — aide et conditions eBay] |
| **Etsy** | 0,18 € par annonce, frais de transaction et de paiement (pourcentage + part fixe) ; publicités hors Etsy (« Offsite Ads ») : 15 %, désactivables sous 10 000 $ de ventes sur 365 jours, puis 12 % obligatoires | Correspondance de la requête (tags, titres, attributs, catégories) ; score de qualité de l'annonce (clics, favoris, achats) ; petit coup de pouce aux **nouvelles** annonces (plus faible pour un renouvellement) ; score d'expérience client (avis, À propos, politiques, délais) ; frais de port | **Revente d'objets fabriqués en série interdite** (normes de créativité, 2024) : créations, personnalisation, vintage seulement | [FAIT — divulgations de classement d'Etsy du 16/02/2024, aide Etsy] |
| **TikTok Shop** (France depuis le 31/03/2025) | Commission 9 % (7 % sur certaines catégories électroniques) depuis le 08/01/2026 ; 4 % pendant 60 jours pour un premier magasin dans l'UE (mission à accepter) | Vidéos et lives qui démontrent le produit ; affiliation de créateurs (taux fixé par le vendeur) | Règles de contenu de TikTok (module 05) ; logistique et délais suivis | [FAIT — aide vendeurs TikTok ; taux à revérifier] |
| **Boutiques Facebook / Instagram** | 0 € | Qualité de l'annonce (images, description, prix et disponibilité exacts) et signaux de confiance (performance, avis) | En France, renvoi vers le site pour payer | [FAIT] |
| **Places de marché à abonnement** (Amazon, Cdiscount, Fnac, ManoMano, Rakuten…) | Abonnement ou frais par article selon l'offre [À VÉRIFIER] | Propres à chacune | Hors chemin 0 € si abonnement mensuel | [À VÉRIFIER] |

## 3. Méthode en 5 étapes

1. **Choisir 1 marketplace** selon le produit : seconde main et mode → Vinted (appoint) ou Leboncoin ; objets
   techniques, pièces, collection → eBay ; créations et personnalisation → Etsy ; produit démontrable en vidéo →
   TikTok Shop.
2. **Calculer la marge** avec la commission réelle (`scripts/unit_economics.py --commission-pct …`) ; ajuster le prix
   ou le bundle avant de publier.
3. **Publier 3 à 10 annonces soignées** (pas 100 annonces bâclées) : titres avec les mots des acheteurs, 5 photos
   originales minimum (fond neutre, échelle, détails, usage), description courte et exacte, conditions claires.
4. **Mesurer 14 jours** : vues, favoris, messages, ventes par annonce ; améliorer titres et photos des annonces qui ont
   des vues sans favoris ; nouvelles annonces plutôt que renouvellements quand la plateforme favorise la nouveauté.
5. **Relier au canal possédé** : carte de remerciement (dans les limites des conditions), marque et nom de domaine
   identiques partout, avis demandés sur la plateforme.

Le cerveau garde, par marketplace, les frais vérifiés et datés et ce qui a marché (`brain add -t learning …`).
