# Module 01 — Diagnostic et audit express

Objectif : trouver le **goulot unique** qui limite les ventes, puis les 3 actions qui le débloquent. Un diagnostic
juste évite d'envoyer du trafic vers une page qui ne convertit pas.

Sommaire : 1. Collecte · 2. Audit express en 15 minutes · 3. Équation et arbre du goulot · 4. Score sur 100 ·
5. Restitution · 6. Contrôle de santé hebdomadaire

## 1. Collecte (par ordre de priorité)

1. **Le cerveau** : `brain q "boutique <nom>"` — fiche contexte, chiffres, décisions, tests déjà menés.
2. **Les connecteurs** : rapports Shopify (sessions, conversion, panier moyen), Search Console, Merchant Center.
3. **Le site lui-même**, dans le navigateur (section 2).
4. **L'utilisateur**, pour le reste seulement — 8 questions au maximum :
   1. URL, plateforme, date de lancement.
   2. 1 à 3 produits héros : prix TTC, coût complet par commande (produit + livraison + frais).
   3. 30 derniers jours : sessions, ajouts au panier, checkouts atteints, commandes, CA, panier moyen.
   4. Sources de trafic actuelles.
   5. Comptes sociaux existants (plateforme, abonnés, fréquence de publication).
   6. Délai de livraison réel et origine du stock.
   7. Heures disponibles par semaine ; aisance en vidéo face caméra.
   8. Objectif chiffré et échéance.

Sur Shopify, le rapport « Conversion rate breakdown » (détail du taux de conversion) donne les sessions avec ajout au
panier → ayant atteint le checkout → l'ayant finalisé [FAIT* — libellé français à lire dans l'admin]. Depuis fin
septembre 2026, Shopify exclut par défaut les sessions de robots identifiées ; filtrer quand même le pays de vente avant
de calculer un taux. Ces trois chiffres alimentent `brain boutique kpi` (module 09).

## 2. Audit express en 15 minutes (navigateur, 0 €)

| Minute | Contrôle | Comment | Ce qu'on cherche |
|---|---|---|---|
| 0–2 | Audit technique | `python scripts/audit_site.py <accueil> --conformite --pages 10` puis sur une fiche produit et une collection (`--vitesse` pour les Core Web Vitals) | noindex, titres, données Product/Offer (livraison, retours), robots des moteurs et des IA, sitemap ; pages du sitemap en erreur ou en double ; pages légales et points bloquants du module 10 |
| 2–4 | Vitesse mobile | PageSpeed Insights, onglet mobile (données réelles si disponibles) | LCP ≤ 2,5 s, INP ≤ 200 ms, CLS ≤ 0,1 (seuils web.dev) |
| 4–7 | Premier écran mobile d'une fiche produit | Ouvrir la page en largeur de téléphone | Bénéfice clair, preuve réelle, prix TTC, bouton visible, délai et frais de livraison avant le panier |
| 7–9 | Tunnel | Ajouter au panier → aller jusqu'à la page de paiement (sans payer) | Frais découverts tard, compte obligatoire, champs inutiles, paiements express absents |
| 9–10 | Confiance | Pages mentions légales, CGV, livraison et retours, contact ; avis | Identité claire, retours 14 jours, avis vérifiables |
| 10–12 | Visibilité Google | `site:domaine.fr` ; onglet Shopping avec le nom du produit héros ; si accès : Search Console (pages, requêtes, rapport « IA générative ») | Pages indexées, titres affichés, présence dans les fiches gratuites et dans les Aperçus IA |
| 12–13 | Visibilité IA | Demander à ChatGPT et Perplexity : « où acheter <produit> en France ? », « meilleur <produit> pour <usage> » | La marque est-elle citée ? Qui l'est à sa place ? (référence GEO, module 07) |
| 13–15 | Réseaux et marketplaces | Profils : date du dernier post, vues moyennes ; présence sur les marketplaces de la niche | Canal actif ou abandonné, angle qui marche déjà |

Note chaque constat avec sa preuve (capture, chiffre, URL). Sans navigateur piloté, donne cette grille à l'utilisateur
et demande les captures.

## 3. Équation et arbre du goulot

- CA = Sessions × Taux de conversion × Panier moyen (+ CA de réachat)
- Marge de contribution totale = Commandes × Marge de contribution par commande (`scripts/unit_economics.py`)

