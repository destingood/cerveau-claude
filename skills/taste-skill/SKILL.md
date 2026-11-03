---
name: taste-skill
description: "Direction artistique et motion design d'un site ou d'une appli avec taste-skill de Leonxlnx (github.com/Leonxlnx/taste-skill, licence MIT, skill design-taste-frontend) : trois directions tirées de 247 sites de galeries, typo, palette, héros et sections, puis une couche d'animation obligatoire (moment signature, entrées par section, retour sur chaque contrôle, image qui bouge), contrôlée sur captures. L'installe au besoin avec l'accord de l'utilisateur, ou suit sa partie animation sans l'installer. À utiliser quand l'utilisateur dit « motion design », « site animé », « animations du site », « site vivant », « effet au scroll », « direction artistique », « refais le design », « refais ma landing page », « design pro », « design premium », « style Awwwards », « ça fait template », « rends mon site plus beau », « taste skill ». Ne pas utiliser pour régler une seule animation (cerveau:motion-design), un seul bouton (cerveau:emil-kowalski) ni pour reproduire une capture ou une maquette (cerveau:image-to-code)."
---

# Taste-skill — une vraie direction artistique, et un site qui bouge

## 1. Déjà là ?
`~/.claude/skills/design-taste-frontend/SKILL.md` existe → charger la skill `design-taste-frontend` et suivre ses
10 étapes ; elle renvoie à `references/` (motion, scenes, type, colour, layout, copy, imagery…) : ne lire que le
fichier qui sert à l'étape. Sinon, installer (2), ou pour une seule tâche suivre sans l'installer sa partie animation :
https://raw.githubusercontent.com/Leonxlnx/taste-skill/main/skills/taste-skill/references/motion.md
(le tirage et les contrôles par captures ne marchent qu'avec la skill installée).

## 2. Installer (code tiers : l'utilisateur donne son accord, ou lance lui-même la commande)
1. Node.js 22 ou plus (`node --version`) et Chrome, Edge ou Chromium pour les captures ; rien d'autre à installer.
2. Pour tous les projets, en copie (plus sûr sous Windows), télémétrie coupée :
   - PowerShell : `$env:DO_NOT_TRACK=1; npx -y skills add Leonxlnx/taste-skill -g -a claude-code -y --copy`
   - Bash : `DO_NOT_TRACK=1 npx -y skills add Leonxlnx/taste-skill -g -a claude-code -y --copy`
   Résultat : `~/.claude/skills/design-taste-frontend`, commande `/design-taste-frontend`.
3. Déclencheurs en français : `brain skill trig design-taste-frontend "motion design" "site animé" "direction artistique"
   "refais le design" "design premium" "ça fait template"`, puis nouvelle conversation.

Mise à jour : `npx -y skills update -g` (réécrit la skill ; les déclencheurs ajoutés par `brain skill trig` restent).
Retrait : `npx -y skills remove design-taste-frontend -g -a claude-code -y`, puis
`brain skill --force trig design-taste-frontend`.

## Scripts de la skill (dans `scripts/`)
- `draw.mjs` : tire trois directions, puis la typo, la palette, le héros et les sections (`--app` : écrans d'appli).
- `assets.mjs` : cherche de vraies images libres (Openverse, Wikimedia…), `--get` les télécharge avec leur crédit.
- `lint.mjs` : motifs interdits et phrases toutes faites ; `inspect.mjs` : page ouverte dans Chrome, captures à
  1440, 768 et 390 px, il faut 0 FAIL ; `scenes.mjs` : contrôle d'une scène animée.
- Écrit `.taste-skill/` dans le projet (à mettre dans `.gitignore`) et l'historique des tirages dans
  `~/.taste-skill/history.json`. `assets.mjs` a besoin du réseau, sans clé d'API.

## Motion design (étape 9 et `references/motion.md`)
- Couche d'animation obligatoire : l'inspecteur échoue sous 8 éléments qui bougent et alerte sous 16.
- Quatre parties : un moment signature ; les entrées par section (titre, puis texte, puis image, décalées de 60 à
  90 ms, montée de 16 à 32 px avec l'opacité, une seule fois) ; un retour sur chaque contrôle ; une image qui bouge.
- Durées : appui 140 ms, survol de couleur 180 à 200 ms, survol avec déplacement 300 à 400 ms, menu 240 ms,
  apparition 700 à 900 ms, ouverture d'image 1 100 à 1 300 ms ; sortie à 60-70 % de l'entrée ; transition de page
  480 ms au plus. Ni dépassement (overshoot) ni `ease-in`.
- Animer `transform`, `opacity` et `clip-path` ; tout état caché se met sous `prefers-reduced-motion: no-preference`,
  pour que celui qui refuse le mouvement voie toute la page.
- Interdits : préchargeur, curseur personnalisé, molette détournée ; défilement lissé seulement par `Stage.smooth()`.
- `draw.mjs` répond « No scene library yet. » → construire la scène (`references/scenes.md` §8) et la contrôler
  avec `scenes.mjs`.
- Régler finement une animation précise (courbe, ressort, Lottie) : `cerveau:motion-design` en plus.

## Règles
- Avant le code : la direction retenue et l'idée du site, en une ligne chacune.
- Juger sur les captures, pas sur le code ; corriger puis recapturer jusqu'à 0 FAIL aux trois largeurs.
- Rapport final : direction, retirages, crédits de chaque image trouvée, résultat de `inspect.mjs` ; ce que
  l'inspecteur n'a pas pu vérifier (pas de Chrome, pas de réseau) est dit.
- Durées en millisecondes ; réponses dans la langue de l'utilisateur, même si la skill est en anglais.
