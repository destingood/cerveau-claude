---
name: impeccable
description: "Peaufiner, critiquer ou concevoir l'interface d'un site, d'une landing page, d'un tableau de bord ou d'une appli (web, iOS, Android) avec Impeccable de Paul Bakaus (github.com/pbakaus/impeccable, licence Apache 2.0) : 23 commandes de directeur artistique (critique notée, audit accessibilité et performance, polish, bolder, quieter, distill, harden, typeset, layout, colorize, animate, onboard…), contexte du produit dans PRODUCT.md et DESIGN.md, et un détecteur qui signale après chaque modification d'un fichier d'interface les défauts typiques des interfaces faites par IA (texte en dégradé, halos, contraste, débordements). Vérifie qu'il est là, sinon l'installe sur ce PC avec l'accord de l'utilisateur. À utiliser quand l'utilisateur dit « installe impeccable », « peaufine l'interface », « peaufiner le design », « critique l'interface », « ça fait généré par IA », « interface trop chargée ». Ne pas utiliser pour un logo, une animation seule ni une tâche sans interface."
---

# Impeccable — l'œil d'un directeur artistique sur ton interface

## 1. Déjà là ?
`~/.claude/skills/impeccable/SKILL.md` (ou `.claude/skills/impeccable/` du projet) existe → charger la skill
`impeccable` et la suivre. Elle lance d'abord `scripts/impeccable context` (sous Windows sans `sh` :
`scripts/impeccable.cmd context`), lit `reference/craft-floor.md` avant toute retouche, puis seulement la référence de
la commande demandée. Sinon, installer (2).

## 2. Installer (code tiers : l'utilisateur donne son accord, ou lance lui-même la commande)
1. Node.js (`node --version`), pour l'installeur seulement : le moteur (`impeccable.exe` sous Windows, ≈ 20 Mo) vient
   avec la skill.
2. Copier `~/.claude/settings.json` de côté : l'installeur le réécrit pour y poser ses hooks (fins de ligne, clé
   `description` ajoutée), sans rien retirer.
3. Pour tous les projets, pour Claude Code seul, télémétrie coupée (sans `-y` ni `--providers`, il pose des questions) :
   - PowerShell : `$env:DO_NOT_TRACK=1; npx -y impeccable install -y --providers=claude --global; npx -y impeccable telemetry off`
   - Bash : `DO_NOT_TRACK=1 npx -y impeccable install -y --providers=claude --global && npx -y impeccable telemetry off`
   Résultat : `~/.claude/skills/impeccable` (commande `/impeccable`), 4 agents `~/.claude/agents/impeccable-*.md` et
   3 hooks dans `~/.claude/settings.json` (début de session, après chaque Edit/Write, fin de réponse). Sans hooks :
   ajouter `--no-hooks` ; pour un seul projet : `--scope=project` au lieu de `--global`.
4. Nouvelle conversation. Pas de `brain skill trig impeccable` : les déclencheurs en français sont ceux de
   `cerveau:impeccable`, les recopier ferait des doublons.

Mise à jour : `npx -y impeccable update`. Retrait : supprimer `~/.claude/skills/impeccable`,
`~/.claude/agents/impeccable-*.md` et `~/.impeccable`, puis retirer de `~/.claude/settings.json` les 3 hooks dont la
commande contient `skills\impeccable` et la clé `description` d'Impeccable.

## Règles
- Une fois par projet : `/impeccable init` (questions sur le produit → PRODUCT.md) ; `/impeccable document` tire
  DESIGN.md du code existant. Sans argument, `/impeccable` propose un menu et ne lance rien seul.
- Le brief de l'utilisateur prime sur les goûts de la skill. Une retouche garde l'identité, les textes et tout ce qui
  sort du périmètre ; changer un texte ou ajouter une promesse seulement avec son accord.
- Alertes du détecteur : vrai défaut → le corriger ; faux positif certain → l'exception la plus étroite
  (`/impeccable hooks ignore-value <règle> <valeur> --reason "qui a décidé : preuve"`), signalée dans la réponse ;
  doute → une question d'une ligne. Ignorer une règle ou un fichier entier : seulement sur son « oui ».
- Coût : les hooks ne disent rien hors fichiers d'interface ; une retouche d'interface avec un vrai défaut ajoute
  ≈ 1,6 Ko au contexte. Les couper dans un projet : `/impeccable hooks off`.
- Animation seule → `cerveau:motion-design` ; style d'une marque connue → `cerveau:design-md` ; capture ou maquette à
  coder → `cerveau:image-to-code`.
- Réponses dans la langue de l'utilisateur, même si la skill est en anglais.
