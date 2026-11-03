---
name: uiverse
description: "Trouver et intégrer un élément d'interface de Galaxy d'Uiverse.io (github.com/uiverse-io/galaxy, licence MIT) : 3 802 boutons, cartes, loaders, interrupteurs, cases à cocher, champs, formulaires, infobulles et motifs de fond en HTML + CSS ou Tailwind, cherchés en local, comparés en aperçu, puis adaptés au site (classes préfixées, couleurs du site, accessibilité, crédit gardé). Vérifie qu'elle est là, sinon l'installe avec l'accord de l'utilisateur. À utiliser quand l'utilisateur dit « un joli bouton pour mon site », « un bouton stylé », « un loader pour mon site », « un spinner », « un interrupteur stylé », « une case à cocher stylée », « une carte produit stylée », « une barre de recherche stylée », « un formulaire de connexion stylé », « une infobulle », « un motif de fond ». Ne pas utiliser pour la direction artistique d'un site entier, animer un élément existant (cerveau:emil-kowalski ou cerveau:motion-design), reproduire une maquette (cerveau:image-to-code) ni pour un logo (cerveau:logo-design)."
---

# Uiverse — un élément d'interface tout fait (collection Galaxy), fondu dans le site

Script `galaxy.py`, Python standard (3.8 ou plus), rien à installer avec pip. Il est dans `scripts/` du dossier de
cette skill (« Base directory » au chargement) : le lancer par ce chemin complet, `python` sous Windows, `python3`
ailleurs — `python "<dossier de la skill>/scripts/galaxy.py" search loader --css`. Collection : `~/.claude/galaxy`
(autre dossier : variable `GALAXY_DIR`).

## 1. Déjà là ?
`galaxy.py search` sans mot affiche le sommaire par catégorie. « Galaxy absente » → installer (2).

## 2. Installer (contenu tiers : l'utilisateur donne son accord, ou lance lui-même la commande)
- `galaxy.py install` clone le dépôt (`git clone --depth 1`) dans `~/.claude/galaxy` : ≈ 21 Mo, Git suffit. Que du
  HTML et du CSS, aucun script dans la collection (vérifié au commit adbd2ad) : rien n'est exécuté.
- Mise à jour : la même commande (`git pull`). Le dépôt est figé depuis le 02/09/2024 ; uiverse.io en a davantage en
  ligne.
- Retrait : supprimer le dossier — PowerShell : `Remove-Item -Recurse -Force "$HOME\.claude\galaxy"`.

## 3. Chercher
1. Regarder d'abord le site : techno (HTML/CSS, React/Next, Vue, Svelte, Shopify…), Tailwind ou non, couleurs, police,
   fond clair ou sombre. Site sans Tailwind → `--css`.
2. `galaxy.py search <mots> [--cat C] [--css | --tailwind] [-n 12]`. Les tags sont en anglais : traduire la demande
   (« néon » → neon, « dégradé » → gradient, « verre » → glassmorphism, « réseaux sociaux » → social, « connexion » →
   login, « envoi de fichier » → upload). Les plus complets d'abord, puis les plus légers ; « [1/2 mots] » = trouvé
   en partie.
3. Catégories (`--cat` : le début du nom suffit, `but`, `load`, `tog`…), total (CSS / Tailwind) :

| Catégorie | Contenu | Éléments |
|---|---|---|
| Buttons | boutons | 1 231 (1 082 / 149) |
| Cards | cartes (produit, profil, prix…) | 726 (602 / 124) |
| loaders | chargements, spinners | 718 (697 / 21) |
| Toggle-switches | interrupteurs | 260 (241 / 19) |
| Inputs | champs, barres de recherche | 226 (190 / 36) |
| Forms | formulaires (connexion, contact…) | 180 (129 / 51) |
| Checkboxes | cases à cocher | 171 (157 / 14) |
| Patterns | motifs de fond | 103 (103 / 0) |
| Radio-buttons | boutons radio, sélecteurs | 102 (96 / 6) |
| Tooltips | infobulles | 62 (49 / 13) |
| Notifications | alertes, toasts | 23 (23 / 0) |

