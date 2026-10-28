# ADR-007 — Client MCP : adaptateur maison sur le SDK officiel

- Statut : proposé
- Date : 2026-10-18
- Phase : 1

## Contexte
Le graphe LangGraph (ADR-002) appelle des outils LangChain ; les plugins sont des serveurs MCP
(section 6). Il faut un pont, filtré par le registre : seuls les outils d'un manifeste valide et
d'une classe autorisée au niveau courant sont exposés (R8, R13). Faits vérifiés le 2026-10-18 :
- `langchain-mcp-adapters` 0.3.2 : dépôt archivé ; remplaçant annoncé `langchain[mcp]`
  (`langchain.mcp`), encore en bêta (PyPI et GitHub) ;
- SDK `mcp` 2.3.0 (MIT) : client stdio et session client, tests client / serveur en mémoire.

## Options
1. **`langchain-mcp-adapters`** : prêt à l'emploi, mais archivé (plus de correctifs de sécurité).
2. **`langchain.mcp` (bêta)** : API instable, dépendance de plus.
3. **Adaptateur maison (~150 lignes) sur `mcp` 2.3.0** : peu de code, contrôle total du filtrage,
   des délais et de ce qui est journalisé.

## Décision
Option 3. L'adaptateur :
- lance le serveur du plugin en stdio avec un environnement réduit à une liste blanche de
  variables (le serveur ne reçoit que les clés dont il a besoin) ;
- liste les outils, ne garde que ceux déclarés dans le manifeste validé du plugin et dont la classe
  est autorisée par le moteur de politique ;
- convertit chaque outil en outil LangChain (schéma d'entrée du manifeste), applique un délai par
  appel et compte l'appel dans le budget de la requête ;
- journalise chaque appel (`TOOL_CALL` : plugin, version, outil, durée, statut, coût), sans le
  contenu des pages.

## Conséquences
- Plus simple : aucune dépendance archivée ; filtrage testable sans réseau.
- Plus difficile : à maintenir au fil des versions du protocole MCP ; seul le transport stdio est
  couvert (HTTP au backlog si un plugin distant apparaît).
- `.mcp.json` reste vide : ces serveurs servent le runtime de CERVEAU, pas Claude Code. Le hook
  B7 refuse tout outil `mcp__*` non listé côté Claude Code.
- Réversible : oui ; remplaçable par `langchain.mcp` une fois stable.
