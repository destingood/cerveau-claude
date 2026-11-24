---
name: factures-recus
description: "Quand des factures, reçus ou notes de frais sont à trier, renommer ou classer, ou à mettre en tableau pour le comptable. Pas pour créer ou envoyer une facture."
metadata:
  triggers: >-
    « range mes factures » « classe mes factures » « trie mes factures » « renomme mes factures » « trie mes reçus »
    « classe mes reçus » « mes notes de frais » « factures en vrac » « factures pour le comptable » « tableau pour mon
    comptable » « dossier de factures » « factures électroniques reçues » « pdf factur-x » « xml factur-x » Ne pas
    utiliser pour « crée une facture » « fais une facture » « envoie la facture » « facture client ».
---

# Factures et reçus : renommés, classés, prêts pour le comptable

Écrite pour le cerveau (idées reprises de l'invoice-organizer de ComposioHQ, sans son texte, qui n'a pas de licence).
Outils : `scripts/factures.py` (inventaire, contrôle, rangement, tableau) et `scripts/facturx.py` (lecture des
factures électroniques), bibliothèque standard, aucun réseau.

## À savoir (sources officielles, lues le 24/11/2026)
- **Factures électroniques** : depuis le 1er septembre 2026, toutes les entreprises, micro-entreprises comprises,
  doivent pouvoir **recevoir** les factures électroniques de leurs fournisseurs, par une plateforme agréée ; l'**envoi**
  devient obligatoire au 1er septembre 2027 pour les PME, TPE et micro-entreprises (economie.gouv.fr, « Facturation
  électronique entre entreprises : coup d'envoi de la réforme », 01/09/2026 ; impots.gouv.fr, fiche 1). Ces factures
  arrivent en Factur-X (PDF avec un XML joint), CII ou UBL : l'outil les lit sans rien deviner.
- **Conservation** : factures reçues et émises, 10 ans à partir de la clôture de l'exercice (entreprendre.service-public.fr,
  F10029). Les originaux ne sont jamais effacés.

## Méthode
1. **Inventaire** : `python scripts/factures.py inventaire <dossier>` → `releve.csv` dans le dossier, une ligne par
   document (PDF, image, XML, e-mail), doublons repérés (même contenu), factures électroniques déjà remplies, date
   reprise du nom du fichier quand elle y est.
2. **Lire chaque document** encore vide (outil Read : il lit les PDF et les images) et remplir le relevé : `type`
   (Facture, Reçu, Avoir, Note de frais), `date` (AAAA-MM-JJ, date de la facture), `fournisseur` (nom court :
   « Colissimo », pas « La Poste SA »), `numero`, `objet` (2 à 5 mots), `categorie`, `ht`, `tva`, `ttc`, `devise`,
   `paiement`. **Un montant illisible reste vide**, avec une `note` ; jamais deviné ni recalculé à partir d'un taux.
   Une catégorie « devinée » se confirme.
3. **Contrôle** : `python scripts/factures.py verifier releve.csv` (date, fournisseur, HT + TVA = TTC, fichier,
   doublons) ; corriger jusqu'à « tout est bon », ou montrer à l'utilisateur ce qui reste illisible.
4. **Rangement** : `python scripts/factures.py ranger releve.csv --vers <dossier rangé>` montre le plan :
   `<année>/<catégorie>/AAAA-MM-JJ Fournisseur - Facture - Objet.pdf`. **Rien ne bouge** avant le « oui » de
   l'utilisateur ; ensuite `--appliquer` **copie** (les originaux restent ; `--deplacer` seulement s'il le demande).
   Jamais d'écrasement ; un journal `journal-rangement.csv` garde chaque copie.
5. **Tableau du comptable** : `python scripts/factures.py comptable releve.csv [--annee 2026]` → `comptable.csv`
   (s'ouvre dans Excel : point-virgule, virgule décimale), trié par date, avoirs en négatif, totaux par catégorie.

Catégories : marchandises, emballage-expedition, logiciels-abonnements, materiel, telephone-internet, deplacements,
formation, banque-frais (commissions Stripe, PayPal, SumUp), honoraires, marketing, impots-taxes, autres. Le
comptable a les siennes : les reprendre s'il les donne.

## Règles
- Données privées : tout reste sur le PC ; rien n'est envoyé ; un souvenir sur les factures se garde privé
  (`brain add … --commun non`), sans montant ni numéro de client.
- Une facture d'achat payée par la boutique et une dépense perso ne se mélangent pas : en cas de doute, demander.
- Ce n'est pas un conseil comptable ni fiscal : la déductibilité, la TVA récupérable et le régime se voient avec le
  comptable.
