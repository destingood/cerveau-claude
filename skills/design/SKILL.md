---
name: design
description: "Design d'un site ou d'une appli : direction artistique, critique et finition d'interface, style d'une marque connue (DESIGN.md), design relevé sur un site, capture ou maquette transformée en vrai site. Pas pour un logo ni une animation seule."
metadata:
  triggers: >-
    « direction artistique » « refais le design » « refais ma landing page » « design pro » « design premium »
    « style Awwwards » « ça fait template » « rends mon site plus beau » « taste skill » « taste-skill »
    « installe impeccable » « utilise impeccable » « lance impeccable » « skill impeccable » « peaufine l'interface »
    « peaufiner le design » « critique l'interface » « ça fait généré par IA » « interface trop chargée »
    « revue de mon interface » « vérifie l'accessibilité » « DESIGN.md » « design-md » « design system »
    « système de design » « charte graphique » « dans le style de Stripe » « comme le site d'Apple »
    « inspiré de Notion » « getdesign » « awesome-design-md » « skillui » « extrais le design de ce site »
    « récupère le design de » « mêmes couleurs et polices que ce site » « tokens de design »
    « dans le style de ce site » « image-to-code » « image en code » « maquette en code » « code cette maquette »
    « transforme cette image en site » « reproduis cette maquette » « capture d'écran en site »
    « génère la maquette puis code » « design depuis une image » Ne pas utiliser pour « logo design »
    « animation commerciale »
---

# Design — l'aiguillage vers la bonne fiche

Dossier de cette skill : `${CLAUDE_SKILL_DIR}` (le « Base directory » donné au chargement). Lire **seulement** la fiche
du besoin, puis la suivre ; ses chemins (`references/`, `scripts/`) partent du dossier de la fiche. Chaque fiche garde
la source et la licence de son outil (fichier `LICENSE` à côté quand il y en a un).

| Besoin | Fiche | D'après |
|---|---|---|
| Direction artistique d'un site entier, landing page à refaire, site qui « fait template », design premium (trois directions, typo, palette, sections, contrôle sur captures) | [taste-skill](taste-skill/fiche.md) | taste-skill de Leonxlnx, MIT |
| Critiquer, peaufiner ou auditer une interface (accessibilité, performance, téléphone), « ça fait généré par IA », interface trop chargée | [impeccable](impeccable/fiche.md) | Impeccable de Paul Bakaus, Apache-2.0 |
| Système de design d'une marque connue (Stripe, Apple, Notion…), un DESIGN.md à poser ou à suivre | [design-md](design-md/fiche.md) | getdesign / awesome-design-md de VoltAgent, MIT |
| Relever le design d'un site, d'un dépôt ou d'un projet (couleurs, polices, espacements, tokens, captures) | [skillui](skillui/fiche.md) | SkillUI d'amaancoderx, MIT |
| Transformer une capture d'écran, une maquette ou une image en vrai site responsive | [image-to-code](image-to-code/fiche.md) | d'après image-to-code-skill de Leonxlnx, MIT |

Ailleurs : une animation précise, un bouton qui bouge ou tout un site animé → `cerveau:animation` ; un composant tout
fait (bouton, loader, graphique) → `cerveau:composants` ; un logo → `cerveau:logo-design` ; refaire les fonctions d'une
app existante → `cerveau:replica`.
