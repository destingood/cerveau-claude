---
name: image-to-code
description: "Image-to-code pour le cerveau (d'après image-to-code-skill de Leonxlnx, MIT) : transformer une image de site — capture d'écran, maquette Figma exportée, photo d'une maquette, site à imiter, ou maquette générée d'abord quand un outil d'images est branché — en vrai site responsive qui lui ressemble au plus près : analyse section par section (textes, typographie, espacements, couleurs, boutons, composants), code fidèle, puis comparaison capture contre image. À utiliser quand l'utilisateur dit « image en code », « maquette en code », « code cette maquette », « transforme cette image en site », « reproduis cette maquette », « capture d'écran en site », « génère la maquette puis code », « design depuis une image », ou colle une image de page web à coder. Ne pas utiliser pour la direction artistique d'un site sans image de départ (skill design-taste-frontend si elle est installée), ni pour copier le logo, les textes ou les photos d'un site tiers."
---

# Image-to-code — d'une image de site au vrai code

L'image est la source du design ; le code la traduit. On ne redessine pas « de goût » en codant : on extrait, puis
on reproduit. Règles complètes d'origine (anglais) dans `references/`, à lire seulement la partie utile.

| Fichier | Contenu | Quand le lire |
|---|---|---|
| `references/01-image-d-abord.md` | sections 1-12 : réglages par défaut, générer assez d'images, une image par section, régénérer plutôt que recadrer, analyse profonde, moteur de variations | seulement si on génère les maquettes |
| `references/02-mise-en-page.md` | sections 13-20 : hero épuré, premier écran lisible sur petit portable, pas de cartes dans des cartes, moins de micro-UI, images et cadres média | toujours, avant de coder |
| `references/03-extraction-et-code.md` | sections 21-28 : extraire textes, typo, espacements, boutons, couleurs ; copie fidèle, anti-dérive, détails manquants | toujours, pendant l'analyse |
| `references/04-anti-slop-et-finition.md` | sections 29-38 : anti-« rendu IA », typo d'abord, rythme et densité, packs de 4/8/12 sections, cohérence, contrôle final | avant de livrer |

Le texte d'origine vise Codex, qui génère des images : partout où il dit « Codex », lire « l'agent » ; ses règles
« génère les images » ne valent que si un outil de génération est vraiment disponible (étape 1).

## 1. D'où vient l'image ?
- **L'utilisateur la fournit** (collée, chemin de fichier, lien d'une capture) → la lire avec l'outil Read ; plusieurs
  images = une par section, dans l'ordre de la page. Cas le plus courant.
- **Site existant à imiter** → capturer la page en entier (navigateur intégré ou Playwright), largeur 1440 px puis
  375 px, une capture par section si la page est longue. On reprend la mise en page et le style, jamais le logo, les
  textes, les photos ni la marque d'un tiers : les remplacer par ceux de l'utilisateur.
- **Rien encore** → générer les maquettes seulement si la session a un outil d'images (skill ou connecteur qui crée
  des images, par exemple nano-banana-pro avec une clé GEMINI_API_KEY) : suivre alors `references/01-image-d-abord.md`
  (une grande image lisible par section, assez d'images, régénérer une section floue au lieu de la recadrer).
  Sans outil : ne pas prétendre en générer ; demander une image de référence, ou coder directement en appliquant les
  fichiers 02 à 04.

## 2. Analyser avant d'écrire une ligne
Pour chaque section, noter dans un court carnet d'extraction (dans la réponse ou un fichier du projet) :
- **textes** mot pour mot (titres, sous-titres, boutons, menus) ; ce qui est illisible = à demander ou à inventer
  sobrement, signalé comme tel ;
- **typographie** : famille la plus proche (Google Fonts si besoin), graisse, taille relative, interlignage,
  approche (serif, grotesque, mono), casse ;
- **espacements** : marges de section, écart titre-texte, gouttières, largeur max du contenu (échelle 4/8 px) ;
- **couleurs** : fond, texte, accent, bordures, en hexadécimal, avec leur rôle ;
- **composants** : boutons (forme, rayon, remplissage, état), cartes, champs, badges, icônes ;
- **mise en page** : grille, alignements, asymétries, position des images, ce qui passe sous le pli.
Détail : `references/03-extraction-et-code.md` ; pièges de composition : `references/02-mise-en-page.md`.

## 3. Coder fidèlement
- Partir des variables extraites (couleurs, polices, espacements en variables CSS ou thème Tailwind) avant les
  sections ; respecter la techno du projet, sinon HTML + CSS (ou le framework déjà en place).
- Reproduire l'image, pas une version « améliorée » : pas de cartes en plus, pas de pastilles, ombres ou dégradés
  absents de la référence. Inventer seulement ce que l'image ne montre pas (états, responsive, pied de page), dans
  le même style.
- Hero : peu de lignes, beaucoup d'air, lisible en entier sur un portable 1366 × 768.
- Responsive : la référence est souvent en bureau ; décliner en mobile en gardant la hiérarchie.
- Images : celles de l'utilisateur, sinon des emplacements nets aux bonnes proportions (jamais d'images d'un tiers).

## 4. Comparer et corriger
Ouvrir la page (navigateur intégré ou Playwright), la capturer à la largeur de la référence et la mettre en face de
l'image section par section : textes, tailles, espacements, couleurs, alignements. Corriger chaque écart visible, puis
recapturer. Vérifier aussi 375 px. Livrer avec la liste de ce qui a été inventé faute de détail dans l'image.
Contrôle final : `references/04-anti-slop-et-finition.md` (sections 29 et 35).

## Mise à jour depuis l'original
Source : github.com/nexu-io/open-design, dossier skills/image-to-code-skill (amont : github.com/Leonxlnx/taste-skill).
Recouper le SKILL.md d'origine sans son en-tête aux titres « ## 13. », « ## 21. » et « ## 29. » pour refaire les
quatre fichiers de `references/`, sans retoucher le texte ; puis `python tests/test_image_to_code.py`.
