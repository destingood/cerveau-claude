# Module 09 — Pilotage, KPI, gestion

Sommaire : 1. Tableau de bord · 2. Règles de décision · 3. Priorisation · 4. Expériences et tests · 5. Revue
hebdomadaire · 6. Trésorerie · 7. Stocks · 8. Fournisseurs · 9. Procédures · 10. Valeur client · 11. Micro-entreprise ·
12. TVA et facturation · 13. Échéances · 14. Outils gratuits

## 1. Tableau de bord hebdomadaire

| Bloc | Indicateur | Source |
|---|---|---|
| Trafic | Sessions par source (UTM) | Plateforme, analytics |
| Conversion | Taux d'ajout au panier ; checkout atteint ; taux de conversion | Rapport de conversion de la plateforme |
| Valeur | Panier moyen ; CA ; marge de contribution totale | Plateforme + `scripts/unit_economics.py` |
| Qualité | Taux de retour ; délai réel de livraison ; note moyenne des avis | Commandes, transporteur, app d'avis |
| Audience | E-mails capturés ; abonnés par plateforme | App e-mail, plateformes |
| Contenu | Vidéos publiées ; rétention moyenne ; envois pour 1 000 vues | Statistiques des plateformes |
| SEO / GEO | Impressions, clics, position ; impressions dans les Aperçus IA ; ventes venant des assistants IA | Search Console, Bing Webmaster Tools, sites référents |
| Effort | Heures par canal → marge par heure | Journal, cerveau |

L'indicateur décisif sans pub : **marge de contribution par heure investie**, par canal.

Règles de lecture : semaines complètes (lundi-dimanche, fuseau de la boutique) ; chaque pourcentage accompagné de sa
valeur absolue ; une valeur absente n'est pas un zéro ; CA et nombre de commandes recoupés avec les commandes réelles
(un écart reste affiché « inexpliqué ») ; pas de verdict sur un petit volume.

## 2. Règles de décision [HEURISTIQUES à calibrer sur la base de mesure]

| Objet | Arrêter | Itérer | Amplifier |
|---|---|---|---|
| Produit | Trafic qualifié suffisant sans ajout au panier après 2 versions de la fiche | Ajouts au panier sans commande → checkout, frais, confiance | Ventes régulières et marge positive → plus de contenus et de partenaires |
| Angle vidéo | 5 vidéos sous la médiane de rétention du compte | Bonne rétention, peu de clics → appel à l'action, page d'arrivée | Envois élevés → série (1 idée nouvelle = 1 vidéo) |
| Canal | Aucune vente après 4 semaines d'effort régulier | Ventes isolées → ajuster cible et message | Meilleure marge par heure → priorité |

Si la boutique a déjà ses propres règles (outil maison, tableur), aligne-les plutôt que d'ajouter une deuxième logique.
Chaque décision → `brain add -t decision …` avec sa date de revue.

## 3. Priorisation

- **ICE** pour le tri rapide (Sean Ellis) : Impact, Confiance, Facilité de 1 à 10 ; **score = moyenne des trois** ;
  départage par le délai avant le premier euro, puis par les heures nécessaires.
- **RICE** pour une grosse décision : (Portée × Impact × Confiance) ÷ Effort ; impact 3 / 2 / 1 / 0,5 / 0,25 ;
  confiance 100 / 80 / 50 % ; effort en heures.
- **PIE** pour choisir la page à améliorer : Potentiel, Importance (trafic, valeur), Facilité.

## 4. Expériences et tests

Journal d'une ligne par test : date · hypothèse · changement · métrique · durée · résultat chiffré · décision ·
niveau de confiance (dans le cerveau : `brain obs` pendant le test, `brain add -t learning` pour la leçon).

**Taille d'échantillon** (sessions par version ; test bilatéral, α = 5 %, puissance 80 %) [FAIT — recalculé le
18/10/2026] :

| Taux de base | Gain relatif à détecter : +20 % | +50 % | +100 % |
|---|---|---|---|
| 1 % (conversion) | 42 693 | 7 750 | 2 319 |
| 3 % (conversion) | 13 914 | 2 518 | 749 |
| 8 % (ajout au panier) | 4 921 | 882 | 258 |

