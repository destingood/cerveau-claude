# Module 15 — Trouver et valider un produit, une niche, étudier la concurrence

Objectif : choisir ce qui peut se vendre **sans publicité**, et le prouver avant d'y passer des semaines. Tout se fait
dans un navigateur, gratuitement. Les outils changent vite : vérifie leur disponibilité en France au moment de
l'usage [À VÉRIFIER] et note ce qui marche dans le cerveau (`brain add -t learning …`).

Sommaire : 1. Les critères · 2. Sources gratuites · 3. Étudier la concurrence · 4. Voix du client · 5. Valider avant
d'investir · 6. Fournisseurs · 7. Décision

## 1. Ce qui se vend sans pub

Un produit gagnant en organique coche presque tout le module 02 (grille sur 16) ; les quatre filtres qui éliminent le
plus vite :
1. **Démontrable en vidéo dès la première seconde** (effet visible, avant/après) — la portée organique dépend de la
   rétention (module 05).
2. **Problème ou désir fort, formulé par les gens eux-mêmes** (recherches, questions, plaintes).
3. **Marge de contribution qui paie le temps** (`scripts/unit_economics.py`) : sans pub, chaque vente coûte des heures.
4. **Conformité maîtrisable** : électrique, jouet, cosmétique, alimentaire, puériculture → obligations lourdes
   (module 10) ; à éviter pour un premier produit.

## 2. Sources gratuites de demande

