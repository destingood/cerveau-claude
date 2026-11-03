---
name: animejs
description: "Animer un site en JavaScript avec anime.js v4 (Julian Garnier, github.com/juliangarnier/anime, licence MIT) : animations et timelines, cascades, déclenchement ou synchronisation au scroll, tracés SVG qui se dessinent, morphing, déplacement sur un chemin, texte découpé en lignes, mots ou lettres, texte brouillé, éléments à glisser, transitions de mise en page, ressorts, objets Three.js. L'ajoute au projet (npm, ou fichier hébergé pour un thème Shopify) avec la syntaxe v4 vérifiée et le passage depuis la v3 ; le style se décide avant (cerveau:taste-skill pour un site, cerveau:emil-kowalski pour un composant), le réglage fin avec cerveau:motion-design. À utiliser quand l'utilisateur cite anime.js ou dit « timeline d'animation », « enchaîne les animations », « animation en cascade », « dessine le tracé svg », « morphing svg », « texte lettre par lettre », « texte brouillé », « élément à glisser », « animation synchronisée au scroll ». Ne pas utiliser pour une vidéo ni pour une animation Lottie."
---

# anime.js v4 — animer un site en JavaScript

Le plugin apporte la méthode et la syntaxe v4 (vérifiée sur la 4.5.0) ; la librairie s'ajoute au projet qui en a
besoin, rien à installer sur le PC. Avant le code, le style se décide avec `cerveau:taste-skill` pour un site,
`cerveau:emil-kowalski` pour un composant ; durées et courbes fines : `cerveau:motion-design`.

## 1. Le bon outil ?
- Survol, fondu, apparition simple : CSS (`transition`, `@keyframes`), sans librairie.
- Le projet anime déjà avec Motion (framer-motion) ou GSAP : rester dessus, jamais deux moteurs.
- anime.js : séquences, cascades, SVG, texte découpé, scroll synchronisé, glisser… sur tout site (HTML, Shopify,
  React, Vue), sans dépendance. Fichier complet ≈ 119 Ko (≈ 41 Ko compressé) ; avec un bundler, seul ce qui est
  importé part en production.

## 2. Ajouter au projet (code tiers : l'utilisateur donne son accord)
1. Déjà là ? `animejs` dans `package.json` (`npm ls animejs`) ou un `anime*.js` dans `assets/` : garder sa version
   et sa syntaxe (v3 ou v4, section 3).
2. Avec un bundler (Vite, Next.js…) : `npm i animejs`, puis `import { animate, stagger } from 'animejs';`.
3. Sans bundler, dont un thème Shopify : copier `dist/bundles/anime.esm.min.js` du paquet (dans
   `node_modules/animejs/` après `npm i animejs`, au besoin dans un dossier temporaire) vers `assets/`, puis dans le
   `.liquid` de la section :
   ```liquid
   <script type="module">
     import { animate, stagger } from "{{ 'anime.esm.min.js' | asset_url }}";
     // animations de la section
   </script>
   ```
   Pas dans `{% javascript %}` : le Liquid n'y est pas rendu et ce n'est pas un module. Plusieurs sections peuvent
   l'importer : même adresse, un seul téléchargement. Script classique : `anime.umd.min.js` expose la globale
   `anime` (`const { animate } = anime;`).
4. Prototype seulement : `https://cdn.jsdelivr.net/npm/animejs@4.5.0/dist/bundles/anime.esm.min.js` (version
   figée) ; en production, le fichier hébergé, pour que l'affichage ne dépende pas d'un tiers.
5. La 5.0 en bêta sur npm (`5.0.0-beta.x`) : seulement si l'utilisateur la demande.

Mise à jour : lire les notes de version (github.com/juliangarnier/anime/releases), puis `npm i animejs@latest` ou
remplacer le fichier d'`assets/`, et retester. Retrait : `npm rm animejs` (ou supprimer le fichier) et ses imports.

