---
name: composants
description: "Quand il faut un composant d'interface tout fait à intégrer : bouton, loader, carte, formulaire, fond ou texte animé (KokonutUI, Uiverse), graphique ou tableau de bord React (Bklit UI)."
metadata:
  triggers: >-
    « kokonut » « kokonutui » « composant animé » « composants tout faits » « composants tout fait »
    « bibliothèque de composants » « fond animé » « texte animé » « interface de chat IA » « uiverse »
    « un joli bouton pour mon site » « un bouton stylé » « un loader pour mon site / ma boutique » « un spinner »
    « un interrupteur stylé » « une case à cocher stylée » « une carte produit stylée »
    « une barre de recherche stylée » « un formulaire de connexion stylé » « une infobulle » « un motif de fond »
    « bklit-ui » « installe bklit » « graphique bklit » « graphiques bklit » « ajoute un graphique » « graphique animé »
    « fais un dashboard » « carte KPI » « mini-courbe » « camembert » « ajoute une jauge » « carte de chaleur »
    « design des graphiques » « remplace recharts » « barres arrondies » Ne pas utiliser pour « graphique Excel »
    « composants électroniques » « composants du PC »
---

# Composants — l'aiguillage vers la bonne fiche

Dossier de cette skill : `${CLAUDE_SKILL_DIR}` (le « Base directory » donné au chargement). Lire **seulement** la fiche
du besoin, puis la suivre ; ses chemins (`references/`, `scripts/`) partent du dossier de la fiche. Chaque fiche garde
la source et la licence de son outil (fichier `LICENSE` à côté quand il y en a un).

| Besoin | Fiche | D'après |
|---|---|---|
| Composant React animé tout fait (boutons, textes, fonds et héros, cartes, saisie, navigation, blocs d'interface IA), copié en source par shadcn | [kokonutui](kokonutui/fiche.md) | KokonutUI de kokonut-labs, MIT |
| Élément HTML + CSS ou Tailwind pour n'importe quel site, thème Shopify compris : bouton, loader, interrupteur, case, carte, champ, formulaire, infobulle, motif de fond | [uiverse](uiverse/fiche.md) | Galaxy d'Uiverse.io, MIT ; script `uiverse/scripts/galaxy.py` |
| Graphique React animé, tableau de bord, carte KPI, migration depuis Recharts | [bklit-ui](bklit-ui/fiche.md) | skills de Bklit UI, MIT |

Ailleurs : direction artistique ou finition d'ensemble → `cerveau:design` ; régler le mouvement d'un élément →
`cerveau:animation` ; un graphique dans un document ou un tableur : pas ici.
