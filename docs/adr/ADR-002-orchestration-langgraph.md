# ADR-002 — Orchestration : LangGraph plutôt que le Claude Agent SDK

- Statut : proposé
- Date : 2026-10-17
- Phase : 0 (mise en œuvre en phase 1)

## Contexte
L'orchestrateur exécute les 8 nœuds de la section 7.1. Il doit :
- intercaler des nœuds déterministes (moteur de politique, Porte de risque) entre la décision d'un
  modèle et toute action (R1, R2) ;
- appeler plusieurs fournisseurs, dont des modèles locaux (niveau `local` de `config/models.yaml`) ;
- suspendre une exécution en attente d'une approbation de Lucas (niveaux N1 et N2) ;
- être testable nœud par nœud et tracé dans Langfuse (ADR-004).

Faits vérifiés le 2026-10-17 (PyPI) : `langgraph` 1.2.16 (MIT, publié le 2026-10-16) ;
`claude-agent-sdk` 0.2.168 (MIT, publié le 2026-10-15). Le Claude Agent SDK fournit la boucle
d'agent de Claude Code (outils intégrés, hooks, serveurs MCP), centrée sur les modèles Claude.

## Options
1. **LangGraph (superviseur)** : graphe d'états explicite, nœuds Python ordinaires, points de
   reprise et interruptions pour l'humain dans la boucle, indépendant du fournisseur. Il faut
   écrire et tester la boucle soi-même.
2. **Claude Agent SDK comme orchestrateur** : boucle d'agent complète et éprouvée, hooks et MCP
   natifs. Mais le modèle conduit la boucle (le contrôle déterministe passe par des hooks, pas par
   la structure) et l'usage de modèles locaux sort de son périmètre.
3. **Pydantic AI** : typage fort, multi-fournisseurs ; graphes moins centraux que dans LangGraph.
4. **Microsoft Agent Framework** : multi-agents, multi-fournisseurs ; moins aligné sur la famille
   technique d'Aladdin Copilot, plus récent.

## Décision
Option 1, conforme à la section 5. La garantie R1/R2 doit venir de la topologie du graphe : un
modèle ne peut produire qu'une intention structurée, et seul le nœud de politique, déterministe,
la transmet à un outil d'action. Le Claude Agent SDK est conservé pour le pack Code (piloter
Claude Code) en tant que plugin enregistré derrière le registre, jamais comme orchestrateur.

## Conséquences
- Plus simple : tests unitaires par nœud ; garde-fous structurels plutôt que dépendants du prompt ;
  bascule de fournisseur par configuration.
- Plus difficile : davantage de code à écrire (boucle d'outils, reprises, limites de budget) ;
  suivre les versions majeures de LangGraph (évals relancées à chaque montée, R9).
- Réversible : partiellement ; les nœuds déterministes (politique, Porte de risque, audit) restent
  du Python pur, indépendant de LangGraph.
- Tâches induites (phase 1) : lire la documentation à jour de LangGraph avant le premier nœud ;
  évaluer le SDK pour le pack Code (backlog).
