# Module 06 — SEO e-commerce

Sommaire : 0. Ce que dit Google · 1. Priorités · 2. Mots-clés à 0 € · 3. Modèles on-page · 4. Données marchand et
structurées · 5. Check-list technique Shopify · 6. Plan de contenu · 7. Liens gratuits · 8. SEO programmatique ·
9. Outils gratuits · 10. Suivi

Le SEO est un actif qui compose : lance-le dès le premier jour, n'en attends pas les premières ventes (module 00).

## 0. Ce que dit Google (faits datés, état au 18/10/2026)

- **IA = SEO** : optimiser pour les Aperçus IA (AI Overviews) et le Mode IA, c'est faire du SEO ; aucun fichier ni
  balisage spécial n'est requis [FAIT — guide Google Search Central sur l'IA générative, 15/05/2026].
- **En France** : Aperçus IA et Mode IA lancés le 22/07/2026 [FAIT — blog Google France]. Les requêtes marchandes
  françaises sont concernées.
- **Contrôle « IA générative » de la Search Console** (Inclure par défaut, Exclure, Hériter) : pour servir de source
  dans les Aperçus IA, le Mode IA et l'IA de Discover, le site doit rester inclus. Ce n'est pas un signal de
  classement, et l'entraînement des modèles se règle à part (Google-Extended) [FAIT — aide Search Console 16908024].
- **Clics** : quand un résumé IA s'affiche, les internautes cliquent moins sur les résultats classiques (8 % des
  visites contre 15 % sans résumé, 1 % sur les liens du résumé) [FAIT — Pew Research Center, 07/2025, États-Unis]. La
  valeur se déplace vers le fait d'être **la source citée**, et vers la marque.
- **FAQ** : les résultats enrichis FAQ ne s'affichent plus depuis mai 2026 ; un balisage FAQPage existant ne gêne pas
  (des données structurées inutilisées ne posent pas de problème, selon Google) [FAIT].
- **Abus de contenu à grande échelle** : visé « quelle que soit la façon dont le contenu est créé », y compris les flux
  récupérés « même avec synonymisation ou traduction » → traduire en masse des fiches de fournisseur est visé [FAIT —
  règles anti-spam de Google].
- **Détournement du bouton Retour** : nouvelle règle anti-spam (annoncée le 13/04/2026) ; aucun script qui manipule
  l'historique pour empêcher de revenir en arrière ou rediriger vers une offre [FAIT pour l'existence de la règle].
- **Mises à jour 2026** : principales le 27/03 (environ 12 jours) et du 21/05 au 02/06 ; Discover le 05/02 ; anti-spam
  en mars, juin, août et le 24/09 [FAIT — Search Status Dashboard]. Ne juge une variation qu'après la fin du
  déploiement.
- Les partages sur les réseaux sociaux ne sont pas un facteur de classement direct [CONSENSUS].

## 1. Ordre de priorité pour une boutique

1. **Indexation** : Search Console (propriété + `/sitemap.xml`), Bing Webmaster Tools ; pages faibles en noindex
   (recherche interne, tags vides) ; une URL canonique par contenu ; contrôle « IA générative » sur Inclure.
2. **Architecture et intentions** : 1 intention = 1 URL. Collections = requêtes de catégorie à intention commerciale
   (« lampe de chevet tactile ») ; produits = longue traîne précise (modèle, attribut, usage) ; guides = requêtes
   informationnelles, avec liens vers les collections.
3. **On-page** : modèles de la section 3.
4. **Contenu unique** : descriptions réécrites à partir des caractéristiques vérifiées, jamais copiées ni traduites en
   masse depuis le fournisseur.
5. **Données marchand** : livraison et retours déclarés (section 4), balisage Product/Offer propre, sans doublon.
6. **Performance** : module 03 (Core Web Vitals mobiles).
7. **Contenu éditorial à valeur** : tests mesurés, guides d'usage, comparatifs honnêtes, photos originales
   (expérience réelle = E-E-A-T).
8. **Liens** : section 7.
9. **Suivi** : section 10.

## 2. Recherche de mots-clés à 0 €

- Search Console (dès les premières impressions) : filtre requêtes de marque / hors marque, groupes de requêtes.
- Autocomplétion de Google, YouTube, TikTok, Amazon, Pinterest ; « Autres questions posées ».
- Google Trends (saisonnalité, comparaison de termes).
- Planificateur de mots-clés de Google Ads : gratuit en mode Expert, avec informations de facturation et une campagne
  créée puis mise en pause, sans aucune dépense [FAIT — aide Google Ads] ; volumes en fourchettes sans dépense
  [NON VÉRIFIÉ].
- Vocabulaire des forums, de Reddit et des avis clients (module 15, voix du client).

Priorisation : intention commerciale × faisabilité. La faisabilité se lit dans la page de résultats : si des forums,
de petites boutiques ou des pages pauvres sont classés, l'opportunité existe. Les scores d'« autorité de domaine »
sont des métriques d'outils tiers, pas des mesures de Google.

