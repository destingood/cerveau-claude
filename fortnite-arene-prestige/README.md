# Arène Prestige : map Fortnite (UEFN) Gun Game sans construction

Gun Game FFA pour 2 à 16 joueurs, avec pass de 30 paliers, 10 prestiges, arsenal de 10 armes signature
et progression sauvegardée entre les parties.

## Contenu

| Fichier | Rôle |
|---|---|
| [`GUIDE_UEFN.md`](GUIDE_UEFN.md) | **Commence ici.** Construire la map pas à pas, de l'installation à la publication. |
| [`DESIGN.md`](DESIGN.md) | Le design, les mécaniques de rétention et leur raison d'être, la miniature, les règles Epic, les chiffres à suivre. |
| [`verse/arene_donnees.verse`](verse/arene_donnees.verse) | Sauvegarde persistante, règles du pass, titres, arsenal. |
| [`verse/arene_prestige.verse`](verse/arene_prestige.verse) | Device principal : manches, éliminations, effets d'armes, XP, prestige, HUD. |
| [`outils/simulateur_progression.py`](outils/simulateur_progression.py) | Calcule combien de temps prend chaque palier (`python3 outils/simulateur_progression.py`). |

## Ce qui est fait, et ce qui reste à faire

- ✅ Toute la logique de jeu et de progression en Verse, commentée en français.
- ✅ Économie d'XP vérifiée par simulation : palier 1 en ~3 min, pass complet en ~7 h, prestige max en ~70 h.
- 🔧 **À faire par toi dans UEFN (Windows)** : construire l'arène, placer les devices, coller le code, tester, publier.
- ⚠️ Le code n'a pas pu être compilé ici. S'il y a une erreur au premier « Build Verse Code »,
  envoie le message exact pour obtenir la correction.
