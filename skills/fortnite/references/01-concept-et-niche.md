# Fiche 01 — Choisir le concept et la niche (avant de construire)

Objectif : savoir, chiffres à l'appui, dans quelle niche de combat la map a une place, et ce qu'elle doit avoir de
différent. À faire avant de finir la map : changer de concept après la publication coûte la fenêtre de test (fiche 02).

## 1. Ce que dit Epic sur la concurrence

- Le genre **Shooter** comptait 134 952 îles classées le 14/11/2026 [FAIT — Fortnite Data API,
  `/genres/shooter/rankings`]. Une map de plus dans un format déjà servi ne reçoit rien par défaut.
- Epic retire de la mise en avant les îles pour « Duplicative Content » et « Minimal Gameplay & Thumbnail Standards »,
  et interdit de publier plusieurs copies d'une même île ou de sa fiche pour gagner en visibilité [FAIT — How Discover
  Works ; règles des développeurs 1.9].
- Le contrôle avant publication compare le titre aux titres existants : « Similarity Warning », avec une visibilité
  réduite dans Discover [FAIT — Game Details]. Le titre d'origine appartient à l'île qui a eu 100 joueurs uniques en
  96 heures ou 150 minutes d'édition sur 30 jours [FAIT — How Discover Works].
- Les signaux de Discover se mesurent **par joueur** : « deep engagement can even outperform a large audience »
  [FAIT — How Discover Works]. Une petite map très rejouée peut passer devant une grosse map vite quittée.

## 2. Le genre décide de la rangée

Un seul genre par île ; il décide de la rangée de genre ; en changer oblige à republier [FAIT — How Discover Works].

| Format | Genre selon la définition d'Epic | Identifiant API |
|---|---|---|
| Zone wars, dernier survivant sur zone qui se referme | Battle Royale (« For example: zone wars ») | `battle-royale` |
| Free for all, arène, entraînement, aim, gun game | Shooter (« free-for-alls, arenas, and training maps ») | `shooter` |
| Box fight, realistics, 1v1 de construction | Pas cité par Epic. Une map « 2v2 realistics » de tête était classée en Battle Royale le 14/11/2026 (une seule observation) | à vérifier : `tendances.py ile <code d'un concurrent>` |

## 3. Lire la niche (15 minutes, zéro euro)

```
python scripts/tendances.py classement battle-royale --top 50 --tag zonewars
python scripts/tendances.py classement shooter --top 50 --mot "1v1" --titres titres.txt
python scripts/tendances.py nouveautes --tag boxfight --pages 3
python scripts/tendances.py comparer <code> <code> <code> --json > niche.json
```

Ce qu'on y lit :

| Chiffre | Ce qu'il dit | Décision |
|---|---|---|
| Joueurs par jour et pic des premières | La taille de la niche | Trop petite : peu de joueurs à gagner. Écrasée par une seule map : se placer à côté, pas en face |
| Minutes par joueur, J1, J7 (médiane) | La barre : ce que les joueurs de cette niche font déjà | La map doit viser au moins la médiane ; c'est la référence de `diagnostic.py --reference niche.json` |
| Tendance sur 7 jours | Ce qui monte en ce moment | Une map en forte hausse hors du haut du classement montre un format qui prend |
| Tags des premières | Les tags que la niche utilise | Les reprendre quand ils sont vrais pour la map (quatre au plus, fiche 03) |
| `nouveautes` : nombre de sorties et mots des titres | La saturation et les noms déjà pris | Beaucoup de sorties aux mêmes mots : trouver un nom et un angle que personne n'a |

L'API ne donne ni impressions ni taux de clic : on voit ce que les joueurs font dans une map, pas comment ils y
arrivent. Refaire le relevé chaque semaine (`tendances.py suivre`) : l'API n'a que 7 jours de mémoire.

## 4. La différence, en une phrase

Écrire, avant de construire : « C'est un <format> pour <qui>, et c'est la seule où <fait vérifiable> ». Le fait doit se
voir sur la miniature et se sentir dans les deux premières minutes (fiche 04). Pistes pour une map de combat
[HYPOTHÈSE — à valider sur la niche lue plus haut] :

- un format connu avec une règle en plus (zones qui changent à chaque manche, équipement tiré au sort, manche courte) ;
- un public précis mal servi (débutants, manette, 1v1 rapides sans attente, entraînement d'une seule mécanique) ;
- une finition que les premières n'ont pas (attente nulle, statistiques de manche, rendu propre à 60 images par seconde).

Ce qui ne compte pas comme différence : un décor, un nom, « meilleure » ou « nouvelle » dans le titre.

## 5. Pièges à éviter dès le concept

- Copier une map de tête (titre, miniature, description) : interdit [FAIT — règle 1.6], et le contrôle de similarité
  le voit.
- Un concept qui dépend d'une promesse interdite dans la fiche : XP, V-Bucks, récompenses, AFK [FAIT — règle 1.13].
- Une map qui ne marche qu'à 16 joueurs : au lancement elle sera vide (fiche 04, section lobby).
- Une marque qui ne t'appartient pas (personnages, musiques, logos) : pas de contenu sous licence d'un tiers sans droits.

À garder dans le cerveau : la niche choisie, la phrase de différence, les codes des maps de référence
(`brain add -t decision …`).
