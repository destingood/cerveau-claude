---
name: obsidian
description: "Syntaxe Obsidian pour le wiki du cerveau : propriétés (frontmatter), liens [[…]], intégrations ![[…]], encadrés (callouts, dont [!contradiction]), surlignage, commentaires, références de bloc, maths, Mermaid ; fichiers Bases (.base : filtres, formules, vues table, cartes, liste, kanban) et Canvas (.canvas, JSON Canvas 1.0 : cartes, groupes, flèches, couleurs). À utiliser quand l'utilisateur demande « fais une base », « ajoute une vue au tableau de bord », « un kanban dans Obsidian », « fais un canvas », « carte visuelle », « un encadré », « comment on écrit … dans Obsidian », « intègre cette page », « corrige les propriétés », ou pour vérifier une page avant de l'écrire. Pas pour ingérer une source (brain wiki add), ni pour une recherche web (skill recherche)."
---

# Obsidian — écrire juste dans le coffre du cerveau

D'après les skills obsidian-markdown, obsidian-bases et canvas de claude-obsidian (AgriciDaniel, MIT), réduites aux
conventions de ce coffre. Doute sur une syntaxe récente → l'aide officielle (help.obsidian.md) fait foi.
Question de syntaxe : répondre sans rien écrire. Modification demandée : montrer le texte complet, écrire, puis
`brain wiki lint` et dire ce qui reste. Jamais supprimer ni renommer une page, une base ou un canvas sans accord.

## Propriétés (en tête de page)
```yaml
---
type: concept                    # concept, entite, sujet, source, analyse, decision, fait, apprentissage, reference, afaire…
resume: "Une phrase qui dit l'essentiel."
tags: [cafe, boisson]            # jamais un tag fait que de chiffres (« 2026 » invalide ; « annee/2026 » ok)
domaine: [business]
sources: ["[[Titre d'une page Sources]]"]   # un lien dans le YAML : toujours entre guillemets
lie_a: ["[[Autre page]]"]        # aussi fait_partie_de, depend_de, utilise, corrige, remplace, contredit, a_propos_de
projet: "[[Nom du projet]]"
importance: 3                    # entier 1 à 5
echeance: 2026-11-15             # dates AAAA-MM-JJ
---
```
- YAML plat, pas d'objet imbriqué. `id`, `origine`, `cree`, `maj` : posés par le cerveau, ne pas y toucher.
- Garder les propriétés inconnues déjà présentes. Le lint signale type inconnu, importance hors 1–5, date illisible.

## Dans le texte
```markdown
[[Page]]  [[Page|texte affiché]]  [[Page#Titre]]  [[Page#^preuve-1]]  [[Dossier/Page]] si le nom est ambigu
Paragraphe citable. ^preuve-1
![[Page#Résumé]]  ![[schema.png|480]]  ![[doc.pdf#page=3]]  ![[Tableau de bord.base#À faire]]
==surligné==   %%commentaire invisible%%   #tag/sous-tag   $E = mc^2$   [lien externe](https://…)
```
Le lien vise le nom exact du fichier (sans `.md`) ; ne jamais inventer une cible pour faire joli : une page manquante
se crée ou le lien reste en texte. Liens web en Markdown classique, pages du coffre en `[[…]]`.

Encadrés : `> [!note]`, `abstract`, `info`, `todo`, `tip`, `success`, `question`, `warning`, `failure`, `danger`,
`bug`, `example`, `quote` ; `> [!question]- Titre` = replié, `+` = déplié. Propre au cerveau :
```markdown
> [!contradiction] Prix du café vert
> [[Source A]] (03/2026) : 30 €/kg · [[Source B]] (09/2026) : 45 €/kg. Non tranché.
```
dans les deux pages concernées (le lint les liste). Mermaid : bloc ```` ```mermaid ````. Tableaux, cases `- [ ]`,
notes de bas de page : Markdown standard ; pas de HTML si le Markdown suffit.

## Bases (`.base`, YAML)
`Tableau de bord.base` (racine du coffre) n'est écrit par le cerveau que s'il manque : on peut le retoucher. Pour un
nouveau besoin, **ajouter une vue** à cette base plutôt qu'un nouveau fichier.
```yaml
filters:                         # global ; chaque vue peut avoir les siens. Niveaux : and / or / not
  and:
    - file.inFolder("wiki")
    - 'note.type == "decision"'