| Symptôme | Goulot probable | À vérifier en premier | Modules |
|---|---|---|---|
| Très peu de sessions | Trafic | Indexation, présence vidéo, fiches gratuites, communautés, marketplaces | 00, 04, 05, 06, 16 |
| Sessions correctes, très peu d'ajouts au panier | Offre, fiche produit, prix, confiance | Enregistrements de sessions, profondeur de scroll, prix face aux concurrents, clarté du bénéfice | 02, 03 |
| Ajouts au panier, mais checkouts abandonnés | Coûts ou délais découverts tard, réassurance, paiement | Frais visibles tôt ? Délais clairs ? Paiements express ? Compte obligatoire ? | 03 |
| Ventes, mais marge faible ou négative | Prix, coûts, panier moyen | Calcul de marge, bundles, seuil de livraison offerte | 02, 09 |
| Ventes ponctuelles, pas de réachat | Rétention | Flows e-mail actifs ? Demande d'avis ? | 08 |
| Trafic qui ne correspond pas à la cible | Message ou canal | Sources, requêtes Search Console, commentaires | 04, 05, 06 |
| Visible sur Google mais jamais cité par les IA | Entité, contenu citable, présence chez les tiers | Robots IA, données produit, mentions externes | 07 |

Repères externes, à citer avec leur source : le Baymard Institute publie une moyenne d'abandon de panier calculée sur
50 études (70,22 %) et les raisons déclarées par des acheteurs américains : coûts en plus (39 à 40 %), livraison trop
lente (20 à 21 %), création de compte obligatoire (18 à 19 %) [FAIT* — baymard.com, 2026 ; légers écarts entre ses
pages]. La référence qui compte reste la base de mesure de la boutique.

Ne juge pas un taux sur un volume trop faible. Repère de travail [HYPOTHÈSE] : quelques centaines de sessions sur une
page avant de conclure sur son taux d'ajout au panier ; en dessous, s'appuyer sur l'observation qualitative.

## 4. Score sur 100

| Dimension | Points | Contrôles |
|---|---|---|
| Offre et produit | 15 | Bénéfice clair en une phrase ; produit démontrable ; marge de contribution positive après tous les coûts ; différence nette face aux concurrents |
| Confiance | 15 | Avis réels et vérifiables ; photos et vidéos réelles ; délais et retours clairs ; contact identifiable ; mentions légales et CGV |
| Fiche produit et UX mobile | 15 | Premier écran mobile complet (bénéfice, preuve, prix, bouton) ; vitesse ; livraison annoncée avant le panier |
| Tunnel et checkout | 10 | Frais affichés tôt ; paiements express ; aucun champ inutile ; achat sans compte ; panier qui rassure |
| Acquisition organique | 15 | Comptes vidéo actifs ; présence en communauté ; fiches gratuites Google ; marketplaces pertinentes ; Search Console |
| SEO et GEO | 10 | Pages indexées ; titres et descriptions uniques ; données structurées valides ; robots des moteurs IA autorisés ; marque citée par les assistants |
| Rétention | 10 | Capture d'e-mails avec consentement ; flows (panier abandonné, bienvenue, post-achat) ; demande d'avis |
| Conformité | 10 | Gate du module 10 ; tout point critique manquant bloque la publication, quel que soit le score |

## 5. Restitution

- **Synthèse** : goulot identifié, preuve, gain attendu (qualitatif, ou estimé avec hypothèses explicites).
- **Score** : tableau des 8 dimensions.
- **Top 3** : problème → cause → action → livrable → KPI.
- **Quick wins (moins de 48 h)**.
- **Plan** : décollage 72 h et 14 jours (module 00), en à-faire datés dans le cerveau.
- **Ce qui manque pour conclure** : données absentes et comment les obtenir.
- **Mémoire** : fiche contexte et chiffres créés ou mis à jour dans le cerveau (`--commun non`).

Mode agence : livrable client avec `assets/modele-rapport-audit.md`.

## 6. Contrôle de santé hebdomadaire (10 minutes, connecteur ou navigateur)

- Produits actifs en rupture (hors précommande voulue) → dépublier ou annoncer un délai réel.
- Promotions sans date de fin, expirées, ou dont l'état contredit les dates → corriger (prix de référence :
  art. L112-1-1).
- Liens du menu, des collections et des produits en erreur (attention aux pages « introuvable » servies avec un code
  200).
- Produits sans image, images sans texte alternatif ou avec un texte recopié d'une image à l'autre.
- Refus et avertissements de Merchant Center ; erreurs d'indexation de la Search Console.

En une commande pour tout le catalogue : `python scripts/audit_catalogue.py --url <boutique>` (catalogue public
Shopify, si robots.txt l'autorise) ou `--csv <export de l'admin>` : chaque produit noté (titre, description, images,
textes alternatifs, GTIN, prix barrés, ruptures, allégations à risque), les plus urgents d'abord.

Résultat noté dans le cerveau (`brain boutique audit <boutique>` garde l'historique ; `brain obs` pour le reste),
corrections en lot 🟠 (module 12).
