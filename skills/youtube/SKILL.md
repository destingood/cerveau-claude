---
name: youtube
description: "YouTube pour le cerveau : préparer, écrire, emballer et analyser ses propres vidéos en 11 étapes — planning, niche, script et accroche notée, titre et miniature, coupes, chapitres, description et tags, Shorts, commentaires, rétention, audit. Rien ne se publie : la skill écrit, l'utilisateur publie. À utiliser quand l'utilisateur dit « ma chaîne YouTube », « script de ma vidéo », « accroche de ma vidéo », « titre de ma vidéo », « miniature YouTube », « CTR de ma vidéo », « coupe les blancs », « chapitres de ma vidéo », « timestamps YouTube », « description YouTube », « tags YouTube », « fais des shorts de ma vidéo », « réponds aux commentaires YouTube », « planning de vidéos », « ce qui marche sur YouTube dans ma niche », « pourquoi les gens arrêtent de regarder », « audit de ma chaîne ». Ne pas utiliser pour lire la vidéo d'un autre — « résume cette vidéo », « transcris cette vidéo » : cerveau:agent-reach — ni pour monter ou animer une vidéo."
---

# YouTube — de l'idée à la vidéo prête à publier

Méthode et outils de **youtube-agent-skill** (Jake Schincariol, github.com/Jakeschincariol/youtube-agent-skill,
licence MIT : `LICENSE`), intégrés au cerveau en une seule skill. Les 11 étapes détaillées sont dans `references/`
(en anglais, texte d'origine) : lire **seulement** celle de la demande. Répondre et écrire les livrables dans la langue
de l'utilisateur ; une vidéo en français s'écrit en français, pas traduite de l'anglais.

## Les règles, avant tout (rien ne les lève)
- **Rien ne se publie.** La skill écrit, l'utilisateur publie. Chaque livrable finit par un bloc à copier et la
  question : **« on publie tel quel, ou on change ? »**. Connecteur YouTube : jamais `upload_video`, `update_video`,
  `update_thumbnail` ni `subscribe_channel` sans un oui explicite pour cette action-là ; jamais de réponse postée.
- **Aucun chiffre inventé** : vues, CTR, rétention, résultats, sources. S'il manque, le demander ou écrire sans.
- **Sa voix** : lire `~/.claude/youtube/voice.md`. Absent → modèle `assets/voice.md` : demander trois de ses vidéos,
  en déduire la voix, proposer le fichier et l'écrire sur son accord. Un script dans la mauvaise voix ne se dit pas.
- **Les autres chaînes : lecture publique seulement**, à vitesse humaine, jamais le compte d'un autre. On étudie leur
  forme (formule, rythme, emballage), on ne recopie ni leurs titres, ni leurs scripts, ni leurs miniatures.
- Partenariat ou placement de produit dans un script : mention « Publicité » ou « Collaboration commerciale » claire
  pendant toute la promotion (loi n° 2023-451 du 9 juin 2023, art. 5, modifié par l'ordonnance n° 2024-978 ; texte
  consolidé sur legifrance.gouv.fr).

## Les étapes
Chaque étape marche seule ; `references/11-audit.md` sur une chaîne dit par laquelle commencer.

| # | Demande | Fichier | Outil |
|---|---|---|---|
| 1 | Planning de la semaine : une vidéo phare, une vite faite, des Shorts tirés de la phare | `references/01-plan.md` | — |
| 2 | Ce qui marche dans la niche : vidéos classées par multiple de la médiane de leur chaîne, formule nommée | `references/02-viral.md` | `swipe.py` |
| 3 | Script : cinq accroches notées, structure, relances, fin | `references/03-script.md` | `hookscore.py`, `scripts/hooks.json` |
| 4 | Titre et texte de miniature, en paire ; CTR bas | `references/04-package.md` | `title.py` |
| 5 | Liste de coupes (blancs, euh, reprises), à appliquer dans son logiciel de montage | `references/05-edit.md` | `deadair.py` |
| 6 | Chapitres valides : 00:00 en premier, trois au moins, 10 s chacun | `references/06-chapters.md` | `chapters.py` |
| 7 | Description, tags, requêtes à gagner | `references/07-seo.md` | — |
| 8 | Shorts : moments qui tiennent seuls, nouvelle première phrase, boucle | `references/08-shorts.md` | `hookscore.py` |
| 9 | Commentaires : tri, brouillons de réponse, lequel épingler | `references/09-comment.md` | — |
| 10 | Rétention : fuite de l'accroche, chutes, glissement du milieu | `references/10-retention.md` | `retention.py` |
| 11 | Audit de chaîne : une seule correction prioritaire, ce qui marche déjà | `references/11-audit.md` | `title.py`, `hookscore.py` |

## Les outils
Python standard (3.8 ou plus), rien à installer, aucun accès réseau ; ils lisent les fichiers donnés et écrivent sur
la sortie. Ils sont dans `scripts/` du dossier de cette skill (« Base directory » au chargement) : les lancer par ce
chemin complet, `python` sous Windows, `python3` ailleurs —
`python "<dossier de la skill>/scripts/hookscore.py" --hook "…"`. Sans argument, chacun affiche son mode d'emploi.

Ajouts du cerveau au code d'origine : mots et motifs français dans `hookscore.py`, `title.py`, `chapters.py`,
`deadair.py` et `scripts/hooks.json` ; `deadair.py` et `chapters.py` lisent les sous-titres automatiques de YouTube ;
`retention.py` lit un CSV à `;` et virgule décimale ; `swipe.py` prend directement la sortie de yt-dlp, plusieurs
fichiers à la fois.

## Obtenir les entrées
- **Vidéos d'une chaîne** (étapes 2, 11), lecture publique avec yt-dlp (`uv tool install yt-dlp`) — quatre vidéos
  par chaîne au moins, plusieurs chaînes de la niche :
  `yt-dlp --flat-playlist -J --playlist-end 30 "https://www.youtube.com/@<chaîne>/videos" > chaine.json`, puis
  `swipe.py chaine1.json chaine2.json …`.
- **Transcription horodatée** (étapes 5, 6, 8, 10) : de préférence sa vidéo transcrite par whisper (JSON) ou le SRT
  téléchargé dans Studio ; sinon les sous-titres automatiques :
  `yt-dlp --skip-download --write-auto-subs --sub-langs fr --sub-format vtt -o sub "<lien>"`.
- **Rétention** (étape 10) : l'export de la courbe de fidélisation dans Studio (onglet Engagement de la vidéo,
  icône de téléchargement). Libellés français de Studio et format exact de l'export à confirmer sur le premier fichier.
