# 🧠 Cerveau — le wiki

Le cerveau en wiki Markdown : ingérer une source, santé, journal. Commande : `python "$HOME/.claude/brain/brain.py" <commande>`.

## Wiki (le « LLM Wiki » de Karpathy)
Le cerveau peut vivre dans un **wiki Markdown** (un dépôt git ouvert comme coffre Obsidian) : chaque souvenir y est
une page, et Claude y compile le savoir des sources — `raw/` (sources brutes, immuables), `wiki/<Type>/` (pages tenues
par Claude), `archive/`, `CLAUDE.md` (le schéma : conventions et méthodes, à suivre et à faire évoluer), `index.md`
(catalogue régénéré), `log.md` (journal, on ajoute en bas). Types de savoir en plus : `source`, `concept`, `topic`
(sujet), `analysis` (analyse) ; `add`/`edit`/`rm` créent, modifient, archivent les pages ; `q` cherche dans tout le wiki.

| But | Commande |
|---|---|
| Créer le wiki et y migrer le cerveau (rien n'est perdu : instantané + copie de graph.json) | `wiki init <dossier>` (idéalement le clone d'un dépôt GitHub privé) |
| Ingérer une source : rangée dans raw/, page Sources créée, plan affiché (pages concernées, entités repérées) | `wiki add <fichier\|url\|->` (`-` = texte par stdin, avec `-T "Titre" [--url …] [--format video]`) |
| Sources en attente (déposées dans raw/ par le Web Clipper, ou pages Sources à remplir) | `wiki pending` |
| Santé : pages à créer, orphelines, sans résumé, sources abîmées, pages dépassées, doublons, contradictions | `wiki lint [--log]` |
| Journal : noter une ingestion, une réponse rangée, un entretien · voir les dernières entrées | `wiki log ingest\|query\|lint\|note "titre" "ligne" …` · `wiki log` |
| État (pages, sources, git) · schéma par défaut · index.md · commit + pull + push | `wiki` · `wiki schema` · `wiki index` · `wiki sync` |

Méthode d'ingestion (détail dans le CLAUDE.md du wiki) : lire la source → dire les points clés → remplir la page
Sources (remplacer « ⏳ à remplir », `resume:`) → intégrer dans les pages concernées (10 à 15 pages, `sources:`),
contradictions en `> [!contradiction]` → `wiki log ingest`. Une bonne réponse se range dans une page Analyses.
Sur le PC, commit/pull/push se font seuls en début et en fin de session ; dans une session cloud, pousser sur sa branche.
