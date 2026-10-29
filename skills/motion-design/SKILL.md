---
name: motion-design
description: "Concevoir ou corriger les animations d'un site ou d'une appli avec Motion Design Skill de LottieFiles (github.com/LottieFiles/motion-design-skill, licence MIT) : durées, courbes d'easing, chorégraphie, principes Disney adaptés à l'interface, états chargement, succès et erreur, mouvement réduit. Marche avec CSS, Framer Motion, GSAP, Lottie ou des ressorts. Vérifie qu'elle est là, sinon l'installe sur ce PC avec l'accord de l'utilisateur, ou la suit une fois sans rien installer. À utiliser quand l'utilisateur dit « motion design », « installe motion design », « ajoute une animation », « anime ce bouton », « anime le logo », « transition de page », « micro-interaction », « effet au scroll », « animation de chargement », « rends le site plus vivant ». Ne pas utiliser pour monter une vidéo, ni pour le design statique (couleurs, typographie, mise en page)."
---

# Motion design — des animations d'interface qui ont une raison d'être

## 1. Déjà là ?
`~/.claude/skills/motion-design/SKILL.md` existe → charger la skill `motion-design` et la suivre ; elle renvoie à
`director/`, `patterns/` et `reference/` : ne lire que le fichier qui sert à la tâche. Sinon, installer (2), ou pour
une seule tâche la lire sans l'installer :
https://raw.githubusercontent.com/LottieFiles/motion-design-skill/main/skills/motion-design/SKILL.md
(17 fichiers Markdown en anglais, sans script ni réseau).

## 2. Installer (code tiers : l'utilisateur donne son accord, ou lance lui-même la commande)
1. Node.js (`node --version`).
2. Pour tous les projets, en copie (plus sûr sous Windows), télémétrie coupée :
   - PowerShell : `$env:DO_NOT_TRACK=1; npx -y skills add LottieFiles/motion-design-skill -g -a claude-code -y --copy`
   - Bash : `DO_NOT_TRACK=1 npx -y skills add LottieFiles/motion-design-skill -g -a claude-code -y --copy`
   Résultat : `~/.claude/skills/motion-design`, commande `/motion-design`.
3. Déclencheurs en français : `brain skill trig motion-design "ajoute une animation" "anime ce bouton" "transition de page"
   "micro-interaction" "effet au scroll" "rends le site plus vivant"`, puis nouvelle conversation.

Mise à jour : `npx -y skills update -g` (réécrit le SKILL.md ; les déclencheurs ajoutés par `brain skill trig`
restent). Retrait : `npx -y skills remove motion-design -g -a claude-code -y`, puis `brain skill --force trig motion-design`.

## Règles
- Avant le code : la liste en 8 points de la skill (émotion visée, personnalité, propriété, durée, easing, élément
  héros, couches, règles du tiers), et une seule personnalité par projet (Playful, Premium, Corporate, Energetic).
  Dire en une ligne laquelle et pourquoi.
- Toujours une version pour `prefers-reduced-motion` : plus de déplacement, fondu court ou rien, aucune boucle
  automatique. Tout ce qui bouge seul plus de 5 secondes se met en pause (WCAG 2.2, critère 2.2.2, niveau A).
- Web : animer `transform` et `opacity` ; jamais `width`, `height`, `top`, `left` ni `margin` en continu ; moins de
  20 éléments animés à l'écran ; `will-change` avec parcimonie.
- La règle « toujours trois couches » (principale, secondaire, ambiante) vaut pour une scène (en-tête, illustration,
  Lottie). Pour un bouton, un formulaire ou une page de paiement, le seuil de simplicité de la skill prime : une ou
  deux propriétés, pas d'ambiance qui distrait de l'achat.
- La skill donne des principes, pas de fichier : un `.json` ou `.lottie` se crée dans un outil d'animation (ou
  se reprend d'une bibliothèque sous licence) ; ici, on l'intègre et on règle son mouvement.
- Durées en millisecondes ; réponses dans la langue de l'utilisateur, même si la skill est en anglais.