## 3. Syntaxe v4 (les exemples en ligne sont souvent en v3)
| v3 | v4 |
|---|---|
| `anime({ targets: '.a', translateX: 250 })` | `animate('.a', { x: 250 })` (`x` `y` `z` = translate) |
| `easing: 'easeOutQuad'` | `ease: 'outQuad'` |
| `value:` dans l'objet d'une propriété | `to:` (et `from:`) |
| `direction: 'reverse'` / `'alternate'` | `reversed: true` / `alternate: true` |
| `endDelay` | `loopDelay` |
| `loop: 3` = 3 passages | `loop: 3` = 3 répétitions, soit 4 passages ; `loop: true` = sans fin |
| `round: 1` | `modifier: utils.round(0)` |
| `anime.timeline({…})` puis `.add({ targets, … }, décalage)` | `createTimeline({ defaults: {…} })` puis `.add(cible, params, position)` |
| `begin` `update` `complete` `change` | `onBegin` `onUpdate` `onComplete` `onRender` |
| `loopBegin` `loopComplete` | `onLoop` |
| `.finished.then()` | `.then()` |
| `anime.path()` / `anime.setDashoffset` | `svg.createMotionPath()` / `svg.createDrawable()` + `draw` |
| `anime.stagger` `anime.set` `anime.random` `anime.remove` | `stagger`, `utils.set` `utils.random` `utils.remove` |
| `easing: 'spring(1, 80, 10, 0)'` | `ease: spring({ mass: 1, stiffness: 80, damping: 10, velocity: 0 })` |
| `anime.suspendWhenDocumentHidden` | `engine.pauseOnDocumentHidden` |

Depuis la 4.4 : ordre des transformations fixe (perspective, translate, rotate, scale, skew) quel que soit l'ordre
d'écriture — pour tourner puis déplacer, imbriquer deux éléments ; `matrix` ne s'anime pas ; valeur par fonction
`(cible, index, cibles)` : le 3e argument est le tableau des cibles (`cibles.length` pour leur nombre).

## 4. Les briques (tout s'importe de 'animejs')
```js
import { animate, createTimeline, createAnimatable, createDraggable, createLayout, createScope,
         onScroll, stagger, splitText, scrambleText, spring, svg, utils, waapi } from 'animejs';

// Animation : cible = sélecteur CSS, élément(s) ou objet JS. Défauts : 1000 ms, ease 'out(2)', autoplay true.
const anim = animate('.carte', {
  y: { from: 40 }, opacity: { from: 0 },   // depuis 40 px et 0 jusqu'à l'état actuel ; [de, à] marche aussi
  duration: 600, ease: 'outCubic', delay: stagger(80),
});
// anim.play() .pause() .resume() .reverse() .restart() .seek(ms) .complete() .revert() ; anim.then(() => …)

// Timeline : position = ms, '+=200', '-=200', '<' (fin de la précédente), '<<' (son début), '<<+=100', label
createTimeline({ defaults: { duration: 500, ease: 'outQuad' } })
  .add('.titre', { opacity: { from: 0 }, y: { from: 20 } })
  .add('.sous-titre', { opacity: { from: 0 } }, '-=250')
  .add('.bouton', { scale: { from: 0.9 }, opacity: { from: 0 } }, '<<+=100');

// Cascade en grille depuis le centre ; from : 'first' 'center' 'last' 'random' ou un index
animate('.grille .case', { scale: { from: 0 }, delay: stagger(40, { grid: [8, 5], from: 'center' }) });

// Scroll : joue une fois à l'entrée dans l'écran (pause s'il ressort avant la fin) ; onScroll({ sync: 'restart' })
// rejoue à chaque entrée ; sync: true lie la progression au défilement (entrée par le bas → sortie par le haut)
animate('.bloc', { y: { from: 60 }, opacity: { from: 0 }, autoplay: onScroll() });
animate('.barre', { scaleX: { from: 0 }, ease: 'linear', autoplay: onScroll({ sync: true }) });

// SVG : tracé qui se dessine, morphing (d pour <path>, points pour <polygon>), objet qui suit un chemin
animate(svg.createDrawable('.trace'), { draw: ['0 0', '0 1'], duration: 1500, ease: 'inOutQuad' });
animate('#forme-a', { d: svg.morphTo('#forme-b'), duration: 800 });
animate('.point', { ...svg.createMotionPath('#chemin'), duration: 4000, ease: 'linear', loop: true });

// Texte : lignes, mots ou lettres (copie lisible par les lecteurs d'écran par défaut) ; texte brouillé
const { chars } = splitText('h1', { chars: true });
animate(chars, { y: { from: '100%' }, opacity: { from: 0 }, delay: stagger(25) });
animate('.code', { innerHTML: scrambleText() });

// Suivre la souris sans recréer d'animation (durée en ms par propriété) ; élément à glisser avec rebond
const suiveur = createAnimatable('.suiveur', { x: 400, y: 400, ease: 'out(3)' });
addEventListener('pointermove', e => { suiveur.x(e.clientX); suiveur.y(e.clientY); });
createDraggable('.curseur', { container: '.piste', y: false, snap: 40, releaseEase: spring({ bounce: 0.3 }) });

// Mise en page : changer le DOM dans update(), anime.js anime de l'ancienne disposition à la nouvelle
createLayout('.liste').update(() => liste.prepend(nouvel), { duration: 400 });

// Web Animations API du navigateur : même syntaxe, plus léger, pour transform et opacity
waapi.animate('.bouton', { scale: 1.05, duration: 200, alternate: true, loop: 1 });
```
- Courbes : `'linear'`, `'in(2)'` `'out(3)'` `'inOut(2)'`, `'outQuad'` `'inOutCubic'` `'outExpo'`, `'outBack(1.7)'`,
  `'outElastic(1, .3)'`, `cubicBezier(.2, 0, 0, 1)`, `steps(5)`, `spring({ bounce: .3, duration: 500 })` (fonctions
  importées de 'animejs' ; `createSpring` est déprécié). Un ressort remplace le `duration` de l'animation : ici 500 ms
  perçues, mais 1080 ms jusqu'à l'arrêt, à compter dans une timeline.
