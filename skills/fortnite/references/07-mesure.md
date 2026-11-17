# Fiche 07 — Mesurer : le portail créateur, l'API publique, le diagnostic

Objectif : savoir chaque semaine quelle étape fuit, et ne corriger qu'elle.
Sources : Project Analytics for Fortnite Games, Fortnite Data API (spécification OpenAPI 1.1.0), billet Discover
Performance Snapshot (lus le 14/11/2026).

## 1. Deux sources, qui ne disent pas la même chose

| | Portail créateur (Analytics) | Fortnite Data API (`tendances.py`) |
|---|---|---|
| Accès | Propriétaire, administrateur ou éditeur de l'île | Public, sans clé ni compte |
| Îles | Les siennes | Toutes les îles publiques et visibles dans Discover |
| Impressions, clics, taux de clic | Oui (impression : miniature entièrement visible 2 secondes ; fortnite.com non compté) | Non |
| Rebond à 2, 5 et 10 minutes, durée de session | Oui | Non (minutes par joueur seulement) |
| J1 et J7 | Oui (« Classic Retention ») | Oui |
| Joueurs, parties, minutes, pic, favoris, recommandations | Oui, avec filtres (pays, plateforme, taille du groupe, source) | Oui, par jour, heure ou tranche de 10 minutes |
| Rang dans le genre | Non | Oui (relevé horaire) |
| Historique | Le portail | 7 jours ; rien sous 5 joueurs uniques sur la période |
| Références | Menu Benchmarks | La médiane d'îles qu'on choisit (`comparer`) |

Les deux peuvent différer : Epic le dit [FAIT]. Pour sa propre île, le portail fait foi.

## 2. Le menu Benchmarks du portail

- Références pour le taux de clic, le rebond, la durée de session, J1 et J7 [FAIT].
- Groupe de comparaison : les îles éligibles du même genre classées par temps de jeu actif ; les 10 % premières, 100 au
  moins et 1 000 au plus ; éligible : 50 sessions au moins ce jour-là. La ligne pointillée est la médiane : « The
  median is a reasonable target. » [FAIT]
- Ces références sont celles à donner à `diagnostic.py --ref-…`.

## 3. Le diagnostic de la semaine

```
python scripts/diagnostic.py entonnoir --impressions … --clics … --rebond2 … --rebond5 … --rebond10 … \
    --session … --j1 … --j7 … --ref-ctr … --ref-rebond5 … --ref-session … --ref-j1 … --ref-j7 …
```

Il range l'île étape par étape contre ses références et nomme **le premier goulot** : la première étape à plus de
10 % sous sa référence. La lecture de chaque étape est celle d'Epic (fiche 04). Sans référence, pas de verdict.
Avec peu d'impressions, la fourchette du taux de clic est large : le script le dit.

Références de la niche tirées de l'API (J1 et J7 seulement) :
`tendances.py comparer <codes> --json > niche.json` puis `diagnostic.py entonnoir --j1 … --j7 … --reference niche.json`.

## 4. Où les joueurs arrivent

Filtre « Sources » du portail [FAIT] : Discover (rangées générales, barre d'accueil, recommandations), By Epic,
collections, résultats de recherche, Sponsored Row, abonnements, récents, bibliothèques, catégories, pages de profil,
autres. Plus l'onglet Links pour ses liens de suivi.

| Ce qu'on voit | Lecture [HYPOTHÈSE] |
|---|---|
| Presque tout vient des liens et des récents | Discover ne pousse pas encore l'île : travailler le taux de clic et le rebond |
| La recherche pèse lourd | Le titre et les tags marchent ; Discover peut suivre si la rétention tient |
| Discover pèse lourd et la rétention baisse | La miniature attire un public que la map ne retient pas : miniature trop large ou trompeuse |

## 5. Garder l'historique

L'API oublie au bout de 7 jours. `tendances.py suivre <code> [<code concurrent> …]` ajoute les jours nouveaux à
`~/.claude/fortnite/suivi/<code>.json` : à lancer une fois par semaine au moins (ou la veille automatique du cerveau).
Les exports du portail : télécharger le CSV quand il est proposé (format non documenté par Epic [NON VÉRIFIÉ] : le
lire avec Claude au premier fichier).

## 6. Une correction à la fois

Une seule modification par version, mesurée une semaine. Sinon on ne sait pas ce qui a marché. Noter chaque
modification et son effet : `brain add -t decision -T "<map> : <changement>" -b "goulot, chiffre avant, date de revue"`.
