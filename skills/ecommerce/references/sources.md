# Sources, dépôts et versions

Aucun texte de ces dépôts n'a été recopié : les principes ont été reformulés, croisés avec les sources officielles et
adaptés au droit français. Les chiffres et règles volatils portent leur date ; revérifie-les avant de les affirmer.

## Dépôts GitHub utilisés comme base (lus le 18/10/2026)

**Marketing, conversion, e-commerce**

| Dépôt | Licence | Ce qui en est repris |
|---|---|---|
| coreyhaines31/marketingskills | MIT | Fiche contexte partagée ; offre en 6 éléments ; rareté honnête ; garantie ; tests de prix ; formulaires, pop-ups, recette avant lancement ; rédaction et relecture ; modèle possédé/loué/emprunté ; presse ; parrainage ; avis ; aimants et outils gratuits ; pages comparatives ; UTM ; psychologie (avec garde-fous) |
| thatrebeccarae/claude-marketing | MIT | Grille LIFT, grille PIE, flows e-mail, méthode CAB |
| storehand/storehand | Apache-2.0 | Écriture en deux temps, relecture avant écriture, résultat inconnu, contrôle de santé hebdomadaire, règles des métadonnées produit |
| slavingia/skills | MIT déclaré | Cercles concentriques ; éduquer, inspirer, divertir |
| retieedra-profound/skills-marketing-library | MIT | Éligibilité aux surfaces d'achat IA, UTM par partenaire |

**SEO et GEO**

