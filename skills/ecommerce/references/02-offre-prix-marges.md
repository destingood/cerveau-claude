# Module 02 — Offre, produit, prix, marges

Sommaire : 1. Valider un produit · 2. Économie unitaire · 3. Construire l'offre · 4. Tester un prix à 0 € ·
5. Positionnement

## 1. Valider un produit pour la croissance organique

Note chaque critère de 0 à 2. En dessous de 9/16, ne lance pas sans corriger (recherche et tests : module 15).

| Critère | Pourquoi c'est décisif sans pub |
|---|---|
| Démontrable en vidéo dès la première seconde (effet visible, avant/après) | La portée organique dépend de la rétention |
| Problème ou désir fort, fréquent, facile à formuler | Le message doit se comprendre en 3 secondes |
| Marge de contribution suffisante | Sans pub, le temps passé doit être payé par la marge |
| Logistique simple (poids, volume, fragilité, délai) | Les délais longs tuent la confiance ; un stock UE est un argument |
| Conformité maîtrisable | Électrique, jouet, cosmétique, alimentaire : obligations lourdes (module 10) |
| Différenciation possible (bundle, contenu, service, garantie) | Évite la guerre des prix sur les mêmes produits fournisseurs |
| Saturation acceptable | Un produit vu partout à prix cassé convertit mal |
| Potentiel de réachat ou d'accessoires | Augmente la valeur d'un client acquis à la sueur |

## 2. Économie unitaire

**Marge de contribution par commande** = CA HT de la commande (prix + port facturé au client)
− coût produit − livraison payée au transporteur ou au fournisseur − emballage
− frais de paiement (part fixe + %) − commission du canal
− provision pour retours (ventes remboursées) − prélèvements sociaux sur le CA **net des remboursements**.

Calcul sans erreur : `python scripts/unit_economics.py --aide` (options `--port-client`, `--remuneration-mois` pour
savoir combien de ventes par mois paient les coûts fixes et une rémunération, `--heures` pour la marge par heure).

**Micro-entreprise, vente de marchandises — valeurs au 18/10/2026** (à revérifier chaque janvier sur
autoentrepreneur.urssaf.fr) :

| Prélèvement sur le CA encaissé | Taux | Source |
|---|---|---|
| Cotisations sociales (vente) | 12,3 % | CSS, art. D613-4 (décret 2025-943) [FAIT] |
| Contribution à la formation professionnelle (vente) | 0,1 % | C. trav., art. L6331-48 [FAIT] |
| Taxe pour frais de chambre (CCI, vente) | 0,015 % | Simulateur URSSAF [FAIT, source secondaire officielle] |
| **Total à passer dans `--cotisations-pct`** | **12,415 %** (13,415 % avec le versement libératoire de 1 %) | Calcul |

Services : cotisations 21,2 % (BIC) ou 25,6 % (BNC), plus formation et chambre selon l'activité ; ACRE (publics
éligibles seulement depuis 2026) : 75 % du taux normal pour une création depuis le 01/07/2026 [FAIT — CSS, L131-6-4,
D131-6-1, D131-6-3]. Détail et échéances : module 09.

**Assiette** : le CA brut encaissé, **frais de port facturés au client compris** ; les commissions des plateformes ne
se déduisent pas ; un remboursement diminue le CA de la période [FAIT — URSSAF].