- Outils : `utils.set(cible, { opacity: 0 })` (sans animer), `utils.get(el, 'x')`, `utils.remove(cible)` (arrête
  ses animations), `utils.random(0, 100)`, `utils.clamp`, `utils.mapRange`, `utils.lerp`.
- Three.js 0.150 ou plus : `import 'animejs/adapters/three';` une fois, puis `animate(mesh, { x: 2, rotateY: Math.PI })`.
- Un paramètre douteux se vérifie dans les types de la version installée
  (`node_modules/animejs/dist/modules/types/index.d.ts`), puis dans la doc https://animejs.com/documentation/ ;
  jamais de mémoire ni d'après un exemple v3.

## Règles
- Toujours un mode mouvement réduit : `createScope` avec `mediaQueries` (ci-dessous) ; en mode réduit, état final
  directement, sans déplacement ni boucle.
- Ce qui bouge seul plus de 5 secondes a un bouton pause (`anim.pause()` / `anim.play()`) : WCAG 2.2, critère 2.2.2,
  niveau A.
- Contenu lisible sans JavaScript : l'état de départ caché vient de l'animation (`from`, `utils.set`), jamais du
  CSS seul.
- Animer `x`, `y`, `scale`, `rotate`, `opacity` ; jamais `width`, `height`, `top`, `left` ni `margin` en continu.
  Lettres une par une : titres courts ; un paragraphe se découpe en lignes ou en mots.
- Nettoyer au démontage, sinon animations et écouteurs de scroll restent actifs : React, `return () => scope.revert()`
  dans le `useEffect` ; thème Shopify, sur l'évènement `shopify:section:unload` de la section.
- Tester dans le navigateur, panneau visible (onglet caché : ni requestAnimationFrame ni évènement scroll ; à défaut,
  `cerveau:playwright` en headless) ; pour la capture d'un état précis, `seek(ms)` ou `complete()` ; zéro erreur
  console.

```js
const scope = createScope({ root: '.hero', mediaQueries: { reduit: '(prefers-reduced-motion: reduce)' } })
  .add(self => {
    if (self.matches.reduit) return;                               // mouvement réduit : rien ne bouge
    animate('.titre', { opacity: { from: 0 }, y: { from: 30 } });  // cherché dans .hero seulement
  });
// scope.revert() annule tout ce qui a été créé dans le scope
```