formulas:
  etat: 'if(note.echeance.isEmpty(), "sans date", if(note.echeance < today(), "en retard", note.echeance.relative()))'
  liens: file.backlinks.length
properties:
  note.importance: {displayName: Importance}
views:
  - type: table                  # table, cards (Obsidian 1.9+), list (1.10+), kanban (1.14+, selon la doc officielle)
    name: Décisions récentes
    order: [file.name, projet, importance, formula.etat]
    sort: [{property: maj, direction: DESC}]
    limit: 30
```
- Propriétés de page `note.x` (ou `x`), fichier `file.name`, `file.path`, `file.folder`, `file.mtime`, `file.tags`,
  `file.backlinks` ; calculées `formula.x`, définies dans `formulas` avant d'être affichées.
- Mettre entre guillemets toute expression avec opérateur, `:` ou guillemets. Protéger le vide par `if(…isEmpty()…)`.
- Écart entre deux dates : la doc parle de millisecondes, le journal de la 1.9.3 d'une durée → comparer (`<`, `==`)
  et `.relative()` marchent ; un calcul en jours se teste dans Obsidian avant d'être livré.
- Kanban : `groupBy: {property: note.x, direction: ASC}` sur une propriété modifiable (déplacer une carte change la
  propriété de la page). Pas de clés Dataview (`from`, `where`). Une colonne d'une propriété absente reste vide : le dire.

## Canvas (`.canvas`, JSON Canvas 1.0)
`Carte du cerveau.canvas` est **réécrite** par le cerveau quand les thèmes changent : pour la personnaliser, la
dupliquer. Un nouveau canvas va à la racine du coffre (hors `wiki/`).
```json
{"nodes": [
  {"id": "6f0ad84f44ce9c17", "type": "text", "text": "# Titre\n\nTexte **Markdown**.", "x": 0, "y": 0, "width": 400, "height": 180, "color": "4"},
  {"id": "a1b2c3d4e5f67890", "type": "file", "file": "wiki/Concepts/Café.md", "subpath": "#Usages", "x": 460, "y": 0, "width": 400, "height": 240},
  {"id": "0c9e8d7f6a5b4c3d", "type": "group", "label": "Produits", "x": -20, "y": -60, "width": 900, "height": 320}],
 "edges": [
  {"id": "e1f2a3b4c5d6e7f8", "fromNode": "6f0ad84f44ce9c17", "fromSide": "right", "toNode": "a1b2c3d4e5f67890", "toSide": "left", "label": "détaille"}]}
```
- Types : `text`, `file` (+ `subpath`), `link` (`url`, https seulement : Obsidian peut appeler le site à
  l'ouverture pour l'aperçu ; sinon une carte texte avec l'URL), `group` (`label`, `background`).
- `x`, `y` = coin haut gauche, entiers ; y vers le bas ; tailles entières positives (lisible : 200 × 60 au moins).
- Identifiants uniques (16 caractères hexadécimaux) ; chaque `fromNode`/`toNode` existe. Côtés `top`, `right`,
  `bottom`, `left` ; `toEnd` vaut `arrow` par défaut, `none` pour un trait. Couleurs `"1"` rouge, `"2"` orange,
  `"3"` jaune, `"4"` vert, `"5"` cyan, `"6"` violet, ou `"#RRGGBB"`.
- Chemins relatifs au coffre, fichiers existants. Un groupe n'est qu'un cadre : 20 px de marge, 40 px entre cartes.
- Garder les champs inconnus et l'ordre des cartes (= ordre d'empilement) ; retirer des cartes : accord d'abord.

Vérifier avant d'écrire un canvas :
```bash
python -c "import json,sys;d=json.load(open(sys.argv[1],encoding='utf-8'));n=[x['id'] for x in d['nodes']];e=d.get('edges',[]);ids=n+[x['id'] for x in e];print('ids en double' if len(set(ids))<len(ids) else 'ids ok',[x['id'] for x in e if x['fromNode'] not in n or x['toNode'] not in n] or 'liens ok',[x['id'] for x in d['nodes'] if any(type(x.get(k)) is not int for k in ('x','y','width','height'))] or 'tailles ok')" "Mon canvas.canvas"
```
