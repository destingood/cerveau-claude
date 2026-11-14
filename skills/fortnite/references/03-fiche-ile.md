# Fiche 03 — La fiche de l'île : titre, description, tags, genre, miniature, bande-annonce

Objectif : une fiche qui passe le contrôle d'Epic, se trouve à la recherche, et promet exactement ce qu'on joue.
Sources : pages « Game Details », « Making Thumbnails and Videos », « Thumbnail Image Policies », « A/B Thumbnail
Testing », « Promotional Media » (dev.epicgames.com, lues le 14/11/2026) et règles des développeurs (29/04/2026).

## 1. Titre

- Epic : « Your island name should go beyond the genre your island falls under. » [FAIT]. Un titre fait de mots du
  genre seulement (« 1v1 Box Fight ») ressemble à des milliers d'autres et déclenche l'avertissement de similarité.
- Forme qui marche avec la recherche (mots exacts, fiche 02) : **nom à soi + terme exact du format + taille d'équipe**,
  par exemple « NEON 2V2 ZONE WARS » [HYPOTHÈSE pour l'ordre des mots ; FAIT pour la correspondance exacte].
- Longueur maximale : non publiée [NON VÉRIFIÉ] ; le portail la montre à la saisie. Repère : la longueur des titres
  de la niche (`tendances.py classement … --titres titres.txt`).
- Le titre devient le `<title>` de la page fortnite.com de l'île (fiche 06) : c'est aussi le mot-clé Google.
- Contrôle : `python scripts/fiche.py --titre "…" --titre "…" --concurrents titres.txt` classe plusieurs candidats.

## 2. Description

- Epic : propre à l'île, « not generic or misleading » ; une accroche, puis le détail du jeu [FAIT].
- Première phrase : pour qui, quel format, la différence (fiche 01). Ensuite des faits : joueurs, durée d'une manche,
  nombre de zones, réglages. La page fortnite.com affiche ce texte tel quel et Google en tire son extrait (fiche 06).
- Les lignes « How to Play » s'affichent à l'écran de chargement : trois consignes courtes qui fixent l'attente [FAIT].
- Longueur maximale : non publiée [NON VÉRIFIÉ].

## 3. Tags et genre

- **Quatre tags au plus**, pris dans une liste fermée ; ils servent à la recherche du jeu [FAIT]. Ils ne décident pas
  des rangées : c'est le genre (fiche 01).
- Tags utiles au combat (orthographe exacte) : tailles `1v1` à `8v8` ; modes `Boxfight`, `ZoneWars`, `Free for All`,
  `Team Free for All`, `Gun Fight`, `Gun Game`, `One Shot`, `Search & Destroy`, `Capture the Flag`, `King of the Hill` ;
  entraînement `Aim Course`, `Edit Course`, `Practice`, `Training`, `Skills` ; `Arena`, `Building`, `Competitive`,
  `PVP`, `Shooter`, `Sniper`, `Teams`, `Rounds`, `Respawn`, `Solo`, `Duo`, `Trios`, `Squad`. Pas de tag « Red vs Blue ».
- Choix : le mode, la taille d'équipe, puis deux tags que les maps de tête de la niche portent et qui sont vrais ici.

## 4. Ce qui est interdit dans le nom, la description, la miniature et le texte de chargement

| Interdit | Règle |
|---|---|
| V-Bucks, Passe de combat, monnaie réelle, récompenses | 1.13 |
| Les termes « AFK », « XP », « Coin farm », « Coin slide » ; tout ce qui promet de l'XP ou des objets | 1.13 |
| Imiter l'interface de Fortnite (indicateur d'XP, note) | 1.13 |
| Adresse web, QR code, demande de message privé | 1.2 |
| Appel à l'action hors de Fortnite (« abonne-toi », nom d'un réseau), prix, dates d'offre | 4.3 |
| Demander d'utiliser son code créateur | 4.2 |
| Titre, miniature ou description copiés d'un autre | 1.6 |
| Tromper sur l'expérience (« Do not mislead players as to the sort of experience they will have ») | 1.13 |

