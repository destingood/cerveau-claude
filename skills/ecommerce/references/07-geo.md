# Module 07 — GEO : assistants IA et commerce agentique

Objectif : que la boutique soit **trouvée, citée et recommandée** par les assistants IA (Aperçus IA et Mode IA de
Google, ChatGPT, Copilot, Perplexity, Claude, Gemini), gratuitement, et qu'elle soit prête le jour où l'achat par
agent ouvrira en France.

Sommaire : 0. État au 18/10/2026 · 1. Plan d'action · 2. Robots IA · 3. robots.txt sur Shopify · 4. Ce que disent les
études · 5. Commerce agentique · 6. Mesure · 7. À éviter

## 0. État au 18/10/2026

| Canal | Ce qui est établi | Disponible en France ? | Statut |
|---|---|---|---|
| Google : Aperçus IA et Mode IA | Pour servir de source : page indexée, éligible à un extrait, et site **inclus** dans le contrôle « IA générative » de la Search Console. Aucun fichier ni balisage spécial. Les réponses s'appuient sur plusieurs recherches connexes (« query fan-out ») | **Oui, depuis le 22/07/2026** | [FAIT — Google Search Central, aide 16908024, blog Google France] |
| ChatGPT (recherche) | OAI-SearchBot autorisé dans robots.txt (prise en compte en ~24 h) ; GPTBot (entraînement) se règle à part ; ChatGPT-User agit à la demande d'un utilisateur | Oui (réponses qui citent le web) | [FAIT — documentation des robots d'OpenAI] |
| ChatGPT (résultats produits) | Résultats produits organiques, gratuits pour le marchand ; mis en avant selon disponibilité, prix, qualité, et fabricant ou vendeur principal. Programme marchands « live in the U.S. » ; OpenAI a renoncé au paiement autonome dans le chat (l'achat se termine chez le marchand) | Programme : États-Unis. Affichage pour un utilisateur en France : non documenté | [FAIT — chatgpt.com/merchants, billet OpenAI du 24/03/2026] ; affichage FR [NON VÉRIFIÉ] |
| Publicités ChatGPT | Ouvertes dans 31 marchés européens depuis le 18/08/2026 | Oui | [FAIT] — hors périmètre 0 € |
| Bing et Copilot | Copilot s'appuie sur l'index Bing ; Bing Webmaster Tools mesure les citations (« AI Performance ») ; fiches gratuites de Microsoft Merchant Center (la France figure dans la liste) | Oui pour les fiches ; Copilot Checkout : États-Unis | [FAIT — blog Bing 02/2026, aide Microsoft Advertising] |
| Perplexity | PerplexityBot (recherche, sans entraînement) ; Shopping et achat intégré | Réponses : oui ; achat : États-Unis | [FAIT — documentation des robots de Perplexity, centre d'aide 07/2026] |
| Shopify Agentic Storefronts | Catalogue proposé dans ChatGPT, Copilot, Mode IA, Gemini, Meta (canal ajouté le 08/09/2026), géré depuis l'admin. Conditions : vendre aux États-Unis (ChatGPT, Copilot) ; boutique basée aux États-Unis (Mode IA, Gemini) ; Shopify Catalog : produits expédiés vers les États-Unis ou le Canada | **Non** pour une boutique qui ne vend qu'en France ou dans l'UE | [FAIT — aide Shopify, rubrique Agentic Storefronts] |
| Shopify, côté agents | Chaque boutique sert par défaut `/agents.md` (et `/llms.txt`, sa copie) et expose des outils WebMCP, dont la recherche dans les politiques et la FAQ (05/08/2026) | Oui | [FAIT — shopify.dev] |
| llms.txt | Ignoré par Google Search ; la grande majorité des fichiers ne sont jamais lus | — | [FAIT — Google, 15/06/2026 ; Ahrefs, 05/2026] → ne pas y passer de temps (Shopify le génère déjà) |

## 1. Plan d'action (France, 0 €)

1. **Être dans les index** — Googlebot, Bingbot, OAI-SearchBot, PerplexityBot, Claude-SearchBot et Applebot ne doivent
   être bloqués ni par robots.txt ni par un pare-feu ; contrôle « IA générative » de la Search Console sur Inclure ;
   sitemap soumis à Google et à Bing. Contrôle en une commande : `python scripts/audit_site.py <url>`.
2. **Choisir pour l'entraînement** — autoriser (option A, par défaut : ne rien faire) ou refuser les robots
   d'entraînement sans toucher à la recherche (option B, section 3).
3. **Données produit irréprochables** — Google Merchant Center (fiches gratuites) : titres explicites, GTIN ou
   référence fabricant, marque, attributs chiffrés (cm, kg, ml), prix et stock exacts, livraison et retours ;
   importer le même flux dans **Microsoft Merchant Center** (fiches gratuites Bing, qui nourrissent Copilot) ; flux
   supplémentaire avec `question_and_answer` (vraies questions de clients : 30 paires au plus, 1 000 caractères par
   élément, ni prix ni dates) et `related_product` (accessoires, substituts) [FAIT — aide Merchant Center : attributs
   utilisables dans tous les pays] ; effet en France [HYPOTHÈSE].
4. **Politiques exactes, en français** — CGV, livraison, retours (rétractation de 14 jours), confidentialité, contact :
   les agents les lisent et Shopify les expose directement (WebMCP).
5. **Une seule identité** — même nom, logo, description et coordonnées partout (site, Merchant Center Google et
   Microsoft, réseaux, marketplaces, annuaires) ; `Organization` avec `sameAs`. ChatGPT favorise le fabricant ou le
   vendeur principal : être la source officielle de ses propres produits.
6. **Contenu citable** — réponse directe en début de section ; tableaux comparatifs ; caractéristiques chiffrées ;
   données originales (test maison avec méthode, sondage clients) ; FAQ visible reprenant les vraies questions (les
   mêmes que `question_and_answer`) ; données datées.
7. **Présence chez les tiers** — les moteurs IA s'appuient surtout sur des sources tierces (« earned media ») :
   comparatifs et blogs de niche, discussions authentiques sur les forums et Reddit, tests vidéo, presse, avis
   vérifiés, marketplaces (module 04). Les mentions artificielles sont détectées et inutiles.
8. **Canaux agentiques** — revérifier chaque trimestre l'éligibilité dans l'aide Shopify. Accepter des conditions
   supplémentaires = décision de l'utilisateur (🔴, module 12) ; n'ouvre pas la livraison vers les États-Unis
   seulement pour devenir éligible sans étude des douanes, de la fiscalité et du SAV [HYPOTHÈSE].
9. **Mesure** — section 6.

## 2. Robots IA (documentation de chaque éditeur, vérifiée le 18/10/2026)

| Agent | Rôle | robots.txt |
|---|---|---|
| Googlebot | Search, Aperçus IA, Mode IA | respecté |
| Google-Extended | Jeton seulement : entraînement et ancrage de Gemini et Vertex AI ; aucun effet sur Search | respecté |
| Google-Agent | Agents agissant à la demande d'un utilisateur (depuis le 20/03/2026) | ignoré en général [CONSENSUS] |
| OAI-SearchBot | Recherche ChatGPT | respecté |
| GPTBot | Entraînement OpenAI | respecté |
| ChatGPT-User | Pages ouvertes à la demande d'un utilisateur | « peut ne pas s'appliquer » |
| Claude-SearchBot / Claude-User / ClaudeBot | Recherche / demande d'un utilisateur / entraînement (Crawl-delay pris en charge) | respecté |
| PerplexityBot / Perplexity-User | Recherche, sans entraînement / demande d'un utilisateur | respecté / ignoré en général |
| Applebot / Applebot-Extended | Siri, Spotlight / refus de l'entraînement (ne visite aucune page) | respecté |
| Meta-ExternalAgent / facebookexternalhit | Entraînement et indexation des produits / aperçus de liens partagés (ne jamais bloquer) | respecté / peut être ignoré |
| Bingbot | Index Bing, qui alimente Copilot | respecté [CONSENSUS] |

**Cloudflare** : depuis le 01/07/2025, Cloudflare propose de bloquer les robots IA dès l'inscription d'un nouveau
domaine, et son robots.txt géré ajoute une préférence `Content-Signal` [FAIT]. Shopify ne prend pas en charge le proxy
Cloudflare (DNS only) : une boutique Shopify correctement branchée n'est pas concernée [HYPOTHÈSE]. Sur WooCommerce ou
un site statique : chercher `# BEGIN Cloudflare Managed content` dans le `/robots.txt` en ligne et vérifier les
réglages des robots IA dans le tableau de bord Cloudflare.

## 3. robots.txt sur Shopify

Le robots.txt par défaut de Shopify ne bloque aucun robot IA [CONSENSUS]. **Piège (RFC 9309)** : un robot nommé dans
un groupe n'obéit qu'à ce groupe. Ajouter `User-agent: OAI-SearchBot` + `Allow: /` lui ferait ignorer les
interdictions par défaut (panier, checkout, tris) [FAIT]. Ne jamais « autoriser » un robot par un groupe dédié.

- **Option A (par défaut)** : ne créer aucun modèle ; rester visible partout.
- **Option B** : refuser l'entraînement sans toucher aux recherches IA — créer `templates/robots.txt.liquid` :

```liquid
{% for group in robots.default_groups %}
  {{- group.user_agent }}
  {%- for rule in group.rules -%}
    {{ rule }}
  {%- endfor -%}
  {%- if group.sitemap != blank -%}
    {{ group.sitemap }}
  {%- endif -%}
{% endfor %}

User-agent: GPTBot
User-agent: ClaudeBot
User-agent: Applebot-Extended
User-agent: CCBot
Disallow: /
```

Google-Extended (sert aussi à l'ancrage dans Gemini) et Meta-ExternalAgent (sert aussi à indexer les produits) sont
volontairement absents. Après publication (🟠), relire `/robots.txt` en ligne et relancer l'audit.

## 4. Ce que disent les études

| Constat | Niveau |
|---|---|
| Princeton (KDD 2024) : moteur **simulé**, aucune requête e-commerce ; visibilité moyenne 19,4 de base, 27,3 avec citations d'experts, 25,3 avec statistiques, 24,5 avec sources, 17,7 avec bourrage de mots-clés (pire que la base) | [FAIT pour l'étude] |
| C-SEO Bench (NeurIPS 2025, inclut la recommandation de produits) : la plupart des réécritures « pour LLM » sont inefficaces, voire nuisibles ; la position dans les résultats récupérés domine ; les gains fondent quand tout le monde applique la même méthode | [FAIT] |
| Wan et al. (2024) : les modèles retiennent surtout la pertinence et ignorent largement le style | [FAIT] |
| Chen et al. (09/2025) : les moteurs IA privilégient les médias tiers plutôt que le contenu de la marque | [FAIT] |
| Un score « GEO » composite ne prédit pas la citation (étude préenregistrée, 341 pages, Perplexity, 10/2026) | [FAIT pour l'étude] |

Ce qui ressort : **être bien classé dans chaque index, être cité par des tiers, publier des faits vérifiables**. Les
leviers de Princeton (statistiques, citations) ne valent qu'une fois la page récupérée [HYPOTHÈSE]. Ce qui ne sert à
rien : bourrage, scores GEO composites, llms.txt, découpage du contenu « pour l'IA ».

Grille de citabilité d'un passage [HYPOTHÈSE de travail] : il se comprend seul ; il nomme explicitement la marque, le
produit ou l'entité ; il contient une donnée vérifiable (mesure, prix, délai) avec sa source ou sa méthode ; il
répond à une question réellement posée ; il est daté quand la donnée peut changer.

## 5. Commerce agentique (pour comprendre, rien à coder)

| Protocole | Objet | État | Pour une petite boutique |
|---|---|---|---|
| ACP (OpenAI + Stripe) | Flux produit vers l'agent, puis paiement agent–marchand | Bêta ; dernière version stable 2026-04-17 | Rien : passe par la plateforme et le prestataire de paiement |
| UCP (Google + Shopify, Stripe au conseil de gouvernance) | Langage commun agent–marchand : catalogue, panier, paiement, commande | Versions 2026-01-11 à 2026-08-25 ; feuille de route sans l'Europe | Rien : Shopify l'implémente |
| AP2 (Google) | Mandats signés pour les paiements faits par un agent | v0.2 (28/04/2026), sans déploiement public cité | Rien |

Achat par agent ouvert au public (Universal Cart, Copilot Checkout, achat intégré de Perplexity, Agentic Storefronts) :
**États-Unis** au 18/10/2026. Être prêt = appliquer la section 1 ; elle suffit le jour où la France ouvrira.

## 6. Mesure (mensuelle, 0 €)

1. **Search Console › IA générative** : impressions en France, par page (les clics venant de l'IA restent confondus
   avec l'organique Google [CONSENSUS]).
2. **Bing Webmaster Tools › AI Performance** : citations et requêtes d'ancrage.
3. **Ventes par site référent** (rapports de la plateforme) : chatgpt.com, perplexity.ai, copilot, gemini, claude.ai.
4. **Panel** : 20 requêtes (catégorie, comparaison, marque) × 4 assistants × 3 passages, en session déconnectée ;
   noter si la marque est citée, l'URL, les concurrents cités, l'exactitude du prix et du délai. Les réponses varient
   d'une fois à l'autre : comparer des tendances, jamais un test isolé ; ne conclure que sur un écart d'au moins
   15 points maintenu deux mois [HYPOTHÈSE].
5. **Requêtes de la Search Console** classées selon l'Aperçu IA : vous cite / ne vous cite pas / cite un concurrent /
   absent ; traiter d'abord les deuxième et troisième cas.

Résultats consignés dans le cerveau : `brain obs` pour le relevé, `brain add -t learning` pour une leçon durable.

## 7. À éviter

Mentions inauthentiques, faux avis, texte caché destiné aux IA, contenu différent servi aux robots (cloaking),
instructions cachées pour manipuler un assistant (injection), bourrage de mots-clés, « top 10 » à la chaîne,
découpage artificiel du contenu « pour les IA », achat de publicité ChatGPT présenté comme du GEO.
