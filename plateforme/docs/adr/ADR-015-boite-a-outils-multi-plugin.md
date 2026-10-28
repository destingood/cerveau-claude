# ADR-015 — Boîte à outils multi-plugin et démarrage déclaré dans le manifeste

- Statut : **accepté par Lucas le 18/10/2026** (plan de phase 2, D15, D18)
- Date : 2026-10-18
- Phase : 2

## Contexte
En phase 1, une requête n'ouvre qu'un plugin (`web_research`), et la façon de le démarrer est une
constante de `core/mcp/adapter.py` (backlog B26). Le pack Finance a besoin de cinq plugins, plus
les deux outils web partagés avec le pack Généraliste. Par ailleurs, le kill switch n'est vérifié
qu'au début et à la fin d'une requête (B70).

## Options
1. **Un seul serveur MCP Finance** avec les cinq outils : un démarrage au lieu de cinq, mais un
   seul manifeste et une seule étiquette de parité pour des fonctions dont la parité diffère
   (§10.1).
2. **Un plugin par fonction, ouverts ensemble** : un manifeste, des tests et des évals par plugin
   (R8), et des étiquettes distinctes.

## Décision
Option 2.
- Le manifeste C.1 gagne un bloc `runtime` facultatif (`module`, `env`, `priced_tools`). Le
  registre le valide, et l'adaptateur le lit à la place de la constante `RUNTIMES` (B26). Un plugin
  sans bloc `runtime` est refusé au démarrage.
- Le manifeste d'un pack de domaine (`domain_packs/<pack>/manifest.yaml`) liste ses plugins. Le
  nœud de routage ouvre les plugins du pack choisi, dans l'ordre du manifeste. Chacun est filtré
  par le registre et par le moteur de politique, et la liste totale reste bornée par
  `max_tools_to_planner`.
- Un plugin injoignable n'empêche pas les autres : il est listé dans `skipped`.
- Les outils CALCUL et LECTURE de la finance renvoient des chiffres. Le planificateur les voit,
  et le contrôle (nœud 5) les ajoute aux sources des nombres (R1). Le texte libre d'un fournisseur
  n'atteint jamais le planificateur (R5).
- `Run.invoke` vérifie le kill switch avant chaque appel de modèle et arrête la requête s'il est
  engagé (B70).

## Conséquences
- Plus simple : un plugin se démarre à partir de son seul dossier ; on teste chacun isolément.
- Plus difficile : jusqu'à cinq processus par requête Finance (environ 1 s de démarrage chacun) ;
  ils sont ouverts une fois par requête, en parallèle.
- Les versions de tous les plugins ouverts figurent dans l'entrée `DECISION` (R11).
- Réversible : oui ; un regroupement en un serveur reste possible sans changer les outils.