## 4. Comparer
1. `galaxy.py preview ID… [--sombre] --out "<dossier temporaire de la session>/galaxy-apercu.html"` — 3 à 9
   candidats, `--sombre` si le site est sombre (sans `--out` : dossier temporaire du système). Écrit la page HTML,
   interactive, et sa capture PNG (Chrome ou Edge sans fenêtre, ≈ 3 s).
2. Lire la capture et écarter ce qui jure avec le site. Elle ne montre ni le survol ni le mouvement : les animations y
   sont avancées de 0,6 s, toutes en phase. Carte vide → élément clair sur fond clair (relancer avec `--sombre`) ou
   visible seulement au survol (lire son code avec `show`).
3. Montrer 3 à 6 candidats : la capture (envoyée comme fichier si possible), l'ID, le lien `https://uiverse.io/<ID>`
   (original interactif), une ligne chacun. Attendre le choix, sauf si l'utilisateur a dit de choisir pour lui.

Chaque élément tourne dans un cadre isolé (iframe `sandbox`) ; ceux en Tailwind chargent le CDN officiel
(cdn.tailwindcss.com) et aucun autre script.

## 5. Intégrer
1. `galaxy.py show ID` : code complet, précédé de lignes ⚠ (sélecteurs globaux, ressource chargée d'ailleurs, liens
   d'exemple, JavaScript). Au-delà de 25 Ko, il refuse sans `--full` : préférer un élément plus léger.
2. Adapter sans changer l'effet choisi :
   - préfixer toutes les classes et les `@keyframes` (préfixe du projet, sinon `gx-`) ; sélecteurs `html`, `body`,
     `:root`, `*` ramenés sur le conteneur du composant ;
   - couleurs, police, rayons et tailles → variables du site ; textes en français ; liens et images d'exemple
     remplacés ; une image servie par uiverse.io est copiée dans le site ;
   - accessibilité : vrai `<button>` ou `<a>`, focus visible (`:focus-visible`), contraste ≥ 4,5:1, `<label>` relié à
     chaque champ, loader avec `role="status"` et un texte pour lecteur d'écran, animations coupées sous
     `@media (prefers-reduced-motion: reduce)`.
3. Où le mettre :
   - HTML/CSS : le HTML dans la page, le CSS dans la feuille du site ;
   - React / Next : `className`, `htmlFor`, attributs SVG en camelCase (`strokeWidth`…), balises fermées (`<input />`),
     `style` en objet, commentaires `<!-- -->` → `{/* */}` ; CSS en module (`.module.css`) ou feuille globale ;
   - Vue / Svelte : dans le composant, `<style scoped>` (Vue) ou `<style>` (Svelte, isolé par défaut) ;
   - Tailwind : classes de la v3 ; sur un site en v4, vérifier le rendu (tailwindcss.com/docs/upgrade-guide) ;
   - Shopify : `snippets/<nom>.liquid` et `assets/<nom>.css` (ou `{% stylesheet %}` dans la section), textes et
     couleurs en réglages de section.
4. Crédit : la licence MIT permet tout usage et Uiverse.io dit l'attribution facultative mais appréciée : garder le
   commentaire « From Uiverse.io by <auteur> ».
5. Vérifier dans le site : survol, focus au clavier, clic, état désactivé, mobile à 375 px, clair et sombre si le
   site a les deux.

## Règles
- Ne jamais lister ni lire la collection à la main (3 802 fichiers) : `search`, puis `show` sur 1 à 3 éléments ;
  `--full` seulement si l'utilisateur tient à un gros élément.
- Galaxy fournit des pièces, pas une direction artistique : un seul style par page (mêmes rayons, ombres et durées que
  le reste du site). Direction d'ensemble : skills design-taste-frontend ou impeccable si elles sont installées ;
  animer l'élément → cerveau:emil-kowalski, régler finement durées et courbes → cerveau:motion-design ; maquette à
  reproduire → cerveau:image-to-code.
- Ne jamais annoncer un rendu qui n'a pas été regardé.
