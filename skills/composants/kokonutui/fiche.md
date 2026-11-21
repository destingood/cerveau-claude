---
name: kokonutui
description: "KokonutUI (github.com/kokonut-labs/kokonutui, licence MIT) : 102 composants React gratuits, chacun avec son animation (Tailwind CSS, Motion), copiés en source dans le projet par le registre shadcn @kokonutui puis accordés au thème du site — boutons, textes, fonds et héros, cartes, saisie, navigation, médias, 18 blocs d'interface IA (zone de prompt, choix du modèle). Trouve le bon composant, l'ajoute, l'adapte et le vérifie au navigateur ; charge la skill officielle si elle est installée, sinon l'installe avec accord ou la lit une fois. À utiliser quand l'utilisateur dit « kokonut », « composant animé », « composants tout fait », « bibliothèque de composants », « fond animé », « texte animé », « interface de chat IA », ou veut un héros, un bouton ou une section qui en jette sans tout coder. Ne pas utiliser hors React (« thème Shopify », HTML pur), pour un graphique (cerveau:bklit-ui), pour régler une animation existante (cerveau:motion-design) ni pour la direction artistique (cerveau:taste-skill)."
---

# KokonutUI

Composants gratuits (MIT) de kokonut-labs : la commande shadcn copie leur code source dans le projet, qu'on adapte ensuite comme du code maison. Registre lu le 03/11/2026 (dépôt au commit 4d497b7 du 31/10/2026) ; essai fait sous Windows avec Vite, React 19, Tailwind v4 et shadcn 4.23.

## 1. Déjà là ?
`~/.claude/skills/install-kokonutui-component/SKILL.md` existe → charger la skill `install-kokonutui-component` et la suivre, avec les règles ci-dessous (elles priment). Sinon, installer (2), ou pour une seule tâche la lire sans l'installer :
https://kokonutui.com/.well-known/agent-skills/install-component/SKILL.md

## 2. Installer (code tiers : l'utilisateur donne son accord, ou lance lui-même la commande)
1. Node.js (`node --version`).
2. Pour tous les projets, en copie (plus sûr sous Windows), télémétrie coupée :
   - PowerShell : `$env:DO_NOT_TRACK=1; npx -y skills add https://kokonutui.com -g -a claude-code -y --copy`
   - Bash : `DO_NOT_TRACK=1 npx -y skills add https://kokonutui.com -g -a claude-code -y --copy`
   Résultat : `~/.claude/skills/install-kokonutui-component`, commande `/install-kokonutui-component`.
3. Déclencheurs en français : `brain skill trig install-kokonutui-component "kokonut" "composant animé" "composants tout fait" "bibliothèque de composants" "fond animé" "texte animé" "interface de chat IA"`, puis nouvelle conversation.
Mise à jour : `npx -y skills update -g`. Retrait : `npx -y skills remove install-kokonutui-component -g -a claude-code -y`, puis `brain skill --force trig install-kokonutui-component`.

## 3. Dans le projet
1. Prérequis : React 19, Tailwind v4 et shadcn initialisé (`components.json`). Projet neuf : `npx shadcn@latest init -t vite -b radix -p nova -n <nom> --no-monorepo -y` (`-t next` pour Next.js).
2. Choisir dans le catalogue (4) et lire la fiche du composant (props, exemple) : `https://kokonutui.com/docs/<dossier>/<nom>.md`, dossier indiqué pour chaque catégorie.
3. Ajouter : `npx shadcn@latest add @kokonutui/<nom> -y` (plusieurs à la suite possible). Le code arrive dans `components/kokonutui/` avec ses dépendances (motion, lucide-react, primitives shadcn) ; rien à déclarer, la commande inscrit le registre dans `components.json`.
4. Adapter dans le fichier copié : textes, couleurs, tailles, durées.
5. Vérifier : `npm run build`, puis au navigateur ouvrir chaque menu, cliquer chaque bouton, console sans erreur, rendu en mouvement réduit.

