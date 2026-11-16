# Fiche 04 — CV et LinkedIn d'un futur commercial

Objectif : un CV d'une page et un profil LinkedIn qui donnent envie d'appeler, même sans diplôme ni expérience de
vente. Ce qu'un recruteur commercial cherche : la preuve que tu sais **parler aux gens**, **tenir un objectif** et
**encaisser un refus**. Le diplôme passe après pour un premier poste de prospection [CONSEIL — à confirmer par les
offres de la niche : lis la rubrique « profil recherché » de dix offres avant d'écrire].

## 1. Trouver ses preuves (même sans expérience de vente)

Chercher dans toute sa vie ce qui ressemble à de la vente ou à un objectif, avec un chiffre :

| Où chercher | Exemple de ligne de CV |
|---|---|
| Job en magasin, restauration, livraison, téléphone | « Conseillé 40 clients par jour en période de soldes ; 2e vendeur du magasin en décembre 2025 » |
| Vente perso (Vinted, Leboncoin, revente de baskets, cartes) | « 85 ventes sur Vinted en 12 mois, note 4,9/5 sur 60 avis » |
| Sport en compétition, jeu vidéo en équipe | « Capitaine d'une équipe de 5, classée 3e sur 40 au tournoi régional 2025 » |
| Association, événement, projet perso | « Trouvé 6 sponsors locaux pour le tournoi du club (1 200 € récoltés) » |
| Porte-à-porte, collecte, phoning, job d'été | « 120 appels par jour pour une association ; 18 dons obtenus en une semaine » |

Règle : **rien d'inventé, rien de gonflé**. Un recruteur commercial vérifie, et un chiffre faux découvert en entretien
coûte le poste. `progression.py preuves` donne des phrases exactes dès qu'on a un journal.

## 2. Le CV

- Une page, une colonne, police simple, pas de tableau ni de graphique : beaucoup d'entreprises passent les CV dans un
  logiciel de tri qui lit mal les mises en page compliquées [PRATIQUE COURANTE].
- En haut : nom, **titre du poste visé** (« Vendeur conseil — informatique et téléphonie »), téléphone, e-mail, ville
  et moyen de transport, lien LinkedIn s'il existe. Photo et âge : facultatifs en France.
- Une accroche de deux phrases : le poste visé + la preuve la plus forte.
- Expériences : 3 à 5 lignes de résultats chacune, un chiffre par ligne, verbe d'action en tête (« obtenu »,
  « conseillé », « signé », « relancé »).
- Pas de qualités en l'air (« dynamique », « motivé ») : `cv.py --controle` les signale. Une qualité se prouve par un fait.
- Formation : en bas, courte. Une formation en cours (titre professionnel, alternance) se met avec la date de fin prévue.

Outil : `python cv.py --modele > cv.json`, remplir, `python cv.py cv.json --controle`, puis `python cv.py cv.json`
→ `cv.html`, à enregistrer en PDF depuis le navigateur.

**Orthographe** : avant toute génération, faire relire le texte entier (Claude, Antidote, LanguageTool) — fiche 03. Un
CV avec des fautes est souvent écarté sans être lu [PRATIQUE COURANTE] ; c'est le seul endroit où il ne doit en rester
aucune.

## 3. LinkedIn

Pour un poste en magasin, LinkedIn est un plus, pas une obligation. Il devient important pour monter (responsable,
directeur) et pour passer à la vente aux entreprises, où les recruteurs y cherchent les commerciaux [PRATIQUE COURANTE].

| Zone | Quoi mettre |
|---|---|
| Photo | Visage net, fond simple, souriant |
| Titre (sous le nom) | Le poste visé et le secteur : « Vendeur conseil tech | Informatique et téléphonie | Disponible en alternance » |
| Infos (« À propos ») | 4 à 6 phrases courtes : qui tu es, ce que tu veux vendre, tes preuves, ce que tu cherches |
| Expérience | Les mêmes lignes chiffrées que le CV |
| Préférences d'emploi | « Open to work » visible des recruteurs seulement (réglage du profil) |
| Activité | Un commentaire utile par semaine sous les posts de commerciaux ou d'entreprises visées : ça se voit |

Démarche : suivre les enseignes visées ; envoyer à des vendeurs ou responsables de magasin une demande de contact avec
un message court (« Je veux devenir vendeur chez X, je vois que vous y travaillez : est-ce que je peux vous poser deux
questions sur votre métier ? »). Un échange par semaine apprend plus qu'une formation, et ouvre des cooptations
[CONSEIL]. Claude rédige et relit les messages ; c'est toi qui les envoies.

## 4. Lettre et message de candidature

Courts : cinq phrases. Le poste, pourquoi cette entreprise (un fait précis sur elle), la preuve la plus forte, la
disponibilité, la demande d'un échange. Une candidature qui montre qu'on a cherché l'entreprise est déjà une
démonstration de prospection [CONSEIL].