| Dépôt | Licence | Ce qui en est repris |
|---|---|---|
| AgriciDaniel/claude-seo | MIT | Registre daté des mises à jour de Google (à revérifier) ; robots séparés par fonction ; règle de la RFC 9309 |
| aaron-he-zhu/aaron-marketing-skills (ex-seo-geo-claude-skills) | Apache-2.0 | Formats de pages comparatives et « alternatives » ; observation des citations |
| zubair-trabzada/geo-seo-claude | MIT | Détection du robots.txt géré par Cloudflare (le reste n'est pas repris : erreurs sur les robots IA) |
| Auriti-Labs/geo-optimizer-skill | MIT | Étude de calibration : un score GEO composite ne prédit pas la citation |
| GEO-optim/GEO (Princeton) | Apache-2.0 | Méthodes et limites de GEO-Bench |
| DavidHuji/Awesome-GEO | — (bibliographie) | Études académiques sur le GEO |
| Shopify/horizon | Licence Shopify | Constat sur le balisage du thème (aucun code repris) |

**Algorithmes de recommandation**

| Dépôt | Licence | Ce qui en est repris |
|---|---|---|
| xai-org/x-algorithm | Apache-2.0 | Poids de production (17/10/2026), créneau de test des nouveaux posts, filtres, diversité, visibilité |
| twitter/the-algorithm | AGPL-3.0 | Pipeline, filtres, diversité d'auteurs, décote hors réseau, lassitude sur 140 jours (mise à jour du 03/09/2025) |
| twitter/the-algorithm-ml | AGPL-3.0 | Poids du « heavy ranker » de 2023, agrégats sur 30 minutes et 50 jours |
| bytedance/monolith | Apache-2.0 | Entraînement en temps réel, synchronisation des paramètres |
| reddit-archive/reddit | CPAL-1.0 | Formules « hot », « best » (borne de Wilson) |
| googleapis/elixir-google-api | Apache-2.0 | Preuve datée de la fuite de 2024 (champs NavBoost), sans conclusion sur les poids |

**Canaux, conditions des plateformes, commerce agentique, gestion**

| Dépôt | Licence | Ce qui en est repris |
|---|---|---|
| OpenTermsArchive/france-versions, vlopses-ie-versions, pga-versions, contrib-versions, p2b-compliance-versions | ODC-BY 1.0 (Open Terms Archive et contributeurs, dont UFC-Que Choisir et l'Ambassadeur pour le numérique) | Conditions d'utilisation datées : automatisation (Instagram, Facebook, TikTok, Reddit, LinkedIn, Vinted, Pinterest, Google), règles communautaires TikTok, YouTube, Pinterest, paramètres de classement Etsy, eBay, Vinted |
| awesome-directories/awesome-directories, mmccaff/PlacesToPostYourStartup, DirectorySurf/awesome-producthunt-alternatives, goabstract/Marketing-for-Engineers | Apache-2.0, CC0-1.0, MIT, CC-BY-SA-3.0 | Lieux de lancement (filtrés : plus de 90 % visent le SaaS ; soumission en masse à des annuaires déconseillée) |
| stripe/openapi | MIT | Champs de conformité des liens de paiement |
| microsoft/playwright-mcp, ChromeDevTools/chrome-devtools-mcp, browser-use/browser-use | Apache-2.0, Apache-2.0, MIT | Options de pilotage du navigateur et leurs limites |
| agentic-commerce-protocol/agentic-commerce-protocol | Apache-2.0 | Objet et état d'ACP |
| universal-commerce-protocol/ucp | Apache-2.0 | Objet, état et feuille de route d'UCP |
| google-agentic-commerce/AP2 | Apache-2.0 | Mandats de paiement par agent |
| betagouv/mon-entreprise | MIT | Recoupement des règles de la micro-entreprise (code des simulateurs de l'URSSAF) |
| Dolibarr/dolibarr | GPL-3.0 | Logique de réassort (min-max), option de gestion libre |
| anthropics/skills et la spécification Agent Skills | — | Format SKILL.md, chargement progressif |

## Recherche

- Aggarwal et al., *GEO: Generative Engine Optimization*, KDD 2024 (arXiv:2311.09735).
- C-SEO Bench, NeurIPS 2025 (arXiv:2506.11097) ; E-GEO (arXiv:2511.20867) ; Chen et al. 2025 (arXiv:2509.08919) ;
  Wan et al. 2024 (arXiv:2402.11782).
- Pew Research Center, comportement de clic face aux résumés IA (22/07/2025).
- Monolith, ByteDance (arXiv:2209.07663).

## Documentation officielle et textes

- **Google** : guide sur l'IA générative (15/05/2026) ; « AI features and your website » ; aide Search Console
  (contrôle « IA générative », réglages Shopping) ; blogs Search Central 2025-2026 ; règles anti-spam ; fiches
  marchandes ; Search Status Dashboard ; aide Merchant Center ; Google Business Profile ; blog Google France
  (Aperçus IA et Mode IA en France, 22/07/2026).
- **Microsoft** : blog Bing Webmaster (AI Performance, 02/2026 et 06/2026) ; aide Microsoft Merchant Center ;
  indexnow.org.
- **OpenAI** : robots ; chatgpt.com/merchants ; billet du 24/03/2026 ; publicités en Europe (18/08/2026).
- **Anthropic** : robots (aide, 07/04/2026) ; Claude in Chrome (aide et blog) ; Claude Code + Chrome.
- **Perplexity, Apple, Meta** : documentation des robots ; aide Perplexity Shopping ; Apple Business (03/2026).
- **Shopify** : shopify.dev (robots.txt, agents.md, llms.txt, filtre `structured_data`, WebMCP) ; aide Agentic
  Storefronts et Shopify Catalog ; App Store (Shopify Messaging, Inbox, Judge.me).
- **Plateformes** : TikTok Newsroom et aide vendeurs ; Instagram (déclarations d'Adam Mosseri) ; Meta Transparency
  Center ; aides Etsy, eBay, Vinted, Leboncoin, Pinterest, Dealabs, Reddit, Product Hunt, Ulule ; licences CapCut et
  Canva.
- **France et UE** : Légifrance et base LEGI de la DILA (Code de la consommation, CSS, Code du travail, CIBS) ;
  impots.gouv.fr, BOFiP ; URSSAF ; economie.gouv.fr (DGCCRF, facturation électronique) ; CNIL (prospection, traceurs,
  mesure d'audience) ; règlements (UE) 2023/988, 2025/1960, 2019/1150, 2022/2065 ; directive (UE) 2024/825 ;
  web.dev (Core Web Vitals).

## Limites de la vérification du 18/10/2026

Le réseau de l'environnement de recherche bloquait l'accès direct à plusieurs sites officiels : beaucoup de pages ont
été lues par extraits de moteur de recherche, et le quota de recherches a été atteint. Les points restés incertains
sont marqués [À VÉRIFIER] ou [NON VÉRIFIÉ] dans les modules ; à la première utilisation, vérifie-les en direct.

**[FAIT\*]** (version 2.1.0) : valeur lue dans un extrait de moteur de recherche filtré sur le domaine officiel (page
non ouverte directement), parfois recoupée par une copie archivée (Open Terms Archive) ou par la spécification
publique de l'API Stripe. Fiable pour décider, à relire sur la page officielle avant de l'affirmer à un client.
Publication par API (vérifiée le 18/10/2026, version 2.2.0) : YouTube (verrouillage en privé des projets non audités,
quotas), Pinterest v5 (accès d'essai en bac à sable, accès Standard, règle du choix de chaque épingle), API de
publication Instagram et API des Pages (accès Standard, limite de 100 posts sur 24 h, règle de pré-remplissage),
TikTok (outils personnels exclus), LinkedIn (politique IA), X (fin de l'offre gratuite, prix à l'usage), Google
Business Profile (accès sur demande, boutiques en ligne non éligibles), Shopify (apps du Dev Dashboard, jeton de 24 h)
[FAIT* — extraits des domaines officiels].

Restent ouverts au 18/10/2026 : taux de Shopify Payments en France (à lire dans l'admin), taux Stripe des cartes
premium de l'EEE (2,8 % ou 1,9 %), montant de la Protection acheteurs Pro de Vinted, taux eBay de la catégorie Maison
(9 % ou 11 %), fiches gratuites Microsoft sans campagne, acceptation d'une page de paiement externe par Merchant
Center, promulgation de la loi de transposition de la directive (UE) 2024/825, présence de la France dans les filtres
du Creative Center de TikTok, visibilité publique des posts publiés par une app Meta sans revue, audit YouTube ou
accès Standard Pinterest pour un outil personnel, clause des conditions de l'API LinkedIn sur l'automatisation.

## Journal des versions

| Version | Date | Changements |
|---|---|---|
| 1.0.0 | 18/10/2026 | Pack initial : maître + 12 modules + script de marge |
| 1.1.0 | 18/10/2026 | Passe de vérification juridique et Shopify ; robots IA ; grille de citabilité ; modèles |
| 2.0.0 | 18/10/2026 | Intégré au cerveau (mémoire de chaque boutique, livré à tous par le plugin, générique) ; nouveaux modules 00 (décollage), 13 (boutique à 0 €), 14 (navigateur), 15 (recherche produit), 16 (marketplaces) ; algorithmes prouvés par le code (X 2026, Monolith, Reddit) ; Aperçus IA et Mode IA en France, contrôle « IA générative », livraison et retours en Search Console ; commerce agentique (ACP, UCP, AP2 : États-Unis seulement) ; conformité 2026 (bouton de rétractation, allégations environnementales, avis harmonisé, influence art. 5-2, mention CIBS) ; valeurs 2026 de la micro-entreprise ; scripts Python (marge corrigée : cotisations nettes des remboursements, port facturé, ventes pour se payer ; audit SEO/GEO express) |
| 2.1.0 | 18/10/2026 | Des outils qui produisent des résultats : suivi de chaque boutique dans le cerveau (`brain boutique` : plan daté de J0 à J90, relevé hebdomadaire avec test statistique, goulot, marge par heure par canal, audits en historique, bilan) ; `audit_site.py` étendu (conformité légale, pages du sitemap, Core Web Vitals via PageSpeed Insights, rapport Markdown) ; `audit_catalogue.py` (tout le catalogue, flux Merchant Center) ; `relire_texte.py` (allégations interdites, fausse urgence, partenariats) ; `unit_economics.py` (comparaison des canaux, prix testés) ; modèles de textes ; frais 2026 vérifiés (Stripe, Shopify, Etsy, Vinted Pro, Leboncoin, eBay, TikTok Shop, Amazon) ; références juridiques précisées (L121-4 10°, 13°, 21°, 27°, 28° ; L310-3 et L442-5 ; L223-1 ; art. 5-2 et 8 de la loi influence ; D221-5) |
| 2.2.0 | 18/10/2026 | Autonomie : le cerveau agit puis rend compte sur les outils du marchand (journal avant → après, retour arrière), ne pose de questions que pour l'introuvable (hypothèses écrites), publie par API officielle branchée une fois, après un « oui » sur le lot de la semaine (`publier.py` : page Facebook programmable, Instagram professionnel, fichier d'import en masse Pinterest ; YouTube et Shopify par leurs connecteurs ; TikTok exclu : API fermée aux outils personnels) ; niveaux 🟢🤖🟠👤🔴 |

## Protocole de mise à jour

- Tous les 3 mois : revérifier chaque élément volatil (algorithmes, règles des plateformes, frais des marketplaces,
  plans gratuits, textes de loi, disponibilité des canaux IA en France) et relire les nouveaux commits des dépôts
  listés.
- Chaque janvier : taux et plafonds de la micro-entreprise, seuils de TVA (module 09).
- Avant le 01/01/2027 : mention CIBS sur les factures, précompte des marketplaces, fin du régime simplifié de TVA.
- Avant le 01/09/2027 : émission des factures électroniques et e-reporting.
- Ajouter une ligne au journal des versions à chaque modification.
