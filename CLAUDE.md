# Cerveau — consignes pour Claude Code dans ce dépôt

Ce dépôt est le plugin « cerveau » de Claude Code (mémoire persistante), à la racine. `plateforme/` est un projet
à part, avec son propre `CLAUDE.md` et sa propre CI ; `fortnite-ile/` et `fortnite-arene-prestige/` sont des
projets de l'utilisateur. Plan unique, plugin compris : `plateforme/docs/plans/plan-cerveau.md` (Bloc E = cerveau 4D).

## Carte

- `brain.py` : lanceur. `brainkit/` : le moteur — `store.py` (graphe des souvenirs), `search.py` (rappel),
  `hooks*.py` (démarrage, message, fin), `mcp_server.py`, `viz.py` et `vue3d/` (vue 3D), `wiki*.py`, `dream.py`.
- Livré aux utilisateurs : `hooks/`, `skills/` (23), `agents/` (3), `output-styles/`, `.claude-plugin/`.
  Propre à ce dépôt, jamais livré : `.claude/` (interdits, hooks), `tests/`.

## Commandes

- Lint, comme la CI : `uvx ruff@0.17.1 check --isolated --select F,E9 brain.py brainkit skills tests`.
- Un script de test : `python tests/test_rappel.py` → « N vérifications OK, M échec(s) », code ≠ 0 sur un
  échec (sous Windows, avec `PYTHONUTF8=1`). Chaque script travaille dans un dossier temporaire.
- Ce qui a changé : `python .claude/hooks/verifier.py --tout` (lint et tests des fichiers touchés). Le même hook
  tourne seul en fin de tâche ; s'il te renvoie au travail, corrige la cause.
- Tous les scripts (≈ 4 min) : `for t in tests/test_*.py; do python "$t" || echo "ÉCHEC $t"; done`.
- Banc d'essai du rappel (qualité, faux rappels, tokens, vitesse) : `python brain.py bench`.
- Quel test pour quoi : rappel `test_rappel` · démarrage `test_demarrage` · hooks `test_hooks_situations` ·
  commandes `test_commandes`, `test_erreurs` · texte injecté `test_consommation` · vitesse `test_vitesse_message` ·
  wiki `test_wiki`, `test_wiki_conflits` · vue 3D `test_vue3d` · réglages `test_page_reglages` ·
  skills `test_skills_regroupees`, `test_scripts_skills` · regrouper `test_regroupe` · pertes `test_pertes` ·
  partage `test_partage`, `test_echange`, `test_commun` · e-commerce `test_ecommerce`, `test_boutique` ·
  temps `test_temps`, `test_justesse` · protection `test_protection` · serveur MCP `test_serveur_mcp`.

## Règles

- Bibliothèque standard seule : le plugin tourne en `python -I -S`, Python 3.10 à 3.13, Windows, macOS, Linux.
- Aucune migration ne réécrit les souvenirs : un champ absent prend une valeur déduite à la lecture. Un
  `graph.json` d'une version plus ancienne se charge tel quel, et une version plus ancienne lit un graphe récent.
- Mode wiki : tout nouveau champ fait l'aller-retour page ↔ graphe (`wikistore.py`), avec une clé française.
- Budgets : chaque hook sous 150 ms à 3 000 souvenirs ; texte du démarrage et liste des outils MCP pas plus
  longs (`test_consommation`) ; rappel à 58 questions sur 62 au moins (`test_rappel`) ; aucun fichier au-delà de
  1 000 lignes (`test_decoupage`) : découper avant de grossir.
- Chaque changement a un test qui échoue sans lui. Ne jamais retirer ni affaiblir un test ou un seuil.
- Messages, documentation et commentaires du plugin en français ; commits en anglais, préfixés (`feat:`, `fix:`,
  `test:`, `docs:`, `perf:`, `chore:`).

## Interdits

- `brain.exe` : binaire Rust dont la source n'est pas dans le dépôt ; ne pas le modifier ni le refaire (E12).
- `brainkit/vue3d/3d-force-graph.min.js` et `three-fx.js` : refaits seulement par `brainkit/vue3d/fabriquer.py`
  (versions et empreintes dans `sources.json`, vérifiées par `test_vue3d`).
- Fichiers générés par `brainkit/publish.py` (`_generated`) : `README.md` (`publish.readme`), `hooks/hooks.json`
  (`install.EVENTS`), `.claude-plugin/*.json`, toute la skill `skills/brain/` (`install.write_brain_skill`, dont
  `references/reglages.md` tirée de `reglages_doc.py`). Changer le code qui les écrit, jamais le fichier seul :
  la publication suivante l'écraserait, et des tests comparent ces fichiers au code.
- Ne jamais retirer ni assouplir un interdit ou un hook de `.claude/settings.json`. Un refus d'un hook se signale à
  l'utilisateur ; il ne se contourne pas.

## Publier une version

- Une version mineure par étape du plan : `__version__` dans `brainkit/__init__.py`, l'étape mise à jour dans le
  plan (« faite le … »), un commit, puis `python brain.py publish`. Sur place, il refait les fichiers générés, les
  essaie dans un bac à sable, puis fait le commit « cerveau x.y.z » et le tag. Jamais `--push` sans l'accord de
  l'utilisateur. Les utilisateurs reçoivent la version quand la PR est fusionnée dans `main`.
