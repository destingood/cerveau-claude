# Module 11 — Mode agence (boutiques clientes)

Quand la boutique appartient à quelqu'un d'autre (« client », « prospect ») : livrables professionnels en
vouvoiement, autorisation écrite avant toute action, accès collaborateur et jamais de mot de passe, données du client
toujours privées dans le cerveau (`--commun non`).

## 1. Offre de service

Positionnement proposé : « Croissance organique pour boutiques e-commerce : premières ventes et visibilité sans budget
publicitaire. »

| Niveau | Contenu | Rôle |
|---|---|---|
| Mini-audit gratuit | Vidéo de 5 à 8 minutes : 3 problèmes visibles, 1 quick win offert | Prise de contact, preuve de compétence |
| Audit complet | Score sur 100 (module 01), conformité (module 10), plan sur 90 jours | Première vente, faible risque pour le client |
| Sprint 30 jours | Exécution : fiches produits, SEO technique, fiches gratuites Google, flows e-mail, plan vidéo | Résultats visibles |
| Accompagnement mensuel | Contenus, SEO/GEO, conversion, rapport hebdomadaire | Revenu récurrent |

Prix : fixés selon la valeur créée (marge additionnelle attendue), le temps nécessaire et les tarifs observés au
moment de la proposition sur les plateformes freelances [À VÉRIFIER] — aucun tarif de mémoire. Ne promets jamais un
chiffre de ventes : engage-toi sur des livrables, une méthode et des indicateurs suivis.

## 2. Trouver des clients à 0 €, depuis le navigateur

- **La preuve d'abord** : une étude de cas sur ta propre boutique (ou celle d'un premier client à prix d'ami), avec
  chiffres réels avant/après et accord écrit. C'est l'actif commercial le plus fort.
- **Repérer les boutiques qui ont un besoin visible** (recherche Google gratuite) :
  - opérateurs : `"<niche>" "boutique en ligne" -amazon`, `site:myshopify.com <niche>`, `"<niche>" "livraison offerte" <ville>` ;
  - signaux de besoin : fiches copiées du fournisseur, aucun avis, site lent (PageSpeed), absence des fiches gratuites
    Google Shopping, réseaux inactifs, pas de données structurées, robots IA bloqués ;
  - pré-audit en 2 minutes : `python scripts/audit_site.py <url> --complet --rapport pre-audit.md` (conformité,
    10 pages du sitemap, vitesse mobile) et, sur une boutique Shopify, `python scripts/audit_catalogue.py --url <url>` ;
    le premier message cite un constat précis tiré du rapport (modèle : `assets/modeles-textes.md`, section 10).
- **Canaux** : réseau local (CCI, clubs d'entrepreneurs, commerçants de ta ville) ; LinkedIn (contenu utile + messages
  personnalisés écrits à la main ; les outils d'automatisation y sont interdits par les conditions d'utilisation) ;
  partenariats avec des créateurs de sites (ils construisent, tu fais croître) ; experts-comptables ayant des clients
  e-commerce ; plateformes freelances (commission au succès).
- **Contenu de démonstration** : analyses de boutiques publiées avec l'accord du propriétaire, ou anonymisées.
- **Prospection par e-mail** : B2B uniquement, objet lié à l'activité du destinataire, droit d'opposition dès le
  premier message (CNIL ; CPCE, art. L34-5) ; peu de messages, très personnalisés, envoyés un par un. Pas de collecte
  massive de données personnelles sans base légale (RGPD). Téléphone : appeler des professionnels sur leur activité
  reste possible ; le démarchage téléphonique des particuliers est interdit sans consentement depuis le 11/08/2026.
- **Offres à ajouter** : mise en conformité 2026 (bouton de rétractation, allégations environnementales, mentions
  d'influence) ; mise en accessibilité pour les clients qui ne sont pas des microentreprises (obligation depuis le
  28/06/2025, module 10).
- **Vidéo du mini-audit** : enregistrement d'écran avec un outil gratuit (OBS Studio, open source) ; 3 constats montrés
  à l'écran, 1 correction offerte.

**Modèle d'e-mail (mini-audit)**
Objet : 3 points rapides sur [nom de la boutique]
« Bonjour [prénom], en parcourant [boutique], j'ai relevé trois points qui freinent probablement les ventes : [1], [2],
[3]. Je vous ai enregistré une courte vidéo qui les montre : [lien]. Le premier se corrige en moins d'une heure. Si
vous souhaitez en parler, je suis disponible cette semaine ; sinon, répondez simplement « non » et je ne vous
relancerai pas. [Signature complète, coordonnées professionnelles] »

## 3. Livraison de la mission

1. Questionnaire d'onboarding (module 01) ; fiche contexte du client dans le cerveau, privée :
   `brain add -t fact -T "Client <Nom> — fiche contexte" … --tags client-boutique,ecommerce --commun non`.
2. Accès : compte collaborateur ou employé aux permissions limitées, jamais de mot de passe partagé [À VÉRIFIER :
   procédure Shopify en vigueur].
3. Réunion de lancement : objectifs, KPI, règles de validation (qui valide les actions 🟠).
4. Audit → plan → exécution selon le module 12, avec validation du client.
5. Rapport hebdomadaire : fait / résultats / semaine suivante / décisions attendues (`assets/modele-rapport-audit.md`
   pour le premier).
6. Fin de mission : passation, documentation, retrait des accès.

## 4. Cadre administratif et juridique

- Devis et conditions générales de prestation signés avant de commencer.
- Factures conformes (Code de commerce, art. L441-9) ; mention de franchise de TVA et facture électronique :
  module 09, section 12.
- Contrat de sous-traitance des données (RGPD, art. 28) si accès aux données des clients finaux.
- Activité de prestation déclarée ; activité mixte vente + services → plafond global de 203 100 € dont 83 600 € de
  services au plus ; cotisations des services : 21,2 % (BIC) ou 25,6 % (BNC ; le conseil en marketing relève
  probablement du BNC [HYPOTHÈSE]) — valeurs 2026, module 09.
- Factures électroniques entre entreprises : réception obligatoire depuis le 01/09/2026, émission à partir du
  01/09/2027, avec le SIREN du client.
- Clause de confidentialité ; limitation de responsabilité ; propriété des contenus produits.