- **Connecteur YouTube**, s'il est branché : `video_details`, `list_channel_videos`, `get_channel_statistics` en
  lecture. Son quota d'API s'épuise vite (403 quotaExceeded) → yt-dlp. `load_captions` ne lit que les vidéos du
  compte connecté.

## Limites
- Les scores (`hookscore.py`, `title.py`) sont des heuristiques ; d'origine, mesurés sur 74 accroches anglaises. En
  français ils ne sont **pas calibrés** : un score bas dit de relire, un score haut ne promet rien.
- Sous-titres automatiques : les cues se touchent, donc `deadair.py` ne trouve aucun blanc (DEAD) et `chapters.py`
  répartit plus par durée que par pauses. Pour le montage : une transcription whisper.
- `deadair.py` ne coupe rien : il donne la liste, le total retiré et la durée finale.

## Avec le cerveau
- Au début : `brain q "<chaîne ou sujet>"` pour reprendre (chaîne, niche, chaînes suivies, décisions prises).
- Mémoriser ce qui sert plus tard, après un `q` anti-doublon : la chaîne et sa niche (`brain add -t fact …`), les
  chaînes de référence, le format retenu et la correction prioritaire de l'audit (`-t decision`). Le profil de voix
  reste dans `~/.claude/youtube/voice.md`.
- Lire ou résumer la vidéo d'un autre, ou ce qu'en disent Reddit et X : skill `cerveau:agent-reach`.
- Script ou description qui sonne IA : skill `cerveau:humanizer`.