Conséquences écrites par Epic : avertissement, visibilité réduite, contenu désactivé, perte du droit de publier.

## 5. Miniatures (obligatoires depuis le 22/10/2026)

| Image | Dimensions | Format | Rôle |
|---|---|---|---|
| Paysage « art + logo » et paysage « art seul » | 1920 × 1080 exactement, 5 Mo au plus | PNG ou JPG | Discover |
| Portrait « art + logo » et portrait « art seul » | 1440 × 1920 | PNG ou JPG | Mises en avant et mobile |
| Logo du nom de l'île | 1440 × 608 | PNG transparent | Posé par Fortnite sur l'art seul |
| Fond du lobby (facultatif) | 2048 × 1024, 10 Mo au plus | PNG ou JPG | Pas de test A/B dessus |

- Zone libre : 200 px (environ 15 %) en haut et en bas, le logo y est placé et rogné automatiquement [FAIT].
- Contrôle des fichiers : `python scripts/medias.py dossier-des-images/`.

Ce qu'Epic refuse sur une miniature de combat [FAIT — Thumbnail Image Policies, règle 1.15, How Discover Works] :
tir en cours depuis une arme visible, viseur sur un visage ou une tête, arme pointée vers le spectateur ou vers la tête
d'un personnage, sang ; une arme ou un appareil absent de l'île ; touches d'une plateforme précise ; logos ou
illustrations officielles d'Epic ; photo d'une personne réelle. Signalés automatiquement : fond uni, vide ou en
dégradé, armes « plaquées » sur l'image au lieu d'être dans le décor de l'île, capture d'écran brute. Autorisé : une
arme tenue par un personnage ou posée sur un râtelier de l'île ; du texte sur l'image.

Ce qui fait cliquer [HYPOTHÈSE — à trancher par le test A/B] : un seul sujet lisible en petit, l'action du format
(deux joueurs face à face pour un 1v1), le décor réel de la map, peu de texte.

## 6. Test A/B de miniature

- Dans le portail, étape Promotional Media, « Create A/B Test » : deux variantes, moitié des joueurs chacune,
  affectation fixe par compte, sur Discover, la navigation et la recherche [FAIT].
- La variante B porte le jeu complet (paysage, portrait, logo) : pas de mélange entre variantes [FAIT].
- Mesures : impressions, clics, taux de clic. Durée : 90 jours au plus, en général quelques jours à deux semaines.
  Seuil : 90 % de confiance. Sans écart net à 90 jours, la miniature A reste [FAIT].
- Un seul test par version, et pas de nouvelle version tant qu'il tourne ; si une variante est refusée à la modération,
  toute la soumission l'est [FAIT] : ne pas lancer un test la veille d'une mise à jour prévue.
- Lire un test en cours : `python scripts/diagnostic.py ab --a impressions:clics --b impressions:clics`.

## 7. Bande-annonce et vidéo de jeu (facultatives)

- 15 à 30 secondes, MOV, codec ProRes, 16:9, audio stéréo non compressé [FAIT].
- La bande-annonce se lance au survol de la miniature dans Discover et à la sélection de l'île ; jusqu'à cinq dans le
  carrousel ; une bande-annonce tous publics est exigée pour Epic's Picks [FAIT].
- Vidéo de jeu : jeu réel sans coupe, interface visible, ni texte ajouté ni musique sous licence. Conseil d'Epic pour
  le joueur contre joueur : montrer les lignes de vue de plusieurs zones [FAIT]. Jusqu'à trois captures d'écran.

## 8. Ordre de travail

1. `fiche.py` sur trois titres candidats, avec les titres de la niche. 2. Description et « How to Play ». 3. Tags et
genre. 4. Miniatures, puis `medias.py`. 5. Variante B prête avant la publication, pour lancer le test dès que l'île
reçoit des impressions.