## 3. Modèles on-page

| Élément | Modèle | Règle |
|---|---|---|
| Title SEO (produit) | [Produit + attribut clé] – [bénéfice ou usage] \| [Marque] | 60 caractères au plus ; unique ; différent du titre affiché si besoin |
| Meta description | Bénéfice + preuve + livraison/retours | 155 caractères au plus ; sert le taux de clic, pas le classement [CONSENSUS] |
| H1 | Nom clair du produit ou de la collection | Un seul par page |
| Intro de collection | 80 à 150 mots utiles + FAQ visible | Pas de texte de remplissage |
| Texte alternatif | Ce que montre la photo (le produit, pas le mannequin), sans deviner une matière | Ni vide, ni recopié d'une image à l'autre, ni nom de fichier |
| URL (handle) | Courte, en minuscules, avec tirets | Stable ; sinon redirection 301 |
| Langue | Celle du pays de vente, déclarée (`lang="fr"`) | Jamais celle du fournisseur par défaut |

Écrire par connecteur (module 12) : aucun fait inventé (un fait manquant devient « [?] » et il est signalé) ; un champ
déjà bon n'est pas réécrit ; au-delà de 20 produits, présenter un échantillon avant de tout traiter.

## 4. Données marchand et structurées

**Où déclarer livraison et retours** [FAIT — Google, novembre 2025] : réglages Shopping de la Search Console
(Paramètres › Shopping, sans compte Merchant Center) ou Merchant Center. Ces réglages priment sur le balisage
produit, qui prime sur le balisage d'organisation. Choisir **un seul endroit** (rien ne migre d'un outil à l'autre),
et rester identique à la page « Livraison et retours ».

**Balisage** [FAIT — documentation des fiches marchandes de Google] :
- `Product` (ou `ProductGroup` si variantes) + `Offer` : nom, images, description, prix, devise, disponibilité, GTIN
  ou référence fabricant, marque ;
- `Organization` : nom, logo, url, `sameAs` (réseaux, marketplaces), et au niveau de l'organisation
  `hasMerchantReturnPolicy` et `hasShippingService` ; `shippingDetails` dans l'offre seulement pour les exceptions ;
- depuis juillet 2026 : `category` et dates de promotion (`validFrom` avec `validThrough` ou `priceValidUntil`), à
  aligner sur l'art. L112-1-1 (prix de référence) ;
- `AggregateRating` et `Review` seulement si les avis sont réels et visibles sur la page ;
- `BreadcrumbList` sur les fiches et collections.

Contrôles : test des résultats enrichis, validateur Schema.org, `python scripts/audit_site.py <url>`. Un seul JSON-LD
produit : écarter les apps qui dupliquent celui du thème ; un balisage injecté en JavaScript est lu moins vite et
moins sûrement par Google Shopping [CONSENSUS].

## 5. Check-list technique Shopify 2026

**Exploration**
- Un seul domaine principal ; avec Cloudflare, enregistrements DNS en « DNS only » (Shopify ne prend pas en charge le
  proxy Cloudflare) [FAIT — aide Shopify].
- Sitemap généré automatiquement (`/sitemap.xml` + sous-sitemaps) ; un produit en brouillon en sort ; soumettre
  uniquement `/sitemap.xml`.
- robots.txt : laisser celui par défaut sauf besoin précis (module 07, section 3). Personnalisation via
  `templates/robots.txt.liquid` (non prise en charge par le support Shopify) : sauvegarder avant, puis comparer
  `/robots.txt` en ligne. Attention [SECONDAIRE — forum des développeurs Shopify, 2026] : la boucle
  `robots.default_groups` produirait un jeu de règles plus ancien que le fichier servi (qui réinterdit `/search` et
  `/policies/`) → copier `/robots.txt` avant, comparer après ; au besoin, coller le contenu en dur dans le modèle.
- Liens produits en `product.url` dans les vignettes et produits associés : les URL `/collections/x/products/y`
  (filtre `within: collection`) peuvent faire retenir la mauvaise canonique par Google.
- Changement de handle : cocher « créer une redirection » ; produit retiré définitivement : 301 vers un produit
  équivalent ou la collection, jamais vers l'accueil [CONSENSUS].

**Données**
- Le filtre Liquid `structured_data` produit un `Product` ou un `ProductGroup` ; le thème Horizon ajoute
  `Organization` (nom, logo, url) ; ni fil d'Ariane, ni `sameAs`, ni livraison et retours : à compléter [FAIT —
  shopify.dev, code d'Horizon].
- GTIN renseigné s'il existe ; prix barré (compare-at price) conforme à l'art. L112-1-1.
- Images générées par IA : métadonnées exigées par Merchant Center [À VÉRIFIER : aide Merchant Center].

**Pages et apps**
- Thème officiel gratuit (Horizon est désormais le thème phare) ; chaque app justifie le JavaScript qu'elle ajoute.
- Apps gratuites éditées par Shopify : Search & Discovery (filtres), Translate & Adapt (traductions), Shopify Markets
  (international) [À VÉRIFIER : conditions du jour].
