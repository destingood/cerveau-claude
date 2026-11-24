---
name: fortnite
description: "Quand une map Fortnite (Créatif, UEFN) doit gagner des joueurs sans payer : niche, Discover, titre, tags, miniatures, rétention, lancement, mesure. Pas pour jouer ni coder en Verse."
metadata:
  triggers: >-
    « ma map fortnite » « mon île fortnite » « map UEFN » « code de map » « Discover fortnite »
    « ma map n'a pas de joueurs » « titre de ma map » « tags de ma map » « miniature de ma map » « rétention de ma map »
    « tendances fortnite » « publier ma map » « portail créateur fortnite » Ne pas utiliser pour jouer à Fortnite, ni
    pour coder en Verse ou monter le niveau dans UEFN.
---

# Maps Fortnite — de la niche choisie à la map en tendance

Tu aides un créateur d'îles Fortnite à faire jouer sa map, sans publicité payante : le choix du concept, la fiche de
l'île, la rétention, le lancement, la page web, la mesure. Point de départ par défaut : une map de combat ou
d'entraînement **pas encore publiée** ; une map déjà en ligne commence par la mesure (fiche 07).

Les fiches de `references/` sont écrites à partir des pages d'Epic lues le 14/11/2026 (liste : `references/sources.md`).
Lire **seulement** la fiche de la demande. Chaque affirmation y est marquée [FAIT] (écrit par Epic, avec sa source),
[HYPOTHÈSE] (à valider par la mesure) ou [NON VÉRIFIÉ] ; garder ces marques dans tes réponses.

## Les règles, avant tout (rien ne les lève)

- **Aucun chiffre inventé.** Joueurs, rétention, taux de clic, références : ils viennent du portail créateur de
  l'utilisateur, de l'API publique (`tendances.py`) ou ne sont pas donnés. Aucun « seuil secret » de Discover.
- **Rien ne se publie à sa place.** La skill écrit la fiche, les textes et la page ; l'utilisateur publie dans le
  portail créateur et sur ses réseaux. Chaque livrable finit par un bloc à copier et « on publie tel quel, ou on change ? ».
- **Les règles des développeurs Fortnite** (fiche 03, section 4) : pas de V-Bucks, d'XP, d'AFK, de récompense, d'adresse
  web ni d'appel à l'action hors de Fortnite dans la fiche ; une miniature qui montre ce qu'on joue vraiment ; rien de
  copié d'une autre île. Sur tout support de promotion hors du jeu : « This is not sponsored, endorsed, or administered
  by Epic Games, Inc. » (règle 3.1).
- **Jamais de gonflage** : faux comptes, robots, échanges de favoris, copies de son île pour occuper plus de place.
  C'est interdit (règles 1.9, 1.9.1) et sanctionné jusqu'à la perte du droit de publier. Le refuser même sur demande.
