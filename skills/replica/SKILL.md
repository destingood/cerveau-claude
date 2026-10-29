---
name: replica
description: "Replica pour le cerveau : refaire sa propre version d'une app existante, en 11 étapes — analyse (écrans, parcours, modèle de données), architecture, design, construction, backend, tests, score de parité, avis des utilisateurs (ce qu'ils détestent → corrections et angle de vente), nouvelle marque, lancement (page, prix, fiche App Store / Google Play), mise en ligne. Fonctions et parcours seulement, jamais le code, le logo, les textes ni le contenu de l'original. À utiliser quand l'utilisateur dit « replica », « clone cette app », « refais cette app », « ma version de X », « copie cette app », « reverse engineer X », « qu'est-ce que les utilisateurs de X détestent », « score de parité », « rebrande mon clone », ou colle le lien d'une app ou d'une fiche App Store pour la refaire. Ne pas utiliser pour une boutique en ligne (cerveau e-commerce) ni pour une app créée de zéro sans modèle."
---

# Replica — refaire une app, à sa façon

Méthode et outils de **replica-skill** (Jake Schincariol, github.com/Jakeschincariol/replica-skill, licence MIT :
`LICENSE`), intégrés au cerveau. Les 11 étapes détaillées sont dans `references/` (en anglais, texte d'origine) : lire
**seulement** celle de l'étape en cours. Répondre et écrire les livrables dans la langue de l'utilisateur.

## Les règles, avant tout (rien ne les lève)
- **Ce que l'app fait, jamais ce qu'elle possède** : fonctions et parcours, réécrits de zéro. Jamais son code, ses
  fichiers JavaScript, une décompilation, ses API privées, son logo, ses textes, son contenu ni ses données.
- **Sources publiques et compte de l'utilisateur seulement** : jamais le compte d'un autre, jamais de mot de passe
  demandé, jamais de contournement d'un paywall ou d'une connexion ; lecture à vitesse humaine, pas de robot.
  Si les conditions du compte interdisent de bâtir un concurrent : le dire et rester sur le public.
- **Nouvelle marque avant toute mise en ligne** : `sweep.py` propre, sinon pas de déploiement.
- **Rien d'inventé** : chaque avis cité a son lien, la taille d'échantillon est donnée.
- Droit français, pour situer le risque (pas un avis juridique ; avant de vendre : juriste) : le logiciel est protégé
  par le droit d'auteur (CPI art. L112-2 13°), pas ses fonctionnalités (CJUE, 2 mai 2012, SAS Institute, C-406/10) ;
  décompiler n'est permis que pour l'interopérabilité (CPI art. L122-6-1 IV) ; nom et logo relèvent des marques
  (CPI art. L713-2 et suivants) ; une base de données a un droit propre (CPI art. L341-1) ; copier de trop près
  l'ensemble peut constituer du parasitisme (Code civil art. 1240). Marques à vérifier : data.inpi.fr, EUIPO
  (TMview), base mondiale de l'OMPI.

## L'ordre
Chaque étape lit ce que la précédente a écrit dans le dossier `replica/` du projet. Une étape seule marche aussi :
`08-entrepreneur` sur une app qu'on hésite à refaire dit s'il y a un créneau.

| # | Étape | Fichier | Écrit dans `replica/` | Outil |
|---|---|---|---|---|
| 1 | Analyse de l'app : périmètre, sources, écrans S01…, parcours F01…, composants, modèle de données, matrice de fonctions, taille | `references/01-recon.md` | `recon.md`, `features.csv`, `screens/` | — |
| 2 | Pile technique, schéma SQL, routes, ordre de construction | `references/02-architect.md` | `architecture.md`, `schema.sql` | — |
| 3 | Design en jetons (couleurs, typo, espacements, composants), éléments à soi | `references/03-design.md` | `design/tokens.json`… | `contrast.py` |
| 4 | Construction écran par écran, parcours principal d'abord | `references/04-build.md` | code, `build-log.md`, `clone-screens/`, `features.csv` à jour | — |
| 5 | Connexion, base, paiements, e-mails, intégrations par API officielles | `references/05-backend.md` | `backend.md` | — |
| 6 | Plan de test, Playwright, bugs par gravité | `references/06-test.md` | `test-plan.md`, `bugs.md` | — |
| 7 | Score de parité et ce qui manque ; écart de mise en page | `references/07-diff.md` | `parity.md`, `diffs/` | `parity.py`, `imgdiff.py` |
| 8 | Avis réels : ce qui déplaît, classé et sourcé → corrections, angle | `references/08-entrepreneur.md` | `reviews.csv`, `feedback.md`, `fixes.md` | `reviews.py` |
| 9 | Nom, palette, brief de logo, ton ; balayage des restes de l'original | `references/09-brand.md` | `brand.md`, `brand.json` | `sweep.py`, `contrast.py` |
| 10 | Page d'accueil, prix, fiche des stores | `references/10-launch.md` | `launch/` | `listing.py` |
| 11 | Contrôle avant départ, production, DNS, mise en ligne sur son accord | `references/11-deploy.md` | `deploy.md` | les quatre ci-dessus |

Modèles à copier : `assets/` (recon-map.md, features.csv, architecture.md, tokens.json, test-plan.md, bug-report.md,
e2e.example.spec.ts, listing.example.json, preflight.md).

## Les outils
Python standard (3.8 ou plus), rien à installer, aucun accès réseau ; ils lisent les fichiers donnés et n'écrivent
que vers `--out`. Ils sont dans `scripts/` du dossier de cette skill (« Base directory » au chargement) : les lancer
depuis le projet par ce chemin complet, `python` sous Windows, `python3` ailleurs —
`python "<dossier de la skill>/scripts/parity.py" replica/features.csv`. `--help` sur chacun.

## Avec le cerveau
- Au début : `brain q "<nom de l'app>"` pour reprendre un travail déjà commencé ; le dossier `replica/` du projet
  fait foi pour l'avancement.
- À chaque étape finie : mémoriser ce qui sert plus tard (pile choisie et pourquoi, nom retenu, score de parité,
  angle de vente) — `brain add -t decision …` ou `-t fact …` dans le projet, après un `q` anti-doublon.
- Étape 8 : avis Reddit, X ou YouTube que WebFetch ne lit pas → skill `cerveau:agent-reach` si l'outil est installé.
- Code exposé (connexion, paiements, API, étape 5) → skill `cerveau:securite` avant de livrer.
- Mise en ligne en France : mentions légales (LCEN), information RGPD (art. 13), consentement aux cookies (loi
  Informatique et Libertés art. 82, recommandations CNIL), CGV et droit de rétractation de 14 jours pour une vente à
  des particuliers (Code de la consommation art. L221-18).