À 3 % de conversion et 100 sessions par jour, détecter +20 % prend environ 278 jours : sur une petite boutique, un test
A/B ne conclut presque jamais. Fais des changements séquentiels mesurés sur des semaines complètes (au moins une, au
plus huit, sans arrêt anticipé) et qualifie le résultat d'indicatif ; appuie-toi sur le qualitatif (module 03).

## 5. Revue hebdomadaire (60 minutes)

Ordre : chiffres (section 1) → trésorerie → stock → expériences en cours → 3 priorités de la semaine → échéances.
Sortie : 3 à-faire datés dans le cerveau (`brain add -t todo … --due …`) et une observation (`brain obs`).

## 6. Trésorerie

- **Plan sur 13 semaines** : solde de départ ; encaissements aux dates réelles de versement (prestataire de paiement,
  marketplaces) ; décaissements (fournisseurs, transport, abonnements, URSSAF à l'échéance, remboursements) ; solde de
  fin. Alerte si le solde passe sous 4 semaines de dépenses plus la prochaine échéance URSSAF.
- **Provision** : à chaque versement reçu, mettre de côté le taux de prélèvement sur le CA (13,415 % en vente avec
  versement libératoire) sur un compte séparé (méthode *Profit First*, Michalowicz) [CONSENSUS].
- Dropshipping : le fournisseur est payé à la commande, le versement du prestataire arrive plus tard → prévoir le
  décalage. Marketplaces en 2027 : versements nets du précompte (module 02).

## 7. Stocks

- **Point de commande** = ventes moyennes par jour × délai du fournisseur (jours) + stock de sécurité.
- **Stock de sécurité** = z × écart-type des ventes journalières × √délai (z = 1,65 pour éviter la rupture sur 95 %
  des cycles) ; version simple : (ventes max par jour × délai max) − (ventes moyennes par jour × délai moyen).
- **Classement ABC** chaque mois (A = 80 % du CA) : surveiller les A de près.
- Dropshipping UE : dépublier un produit dès que le stock du fournisseur passe sous un seuil (contrôle hebdomadaire).

## 8. Fournisseurs

- Commande test avant de référencer un produit (qualité, délai réel, emballage, documents de conformité).
- Note mensuelle sur 5 : défauts, délais, coût rendu, réactivité, documents (sécurité des produits, CE).
- Deuxième source pour chaque produit phare ; classement des achats par risque et enjeu (matrice de Kraljic).
- Fiche par fournisseur dans le cerveau (`brain add -t entity … --tags fournisseur,entreprise --commun non`).

## 9. Procédures (systématiser sans budget)

Principe (Michael Gerber, *The E-Myth Revisited*) : toute tâche répétée devient une procédure ; toute procédure
stable devient une automatisation (Shopify Flow, app gratuite sur les plans Basic et plus — l'action « requête HTTP »
demande Grow ou plus [CONSENSUS, octobre 2026] ; scripts).

Structure d'une procédure : déclencheur · résultat attendu · étapes · contrôle · durée · responsable ; check-list de
5 à 9 points. En priorité : traitement d'une commande, rétractation, remboursement, mise en ligne d'un produit,
déclaration URSSAF.

## 10. Valeur client

- **Coût d'acquisition organique** = heures passées sur le canal ÷ nouveaux clients venus de ce canal.
- **Valeur client** = marge moyenne par commande × nombre de commandes par client sur 12 mois, mesurée par cohorte
  (clients arrivés le même mois).
- Le ratio « valeur client / coût d'acquisition ≥ 3 » vient des abonnements logiciels : ne pas l'appliquer tel quel
  à une boutique.

## 11. Micro-entreprise — valeurs au 18/10/2026 (⚠ = change au 01/01/2027)

| Sujet | Valeur | Source |
|---|---|---|
| Plafonds de CA | Vente 203 100 € ; services 83 600 € ; activité mixte : 203 100 € au total dont 83 600 € de services au plus ; prorata la 1re année ; sortie du régime après 2 années consécutives de dépassement | URSSAF, impots.gouv.fr [FAIT] |
| Cotisations (depuis le 01/01/2026) | Vente 12,3 % ; services BIC 21,2 % ; BNC 25,6 % ; BNC Cipav 23,2 % | CSS, art. D613-4 [FAIT] |
| Formation professionnelle | 0,1 % (vente), 0,3 % (artisan), 0,2 % (autres) | C. trav., art. L6331-48 [FAIT] |
| Versement libératoire de l'impôt | 1 % (vente), 1,7 % (services BIC), 2,2 % (BNC) ; option avant le 30/09 pour l'année suivante ; condition de revenu fiscal ⚠ | Simulateur URSSAF [FAIT] |
| ACRE | Publics éligibles seulement (demandeurs d'emploi, RSA, 18-25 ans, QPV, ZFRR…) ; demande sous 60 jours ; 12 mois ; 75 % du taux normal pour une création depuis le 01/07/2026 | CSS, L131-6-4, D131-6-1, D131-6-3 [FAIT] |
| Déclarations | Mensuelle (dernier jour du mois suivant) ou trimestrielle (30/04, 31/07, 31/10, 31/01) ; déclarer « néant » si CA nul ; pénalité par déclaration manquante | CSS, L613-8, R613-8 à R613-10 [FAIT] |
| Compte bancaire dédié | Obligatoire si le CA dépasse 10 000 € pendant 2 années consécutives | CSS, L613-10 [FAIT] |
| Précompte par les marketplaces ⚠ | Cotisations et impôt prélevés par les plateformes de mise en relation sur le CA réalisé dès 2027 (date à confirmer par arrêté) | CSS, L613-6-1 [FAIT] |

Vérification en un clic : simulateur officiel de l'URSSAF (son code est public : dépôt betagouv/mon-entreprise).

## 12. TVA et facturation

| Sujet | Règle | Source |
|---|---|---|
| Franchise en base | Vente 85 000 € (seuil majoré 93 500 €) ; services 37 500 € (41 250 €) ; dépassement l'année précédente → TVA due dès le 1er janvier ; seuil majoré dépassé en cours d'année → TVA due dès le dépassement | impots.gouv.fr, BOFiP [FAIT] |
| Mention sur les factures ⚠ | « TVA non applicable, art. 293 B du CGI » admise jusqu'au 30/06/2028 ; dès le 01/01/2027 : « TVA non applicable, article L. 233-3 du CIBS » | Ordonnances 2025-1247 et 2026-671 [FAIT] |
| Régime simplifié de TVA ⚠ | Supprimé au 01/01/2027 : déclaration trimestrielle (CA ≤ 1 M€) ou mensuelle | impots.gouv.fr [FAIT] |
| Facture électronique | **Réception** via une plateforme agréée obligatoire pour toutes les entreprises **depuis le 01/09/2026** (franchise comprise) ; **émission** pour les PME et micro-entreprises au 01/09/2027 | economie.gouv.fr, impots.gouv.fr [FAIT] |
| Transmission des ventes aux particuliers (e-reporting) | À partir du 01/09/2027 : données cumulées par jour, sans donnée personnelle ; en franchise, tous les 2 mois | impots.gouv.fr [FAIT] |
| Nouvelles mentions de facture | SIREN du client ; nature de l'opération (biens, services, les deux) ; option pour la TVA sur les débits ; adresse de livraison si elle diffère | economie.gouv.fr [FAIT ; dates d'application à confirmer] |
| DAC7 | Les plateformes déclarent leurs vendeurs dès 30 ventes ou plus de 2 000 € par an | CGI, art. 1649 ter A et suivants [FAIT] |

Choisir une plateforme de réception des factures électroniques est une décision de l'utilisateur (🔴 : comptes et
conditions) ; le cerveau prépare la comparaison.

## 13. Échéances à mettre dans le cerveau (`--due`)

Déclarations URSSAF ; option pour le versement libératoire avant le 30/09 ; ACRE sous 60 jours après la création ;
DAC7 en janvier ; 01/01/2027 : mention CIBS sur les factures, précompte des marketplaces, fin du régime simplifié de
TVA ; 01/09/2027 : émission des factures électroniques et e-reporting.

## 14. Outils gratuits

Tableur (Google Sheets, LibreOffice Calc) pour le tableau de bord, la trésorerie et les stocks ; simulateur de
l'URSSAF ; Shopify Flow ; Dolibarr (logiciel de gestion libre, stock et factures, à héberger soi-même : option, pas
par défaut) ; le cerveau pour le journal, les décisions et les échéances.