**TVA** : franchise en base jusqu'à 85 000 € de CA (seuil majoré 93 500 €) pour la vente, 37 500 € (41 250 €) pour les
services [FAIT — impots.gouv.fr, BOFiP 2026 ; le seuil unique de 25 000 € n'est jamais entré en vigueur].
**Le mur de la TVA** : à prix TTC constant, passer à 20 % de TVA fait perdre 16,7 % du CA HT. Dès que le CA approche
85 000 €, simule `--tva-pct 20` et prépare les prix. Prix HT = prix TTC ÷ (1 + taux de TVA) ; en franchise, HT = TTC.

**Mention de franchise sur les factures** : « TVA non applicable, art. 293 B du CGI » reste admise jusqu'au
30/06/2028 ; à partir du 01/01/2027, la référence devient « TVA non applicable, article L. 233-3 du CIBS »
[FAIT — ordonnances 2025-1247 et 2026-671, BOFiP du 07/10/2026].

**Marketplaces à partir de 2027** : les plateformes de mise en relation (Etsy, Vinted, Amazon…) prélèveront
cotisations et impôt à la source et verseront des montants nets (CSS, art. L613-6-1) [FAIT ; date de démarrage à
confirmer par arrêté] → prévoir le décalage de trésorerie.

**Prix plancher** : le prix TTC qui garantit la marge visée après tous les frais (`--marge-cible`). N'écris jamais
de seuil fiscal ni de taux de cotisation de mémoire : reprends ce tableau en le datant, ou vérifie en direct.

## 3. Construire l'offre

**Équation de valeur** (Alex Hormozi, *$100M Offers*, reformulée) : la valeur perçue monte avec le résultat désiré et
la probabilité perçue de l'obtenir ; elle baisse avec le délai et l'effort. Note les 4 leviers de 1 à 10 et corrige
le plus faible, un élément à la fois.

**L'offre en 6 éléments** : produit cœur · bonus (guide, accessoire, service) · garantie commerciale · raison réelle
d'agir maintenant · nom de l'offre · prix et modalités (paiement, livraison, retours).

| Levier | Ce qui marche | Garde-fou |
|---|---|---|
| Panier moyen | Bundles « prêts à l'emploi », accessoire compatible, seuil de livraison offerte fixé au-dessus du panier moyen actuel, barre « encore X € pour la livraison offerte » | Seuil calculé sur la marge |
| Garantie commerciale | La preuve d'abord, la garantie ensuite ; 2 conditions au plus ; affichée près du bouton ; test : que se passe-t-il si 10 % des acheteurs l'invoquent ? | Facultative ; ne remplace jamais les garanties légales, présentées à part ; ne pas vendre la garantie légale ni le délai de rétractation comme un atout propre (C. conso., art. L121-4) [À VÉRIFIER : alinéa] |
| Rareté et urgence | Seulement réelles : stock réel, série sans réassort, saison, bonus qui disparaît vraiment, hausse de prix annoncée puis appliquée ; contrainte vérifiable, appliquée, placée près du bouton | Fausse urgence réputée trompeuse (art. L121-4, 7°) ; inutile pour un achat d'impulsion (environ 5 à 30 €) et contre-productive pour un produit premium [CONSENSUS] |
| Prix barré | Uniquement avec un prix de référence = prix le plus bas pratiqué pendant les 30 jours précédant la réduction (art. L112-1-1) ; un produit jamais vendu au prix barré ne peut pas afficher de réduction ; une comparaison avec un « prix conseillé » se présente comme une comparaison (fiche DGCCRF) | Black Friday et promotions : même règle ; « soldes » réservé aux périodes légales et revente à perte interdite (C. com., art. L310-3 et L442-5) [À VÉRIFIER] |
| Ancrage honnête | « Pas le moins cher, mais… » ; coût par utilisation (« 0,30 € par jour d'usage ») ; comparaison avec l'alternative (réparer, racheter, faire soi-même) | Jamais un prix de référence fictif |
| Prix psychologiques (9,90 €) | À tester | Effets discutés [HYPOTHÈSE] |

**Garantie légale de conformité** [FAIT] : le vendeur répond des défauts apparus dans les 2 ans suivant la délivrance
(C. conso., art. L217-3) ; défauts présumés exister à la délivrance pendant 24 mois (art. L217-7), 12 mois pour un
bien d'occasion ; un bien réparé gagne 6 mois de garantie (art. L217-13).

**À bannir** : « révolutionnaire », « secret », « offre limitée » sans limite réelle, « d'une valeur de X € » sans
élément de comparaison, « garanti 100 % » sans conditions, superlatifs invérifiables (« le meilleur », « n° 1 » :
art. L121-2). **Remise d'acquisition systématique** : déconseillée, elle apprend aux clients à attendre la promo
[CONSENSUS].

**Échelle de valeur** (Russell Brunson, adaptée) : aimant gratuit (guide, quiz) → produit d'entrée → produit cœur →
bundle, accessoires ou abonnement.

## 4. Tester un prix à 0 €

- **Van Westendorp** (4 questions dans un formulaire gratuit) : à quel prix ce serait trop cher ? trop bon marché pour
  être de qualité ? cher mais envisageable ? une bonne affaire ? Mesure une perception, pas une demande ; viser 100 à
  300 réponses de la cible.
- **Gabor-Granger** : « l'achèteriez-vous à X € ? », X variant d'un répondant à l'autre.
- **Le vrai test** : une précommande datée ou une page produit à deux prix successifs, mesurée en ventes réelles
  (module 15).

## 5. Positionnement

Phrase type : « Pour [cible] qui [problème], [marque] propose [produit] qui [bénéfice principal], contrairement à
[alternative], parce que [preuve]. »

- **Usages** (« jobs to be done ») : 2 ou 3, fonctionnels, émotionnels et sociaux.
- **Concurrence en 3 cercles** : concurrents directs ; autre solution au même problème ; faire soi-même ou ne rien
  faire.
- **Forces en jeu** : ce qui pousse à quitter la solution actuelle, ce qui attire vers la tienne, l'habitude,
  l'anxiété du changement → la fiche produit répond aux deux dernières.
- **Objections** : les 3 principales avec leur réponse ; et l'anti-cible (à qui le produit ne convient pas).
- **Voix du client** : mots exacts relevés dans les avis et commentaires (module 15), réutilisés tels quels dans les
  titres, la FAQ et les accroches vidéo.

Range le positionnement dans la fiche contexte du cerveau (`assets/modele-contexte-boutique.md`).