## 4. Catalogue gratuit : 102 composants (registre du 31/10/2026)
- **Boutons (16)** : dossier buttons — `attract-button`, `bell-button`, `cart-button`, `command-button`, `gradient-button`, `hold-button`, `morph-popover`, `particle-button`, `pull-cord`, `save-button`, `slide-text-button`, `slide-to-confirm`, `switch-button`, `tear-button`, `undo-button`, `v0-button`
- **Textes (10)** : dossier texts — `cradle-text`, `dynamic-text`, `glitch-text`, `marker-text`, `plucked-text`, `shadow-text`, `split-flap-text`, `spoiler-text`, `swoosh-text`, `type-writer`
- **Fonds et héros (10)** : dossier backgrounds — `background-paths`, `caustics-background`, `dot-field`, `drape-background`, `flow-field`, `halftone-background`, `ink-background`, `rain-glass-background`, `shape-hero`, `topo-background`
- **Cartes (17)** : dossier cards — `activity-terrain`, `apple-activity-card`, `bento-grid`, `boarding-pass`, `card-flip`, `card-stack`, `carousel-cards`, `currency-transfer`, `lightbox-grid`, `liquid-gauge`, `liquid-glass-card`, `metric-card`, `notification-stack`, `page-flip`, `receipt-printer`, `spending-ring`, `uptime-card`
- **Saisie (16)** : dossier inputs — `amount-pad`, `avatar-picker`, `card-field`, `detent-dial`, `file-upload`, `liquid-slider`, `loader`, `location-picker`, `seat-map`, `signature-pad`, `slot-picker`, `stay-picker`, `team-selector`, `timezone-planner`, `tip-selector`, `wheel-picker`
- **Navigation (10)** : dossier navigation — `action-search-bar`, `marking-menu`, `morphic-navbar`, `profile-dropdown`, `scroll-index`, `smooth-drawer`, `smooth-tab`, `stack-panel`, `status-island`, `toolbar`
- **Médias (5)** : dossier media — `clip-trimmer`, `contact-sheet`, `focal-point-picker`, `photo-straighten`, `synced-transcript`
- **IA (18)** : dossier ai — `ai-agent-lanes`, `ai-autocomplete`, `ai-branches`, `ai-citations`, `ai-context-meter`, `ai-diff-review`, `ai-inline-edit`, `ai-input-search`, `ai-loading`, `ai-memory`, `ai-message-queue`, `ai-model-selector`, `ai-prompt`, `ai-redact`, `ai-text-loading`, `ai-token-alternatives`, `ai-tool-approval`, `ai-voice`

Pour une landing ou une boutique : héros `shape-hero`, `background-paths`, `rain-glass-background` ; titres `dynamic-text`, `type-writer`, `marker-text`, `swoosh-text` ; appel à l'action `particle-button`, `gradient-button`, `attract-button`, `slide-text-button`, `cart-button` ; sections `bento-grid`, `card-stack`, `carousel-cards`, `lightbox-grid` ; navigation `morphic-navbar`, `smooth-tab`, `action-search-bar`.
Liste à jour : https://kokonutui.com/r/registry.json ; une ligne par composant (nom, effet, fiche, commande) : https://kokonutui.com/r/llms.txt, à fouiller par mot (`shadcn search` est trop flou).

## Règles
- Gratuit seulement : un composant marqué « Part of Kokonut UI Pro » est payant (le registre répond 404 même si llms.txt affiche sa commande) ; proposer le plus proche du catalogue gratuit.
- Thème Shopify (Liquid) ou HTML pur : pas de React, donc rien à copier ; prendre un élément HTML + CSS de cerveau:uiverse, ou reproduire l'effet en CSS avec cerveau:emil-kowalski.
- Partir du composant au lieu de recoder l'effet, et ne garder que ceux qui servent la page.
- Mouvement réduit : `useReducedMotion()` vaut null côté serveur, ne changer le rendu qu'après le montage ; ce qui bouge seul plus de 5 s (fond, texte en boucle) doit pouvoir s'arrêter (WCAG 2.2.2).
- Tailwind v4 : `scale-*`, `translate-*` et `rotate-*` sont des propriétés CSS à part, donc `transition-transform` et non `transition-[transform]`.
- Thème : vérifier que les variables utilisées (`--card`, `--muted`…) existent dans le CSS du projet, sinon les fonds restent transparents.
- Base UI (`components.json` : style `base-nova`) : la commande convertit le code écrit pour Radix, mais un `DropdownMenuLabel` hors de `DropdownMenuGroup` fait planter le menu au clic (« Base UI error #31 », vu avec `ai-prompt`) ; l'entourer de `DropdownMenuGroup`, ou créer le projet avec `-b radix`.
- Régler le mouvement : cerveau:motion-design ; direction artistique du site entier : cerveau:taste-skill ; graphiques : cerveau:bklit-ui ; finition et revue des animations : cerveau:emil-kowalski.
- Répondre dans la langue de l'utilisateur.