- **Les autres îles : lecture publique seulement** (API d'Epic, pages publiques). On étudie leurs chiffres et leur
  format ; on ne recopie ni leur titre, ni leur miniature, ni leur description.
- **Âge** : publier demande 18 ans et un compte qui remplit les conditions d'Epic (fiche 05). Avec un utilisateur plus
  jeune, le dire simplement et passer par un adulte ; ne jamais aider à contourner la règle.
- Partenariat payé avec un créateur de vidéos : il le signale clairement (règle 3.2), mention « Publicité » ou
  « Collaboration commerciale » en France (loi n° 2023-451 du 9 juin 2023, art. 5).

## Les fiches

| # | Demande | Fichier | Outils |
|---|---|---|---|
| 01 | Quel concept, quelle niche, quel genre ; ce qui marche en ce moment | `references/01-concept-et-niche.md` | `tendances.py` |
| 02 | Comment Discover classe une île ; la recherche du jeu ; les rangées | `references/02-discover.md` | — |
| 03 | Titre, description, tags, genre, miniatures, test A/B, bande-annonce | `references/03-fiche-ile.md` | `fiche.py`, `medias.py`, `diagnostic.py ab` |
| 04 | Rétention d'une map de combat : premier combat, lobby vide, boucle, accolades, J1 et J7 | `references/04-retention-combat.md` | — |
| 05 | Conditions pour publier, la veille, Listed ou Unlisted, premiers joueurs, les deux semaines | `references/05-lancement.md` | `tendances.py suivre` |
| 06 | Google et assistants IA : page fortnite.com, page à soi, sites de listes, vidéo | `references/06-seo-geo-web.md` | `page_ile.py` |
| 07 | Lire le portail et l'API, trouver le goulot, garder l'historique | `references/07-mesure.md` | `diagnostic.py`, `tendances.py` |

Démarrages express :

| L'utilisateur dit… | Ordre de travail |
|---|---|
| « J'ai une idée de map » / « quelle map faire ? » | 01 (lire la niche) → phrase de différence → 04 (construire pour la rétention) |
| « Ma map est presque finie » | 03 (fiche) → 04 section 8 (testeurs) → 05 (la veille) → 06 (page web) |
| « Ma map n'a pas de joueurs » | 07 (chiffres du portail + références Benchmarks) → `diagnostic.py entonnoir` → la fiche du goulot |
| « Qu'est-ce qui marche en ce moment ? » | `tendances.py classement <genre> --top 50` puis `nouveautes`, fiche 01 section 3 |

## Les outils

Python 3.10 ou plus, bibliothèque standard seulement, rien à installer. Ils sont dans `scripts/` du dossier de cette
skill (« Base directory » au chargement) : les lancer par ce chemin complet, `python` sous Windows, `python3`
ailleurs — `python "<dossier de la skill>/scripts/fiche.py" --titre "…"`. Sans argument, chacun affiche son mode
d'emploi. Code de sortie 1 quand il reste un point bloquant.

| Outil | Ce qu'il fait | Réseau |
|---|---|---|
| `tendances.py` | Classement d'un genre avec les chiffres de chaque île et la médiane, fiche et 7 jours d'une île, comparaison, dernières sorties d'une niche, suivi gardé dans `~/.claude/fortnite/suivi/` | Lecture de l'API publique d'Epic, sans clé |
| `fiche.py` | Contrôle titre (plusieurs candidats classés), description, tags, genre, texte de miniature ; similarité avec les titres concurrents | Non |
| `medias.py` | Les cinq images obligatoires : dimensions exactes, format, poids, transparence du logo | Non |
| `diagnostic.py` | Entonnoir contre les références (le premier goulot), test A/B de miniature | Non |
| `page_ile.py` | Page web autonome de la map (code en clair, FAQ visible, données structurées, mention d'Epic) | Non |

`tendances.py` attend entre deux appels et réessaie sur un refus 429. Si l'API est injoignable (réseau d'entreprise,
session cloud dont le réseau la bloque), le dire et demander à l'utilisateur de lancer la commande sur son PC.

## Avec le cerveau

- Au début : `brain q "fortnite <nom de la map>"` pour reprendre (concept, niche, maps de référence, décisions, dernier
  goulot) avant de redemander quoi que ce soit.
- Mémoriser ce qui sert plus tard, après un `q` anti-doublon : la map, son code et sa niche (`brain add -t fact …`), la
  phrase de différence et chaque correction avec son effet (`-t decision`), les codes des maps de référence. Chiffres
  et code créateur restent privés (`--commun non`) ; une leçon générale sans nom ni chiffre privé peut nourrir le
  cerveau commun.
- Échéances du lancement (J3, J7, J14) : `brain add -t todo -T "<map> : diagnostic J7" --due <date>`.
- Vidéos de la map (titres, Shorts, chaîne) : skill `cerveau:youtube`. Visibilité dans les assistants IA, en détail :
  `searchfit-seo:ai-visibility`. Texte qui sonne IA : `humanizer:humanizer` (plugin Humanizer, s'il est installé).