- Titles uniques ; Core Web Vitals mobiles ; aucun script de « retour arrière » ; pages de politiques complètes.

## 6. Plan de contenu e-commerce

| Type | Exemple | Structure | Garde-fou |
|---|---|---|---|
| Collection | « lampe de chevet tactile » | H1, intro de 80 à 150 mots, FAQ visible, liens vers les guides | Une intention par URL |
| Guide | « comment choisir… » | Réponse en 2 phrases, critères mesurés, tableau | Données datées |
| Comparatif | « A ou B pour [usage] » | Tableau de critères vérifiables, « pour qui », verdict | Unités métriques ; faits sourcés |
| Alternative | « alternative à [produit connu] » | Pourquoi chercher une alternative, 4 à 7 options réelles, pour qui / pas pour qui | Publicité comparative licite si objective et vérifiable (C. conso., art. L122-1) ; aucun dénigrement ; imitation interdite (art. L122-2, 4°, et L121-4, 13°) ; jamais de page « dupe de… » (présenter un produit comme l'imitation d'une marque est interdit) |
| Donnée originale | Sondage clients, test mesuré | Méthode, résultats, limites | Citable (GEO, liens) |

Discipline de preuve pour toute page qui parle d'un concurrent : chaque fait daté ; « non constaté » n'est pas
« absent » ; revue trimestrielle (à jour, changé, invérifiable, excessif → corriger). Pas de « top 10 » à la chaîne :
citer d'abord le leader honnêtement, puis dire où l'on va plus loin.

## 7. Liens gratuits (sans schéma artificiel)

- Fabricants et fournisseurs : pages « où acheter » ou listes de revendeurs.
- Presse locale : histoire d'entrepreneur, angle régional (module 04).
- Contenus citables : petite étude ou sondage original, test mesuré (utile aussi pour le GEO).
- Mentions sans lien : demander poliment l'ajout du lien.
- Partenaires complémentaires, podcasts et interviews de niche ; outils gratuits utiles (quiz, calculateurs) que
  d'autres sites citent.
- Annuaires locaux et professionnels sérieux.

À éviter : achat de liens, réseaux de sites, échanges massifs, « parasite SEO » (règles anti-spam de Google).

## 8. SEO programmatique

Seulement si chaque page apporte une donnée unique et utile (compatibilités, tailles, comparaisons mesurées). Sinon,
c'est de l'abus de contenu à grande échelle, quelle que soit la façon dont les pages sont produites.

## 9. Outils gratuits

| Outil | Pour quoi |
|---|---|
| Google Search Console | Indexation, requêtes, rapport « IA générative » (impressions dans les Aperçus IA et le Mode IA, par page et par pays), filtre marque / hors marque, annotations, réglages Shopping (livraison, retours), propriétés de comptes TikTok, Instagram, X et YouTube (présence des vidéos dans Google) [FAIT — blogs Search Central 2025-2026] |
| Bing Webmaster Tools | Index Bing (qui alimente Copilot) ; rapport « AI Performance » (citations dans Copilot et les résumés IA de Bing, pages citées, requêtes d'ancrage ; données échantillonnées, sans clics) [FAIT — blog Bing, 02/2026 et 06/2026] |
| IndexNow | Signaler une URL nouvelle ou modifiée aux moteurs participants (Bing et d'autres ; pas Google) ; gratuit, sans garantie d'indexation [FAIT — indexnow.org] ; intégré nativement par Shopify selon Bing (19/05/2025) : aucune application nécessaire [FAIT*] |
| Google Merchant Center, Microsoft Merchant Center | Fiches produits gratuites (module 07) |
| PageSpeed Insights / Lighthouse | Core Web Vitals mobiles |
| Test des résultats enrichis, validateur Schema.org | Données structurées |
| `scripts/audit_site.py` | Audit express : balises, données structurées, robots des moteurs et des IA, sitemap ; `--pages 20` : pages du sitemap en erreur, redirigées, en noindex, titres et descriptions absents ou en double, fiches sans Product ; `--vitesse` : Core Web Vitals |
| `scripts/audit_catalogue.py` | Tout le catalogue : titres, descriptions (doublons, texte fournisseur, anglais), images et textes alternatifs, GTIN, SEO de chaque fiche ; `--flux flux.tsv` : flux Merchant Center |
| Google Trends | Saisonnalité |
| Ahrefs Webmaster Tools, Screaming Frog (version gratuite) | Audit de site, liens [À VÉRIFIER : limites des plans gratuits] |

## 10. Suivi

- Requêtes à beaucoup d'impressions et peu de clics → réécrire title et description.
- Pages en positions 8 à 20 → enrichir le contenu et le maillage interne.
- Une annotation Search Console par changement important ; lecture séparée marque / hors marque.
- Rapport « IA générative » : pages qui apparaissent dans les Aperçus IA en France (module 07, mesure).
- Revue mensuelle consignée dans le cerveau (`brain obs`, et `brain add -t learning` pour une leçon durable).
