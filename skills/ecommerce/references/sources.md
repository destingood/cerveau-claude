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

## Journal des versions

| Version | Date | Changements |
|---|---|---|
| 1.0.0 | 18/10/2026 | Pack initial : maître + 12 modules + script de marge |
| 1.1.0 | 18/10/2026 | Passe de vérification juridique et Shopify ; robots IA ; grille de citabilité ; modèles |
| 2.0.0 | 18/10/2026 | Intégré au cerveau (mémoire de chaque boutique, livré à tous par le plugin, générique) ; nouveaux modules 00 (décollage), 13 (boutique à 0 €), 14 (navigateur), 15 (recherche produit), 16 (marketplaces) ; algorithmes prouvés par le code (X 2026, Monolith, Reddit) ; Aperçus IA et Mode IA en France, contrôle « IA générative », livraison et retours en Search Console ; commerce agentique (ACP, UCP, AP2 : États-Unis seulement) ; conformité 2026 (bouton de rétractation, allégations environnementales, avis harmonisé, influence art. 5-2, mention CIBS) ; valeurs 2026 de la micro-entreprise ; scripts Python (marge corrigée : cotisations nettes des remboursements, port facturé, ventes pour se payer ; audit SEO/GEO express) |

## Protocole de mise à jour

- Tous les 3 mois : revérifier chaque élément volatil (algorithmes, règles des plateformes, frais des marketplaces,
  plans gratuits, textes de loi, disponibilité des canaux IA en France) et relire les nouveaux commits des dépôts
  listés.
- Chaque janvier : taux et plafonds de la micro-entreprise, seuils de TVA (module 09).
- Avant le 01/01/2027 : mention CIBS sur les factures, précompte des marketplaces, fin du régime simplifié de TVA.
- Avant le 01/09/2027 : émission des factures électroniques et e-reporting.
- Ajouter une ligne au journal des versions à chaque modification.
