# ADR-069 — Claude Code comme chef d'orchestre, à budget API nul

- Statut : proposé
- Date : 2026-11-17
- Phase : plan v2, étape 4 (`docs/archive/plans/plan-parite-aladdin-v2.md`, C21)

## Contexte
L'utilisateur a fixé le budget de l'API Anthropic à 0 € le 17/11/2026, en plus de son abonnement
Claude. Le chef d'orchestre de CERVEAU (graphe LangGraph, ADR-002) appelle l'API à chaque nœud :
sans budget, il ne peut pas tourner, et aucune campagne d'évals réelle n'a jamais eu lieu.
`interfaces/mcp_server/` est vide : rien ne relie la plateforme à Claude Code, qui tourne, lui, sur
l'abonnement de l'utilisateur.

Aladdin Copilot repose sur trois éléments (méga-prompt, §2.2) : un chef d'orchestre, un registre
d'outils enregistrés et filtrés, et des garde-fous déterministes. Les deux derniers existent déjà
dans CERVEAU (registre, moteur de politique, Porte de risque, kill switch, journal chaîné).

## Options
1. **Garder LangGraph et demander un budget API.** Écartée : l'utilisateur a choisi 0 €.
2. **Faire tourner le chef d'orchestre sur un modèle local** (Ollama, `models.yaml › local`).
   Écartée pour la planification : la carte graphique de l'utilisateur n'est pas connue (D9), et
   un petit modèle planifie mal au-delà de quelques outils. Reste possible pour le routage et les
   tâches de nuit.
3. **Claude Code comme chef d'orchestre**, par un serveur MCP qui expose les outils des plugins
   enregistrés, sous la même gouvernance. Retenue.
4. **Claude Agent SDK en mode non interactif sur l'abonnement.** Conditions d'usage et limites
   `A_VERIFIER` ; à réexaminer pour les tâches planifiées (étape 8 du plan).

## Décision
Option 3. Un serveur MCP `cerveau-plateforme` (stdio, `interfaces/mcp_server/`) :
- expose les outils des plugins enregistrés et valides (R8), filtrés par domaine : 25 au plus,
  comme le planificateur actuel (méga-prompt, §6.4) ;
- fait passer chaque appel par le moteur de politique (classe d'action × niveau effectif du
  domaine) et par le kill switch, puis l'écrit au journal d'audit chaîné (R11) ;
- n'exécute jamais une action des classes `COMMUNICATION_EXTERNE`, `IRREVERSIBLE` et `FINANCIERE` :
  l'outil crée une intention, refusée, proposée ou soumise à approbation selon la politique (R2) ;
- ajoute un outil `verifier` : chaque chiffre d'une réponse doit venir d'une sortie d'outil de la
  session (R1), avec la vérification que le chef d'orchestre actuel applique déjà.
Le code LangGraph reste en place, inchangé, pour le jour où un budget API existera.

## Conséquences
- **R5, séparation lecteur / acteur (ADR-008)** : Claude Code lit les contenus non fiables et
  propose les actions. Une page piégée peut lui faire *proposer* une mauvaise action, pas la faire
  *exécuter*, à deux conditions. Les outils d'action ne créent que des intentions. Le code
  d'approbation reste hors de portée de Claude, ce qui exige de fermer B228 avant tout N3. Les
  red teams passeront par Claude Code (étape 8).
- **Évals** : le banc hors ligne ne change pas ; la mesure réelle se fera par Claude Code et ses
  sous-agents, sur l'abonnement (étape 8).
- **Coût** : 0 € d'API ; l'usage est compté sur les limites de l'abonnement.
- **Plugin** : le plugin « cerveau » déclarera ce serveur sur le PC de l'utilisateur seulement,
  jamais chez ses amis.
- **Tests** : un client MCP de test vérifie, sans réseau, qu'une question de risque répond avec les
  chiffres de `finance_risk` et l'écrit au journal, et qu'une demande d'ordre devient une intention
  refusée en N0 (`tests/test_mcp_bridge.py`).

## Mise en œuvre (17/11/2026)
`interfaces/mcp_server/server.py`, lancé par `python -m interfaces.mcp_server`, publie cinq outils :
`domaines`, `outils(domaine)`, `appeler(domaine, outil, arguments)`, `verifier(brouillon)` et
`proposer_action(domaine, classe, resume)`. Cinq outils fixes plutôt qu'un outil par outil de
plugin : la liste vue par Claude Code reste courte, et le filtre par domaine (25 au plus) se fait
dans `outils`, avec la règle de l'adaptateur (`McpPlugin._refusal`). Aucun plugin ne déclare encore
d'outil d'action : `proposer_action` rend donc la décision de la politique pour une action décrite
par Claude, l'écrit au journal (le résumé par son empreinte seulement, R6) et n'exécute rien.

## Mise en service, par l'utilisateur seul
Le serveur n'est déclaré nulle part. Claude Code ne touche ni à `.mcp.json` ni aux garde-fous. Pour
l'activer :
1. Déclarer le serveur dans `.mcp.json`, ou dans la configuration MCP de Claude Code sur le PC :
   commande `uv`, arguments `run --project <dossier de la plateforme> python -m interfaces.mcp_server`.
2. Ajouter ses cinq outils à la liste d'autorisation de `.claude/hooks/guard_mcp.py`
   (`PROJECT_TOOLS`) ; sans cela, le garde-fou les refuse.
