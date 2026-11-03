---
name: logo-design
description: "Créer, refaire ou critiquer un logo avec la skill Logo Design de kaankiziltug (github.com/kaankiziltug/logo-design-skill, licence MIT) : brief, trois concepts montrés en gris avant tout le reste, logo construit en SVG propre, testé à 16 px, en une couleur et en négatif, puis, si la direction est validée, le kit (couleurs, versions horizontale et empilée, favicon et icônes d'appli, planche de présentation, mini-charte). Vérifie qu'elle est là, sinon l'installe sur ce PC avec l'accord de l'utilisateur. À utiliser quand l'utilisateur dit « crée un logo », « refais mon logo », « critique mon logo », « idées de logo », « logo pour ma boutique », « identité visuelle », « charte graphique », « crée un favicon », « icône de mon appli ». Ne pas utiliser pour animer un logo (cerveau:motion-design)."
---

# Logo — un signe simple, distinctif, qui marche à 16 px

## 1. Déjà là ?
`~/.claude/skills/logo-design/SKILL.md` existe → charger la skill `logo-design` et la suivre ; elle renvoie à
`references/` (ne lire que le fichier de l'étape en cours) et lance ses scripts depuis `scripts/`. Sinon, installer
(2). Sans installation, sa méthode peut se suivre une fois :
https://raw.githubusercontent.com/kaankiziltug/logo-design-skill/main/skills/logo-design/SKILL.md
mais sans scripts ni bibliothèque, donc ni audit, ni rendu, ni planches : le dire à l'utilisateur.

## 2. Installer (code tiers : l'utilisateur donne son accord, ou lance lui-même la commande)
1. Node.js (`node --version`) pour installer ; Python 3 (`python --version`) pour les scripts, qui n'utilisent que la
   bibliothèque standard (rien à installer avec pip).
2. Pour tous les projets, en copie, télémétrie coupée (≈ 14 Mo, dont 1 432 logos SVG de référence) :
   - PowerShell : `$env:DO_NOT_TRACK=1; $env:DISABLE_TELEMETRY=1; npx -y skills add kaankiziltug/logo-design-skill -g -a claude-code -y --copy`
   - Bash : `DO_NOT_TRACK=1 DISABLE_TELEMETRY=1 npx -y skills add kaankiziltug/logo-design-skill -g -a claude-code -y --copy`
   Résultat : `~/.claude/skills/logo-design`, commande `/logo-design`.
3. Rendu en PNG : `python ~/.claude/skills/logo-design/scripts/render_png.py --which` doit citer au moins un moteur
   (cairosvg, rsvg-convert, Inkscape, ou Chrome / Edge lancé sans fenêtre ; sous Windows, Edge suffit).
4. Déclencheurs en français : `brain skill trig logo-design "crée un logo" "refais mon logo" "critique mon logo"
   "idées de logo" "besoin d'un logo" "identité visuelle" "crée un favicon"`, puis nouvelle conversation. Jamais
   « logo pour mon site / ma boutique » ni « nouveau logo » : « anime le logo de mon site » partirait ici au lieu de
   cerveau:motion-design.

Mise à jour : `npx -y skills update -g` (les déclencheurs ajoutés par `brain skill trig` restent). Retrait :
`npx -y skills remove logo-design -g -a claude-code -y`, puis `brain skill --force trig logo-design`.

## Règles
- Travailler dans un dossier du projet (par exemple `logo/`), jamais dans celui de la skill ; garder chaque version
  (`concept-a-v1.svg`, `-v2.svg`…) au lieu d'écraser.
- Sous Windows, `python` et non `python3` (souvent le raccourci du Microsoft Store), avec le chemin complet du script.
- Tokens : ne jamais lire `assets/library/catalog.json` (≈ 0,9 Mo), `classifications.json` ni `gallery.html`
  (≈ 0,5 Mo). Passer par `search_library.py` (`--summary`, puis `--format paths`) et ouvrir 3 à 5 SVG au plus ; la
  galerie s'ouvre dans un navigateur, pour l'utilisateur.
- Étape d'arrêt obligatoire : trois concepts en gris (`concept_sheet.py … --greyscale`), regardés avant d'être montrés,
  image envoyée à l'utilisateur, puis attendre son choix avant de faire le kit. Seule exception : il a dit de tout
  livrer sans demander.
- Les titres des planches sont en anglais, fixés dans les scripts ; les noms et idées (`--names`, `--notes`) et le
  fichier de présentation s'écrivent dans la langue de l'utilisateur.
- La bibliothèque sert à apprendre, jamais à décalquer : ce sont des marques déposées. Aucune garantie que le logo est
  libre : conseiller une recherche d'antériorité avant d'imprimer (France : data.inpi.fr, rubrique Marques, qui couvre
  aussi les marques européennes et internationales ; monde : WIPO Global Brand Database). La recherche gratuite ne
  trouve que les signes identiques, pas les proches : pour une marque qui compte, un conseil en propriété industrielle.
- Police : licence qui autorise l'usage dans un logo (les polices SIL OFL de Google Fonts le permettent) ; dans le
  fichier final, lettres converties en tracés, aucun `<text>`.
- Ne jamais annoncer un test ou un rendu qui n'a pas été fait et regardé.