| Source | Ce qu'elle montre | Usage |
|---|---|---|
| Google Trends | Intérêt dans le temps, par région, requêtes associées en hausse | Saisonnalité, tendance de fond contre effet de mode ; comparer 3 à 5 termes |
| Autocomplétion (Google, YouTube, TikTok, Amazon, Etsy, Pinterest) | Ce que les gens tapent vraiment | Vocabulaire, problèmes, usages ; mots pour titres et vidéos |
| « Autres questions posées » (Google) | Questions réelles | FAQ, angles de contenu, objections |
| Amazon.fr : Meilleures ventes, Envolées des ventes, Nouveautés | Ce qui se vend maintenant, par catégorie | Repérer une catégorie, pas copier un produit ; lire les avis 1 à 3 étoiles |
| Etsy (recherche, best-sellers d'une boutique) | Demande pour le fait main, le personnalisé, le cadeau | Niches de personnalisation |
| Pinterest (recherche, Pinterest Trends) | Intentions visuelles et saisonnières, souvent en avance | Déco, mode, mariage, cadeaux, DIY [FAIT* : Pinterest Trends a des données France, sans la dernière version de l'outil] |
| TikTok (recherche ; Creative Center, renommé « TikTok One Creative Suite » : Top Ads, Keyword Insights, Top Products, Trends) | Ce qui capte l'attention, formats et accroches | Angles vidéo, produits qui « se montrent » [À VÉRIFIER : France dans les filtres de région] |
| Reddit, forums, groupes Facebook de la niche | Douleurs exprimées sans filtre | Voix du client (section 4) |
| Search Console (si un site existe) | Requêtes qui donnent déjà des impressions | Produits ou pages à créer en priorité |

Lecture : une demande **stable ou montante** avec un **problème clair** vaut mieux qu'un pic viral ; un produit vu
partout à prix cassé convertit mal (saturation).

## 3. Étudier la concurrence (transparence publicitaire, gratuite)

| Outil | Ce qu'il montre | Ce qu'on en tire |
|---|---|---|
| Bibliothèque publicitaire de Meta (Ad Library) | Publicités actives sur Facebook et Instagram ; pour toute publicité diffusée dans l'UE : visible pendant la diffusion puis 1 an après la dernière impression, avec portée estimée, ciblage (âge, sexe, lieux), bénéficiaire et payeur (règlement (UE) 2022/2065 « DSA », art. 39) [FAIT* — Meta] | Une pub qui tourne depuis des semaines est probablement rentable : l'angle, l'accroche et l'offre sont validés par l'argent d'un autre — à transposer en organique, jamais à copier |
| Bibliothèque publicitaire de TikTok (UE) | Publicités diffusées dans l'UE (même obligation DSA) | Formats et accroches qui retiennent |
| Centre de transparence des annonces Google | Annonces d'un annonceur (Search, Shopping, YouTube) | Positionnement prix et promesses des concurrents |
| Le site du concurrent | Offre, prix, bundles, livraison, garanties, avis, pages qui se classent (`site:`) | Trous à exploiter : délai, preuve, service, contenu |
| `python scripts/audit_site.py <url du concurrent>` | Sa base technique (données produit, robots IA) | Où il est faible en SEO/GEO |
| Ses réseaux | Vidéos les plus vues (tri par popularité), commentaires | Angles qui marchent, questions sans réponse |

Règles : observer, pas copier (textes, photos et vidéos sont protégés par le droit d'auteur) ; pas de dénigrement
d'un concurrent nommé (module 03) ; pas de collecte de données personnelles de ses clients.

## 4. Voix du client (la mine d'or gratuite)

1. Relève 30 à 50 avis 1 à 3 étoiles et 5 étoiles de 3 concurrents (marketplaces, site, Google).
2. Classe les mots exacts : douleurs, objections, résultats attendus, usages surprenants, mots du vocabulaire.
3. Ajoute les questions des forums, des commentaires TikTok et des « Autres questions posées ».
4. Réutilise ces mots tels quels : titres, bénéfices de la fiche produit, FAQ, accroches vidéo, e-mails.
5. Les plaintes récurrentes sur les concurrents (délai, fragilité, notice) deviennent ta différence — si tu peux la
   tenir.

Range la synthèse dans le cerveau (`brain add -t analysis` en mode wiki, sinon `-t learning`) : elle resservira.

## 5. Valider avant d'investir

| Test | Comment | Signal | Piège |
|---|---|---|---|
| Entretiens (méthode « The Mom Test », Rob Fitzpatrick) | 5 à 10 personnes de la cible : parler de leur vie et de leur dernier achat sur le problème, pas de ton idée | Elles ont déjà cherché, dépensé, bricolé une solution | Les compliments ne valent rien ; seul compte le comportement passé |
| Test de contenu | 3 à 5 vidéos de démonstration ou épingles avant le stock | Rétention, partages, enregistrements, commentaires « où l'acheter ? » | Intention ≠ achat [HYPOTHÈSE] |
| Liste d'attente | Page produit + inscription, sans paiement | Taux d'inscription des visiteurs qualifiés | Ne jamais encaisser sans date de livraison annoncée |
| Précommande | Paiement avec date ou délai de livraison annoncé (à défaut, livraison au plus tard 30 jours après la commande : C. conso., art. L216-1) | Ventes réelles avant le stock | Tenir la date ; sinon rembourser |
| Financement participatif (précommande) | Campagne sur une plateforme française, frais au succès [À VÉRIFIER : barème du jour] | Contributeurs = clients, communauté, presse | Production et logistique à prévoir avant |
| Test marketplace | 1 à 3 annonces (module 16) | Messages, favoris, ventes | Statut professionnel obligatoire si l'activité est professionnelle |

Seuil de décision fixé **avant** le test (par exemple : X inscriptions pour 100 visiteurs qualifiés, ou Y ventes en
14 jours) et consigné dans le cerveau (`brain add -t decision …`).

## 6. Fournisseurs

- Préférer un stock dans l'UE : délais courts, retours simples, argument de vente, conformité plus facile à prouver.
- Grossistes et places de marché B2B européennes pour commerces indépendants [À VÉRIFIER : conditions et minimums de
  commande du jour] ; fabricants et artisans français (salons, annuaires professionnels) ; dropshipping seulement avec
  délais réels annoncés et conformité vérifiée (règlement (UE) 2023/988 : personne responsable dans l'UE).
- Avant toute commande : échantillon, photos et vidéos réelles, documentation de conformité (marquage CE, fiches de
  sécurité selon la catégorie), délais écrits, conditions de retour fournisseur.
- Fiche fournisseur dans le cerveau (`brain add -t entity -T "<fournisseur>" --tags fournisseur,entreprise …
  --commun non`) : prix, minimums, délais, qualité observée.

## 7. Décision

| Score (module 02, grille sur 16) | Signaux de validation | Décision |
|---|---|---|
| ≥ 12 | Au moins un test positif au-dessus du seuil fixé | Lancer (module 00) |
| 9 à 11 | Signaux partiels | Corriger l'offre (bundle, différence, prix) et retester une fois |
| < 9 | Pas de signal | Abandonner ou changer d'angle : c'est une économie, pas un échec |
