# ADR-052 — Délai d'un appel d'outil déclaré par le plugin

- Statut : **proposé** (F8 du complément de plan P3b, validé par l'utilisateur le 22/10/2026)
- Date : 2026-10-22
- Phase : 6 (P3b)

## Contexte
L'adaptateur MCP (`core/mcp/adapter.py`) coupait tout appel d'outil à 30 s (`TOOL_TIMEOUT_S`) ou à
la fin du budget de la requête. `code_checks` partageait donc 25 s entre la copie et ses conteneurs
(ADR-048) : les 300 s de E5 étaient inatteignables (B272). `code_agent` (F5) a besoin de 15 min.
Le serveur d'un plugin ne connaît pas la limite à laquelle l'adaptateur le coupe : s'il travaille
hors de son processus (conteneur), ce travail peut lui survivre (B282).

Faits vérifiés le 22/10/2026 dans `.venv` (mcp 2.3.0) : `Client.call_tool` accepte
`meta: RequestParamsMeta`, une table ouverte transmise dans `params._meta` ; côté serveur, un
paramètre `ctx: Context` est injecté, exclu du schéma d'entrée, et la table se lit par
`ctx.request_context.meta`. La spécification MCP admet dans `_meta` des clés préfixées
(`libellé/nom`) ; la liste exacte des préfixes réservés est `A_VERIFIER` avant acceptation.

## Options
1. **Relever la limite globale** : simple, mais tout plugin hérite d'un délai long, y compris ceux
   qui n'en ont pas besoin ; un serveur bloqué immobilise la requête plus longtemps.
2. **Délai déclaré dans le manifeste, transmis au serveur** : chaque plugin dit ce qu'il lui faut,
   borné par un maximum ; le budget de la requête reste prioritaire ; le serveur reçoit la limite
   réelle et finit avant la coupure.
3. **Tâche de fond suivie** (un appel lance, un autre lit le résultat) : adapté aux très longs
   travaux, mais demande un état persistant, un nettoyage et un nouvel outil par plugin.

## Décision
Option 2.
- Manifeste : `runtime.tool_timeout_s`, 30 s par défaut, maximum 900 s (`core/mcp/time_limit.py`),
  validé par `core/registry/manifest.py`.
- Adaptateur : un appel est coupé à `min(tool_timeout_s, budget restant de la requête)` ; le
  démarrage d'un serveur reste borné à 30 s quel que soit le manifeste.
- Chaque appel porte cette limite dans `_meta` sous la clé `cerveau/time_limit_s`. Une valeur
  absente ou invalide se lit comme `None` ; une valeur au-delà de 900 s est ramenée à 900 s.
- `code_checks` déclare 315 s : les 300 s de E5 pour les conteneurs plus une réserve de 15 s
  (`KILL_TIMEOUT_S` + 5 s) pour arrêter un conteneur en retard et répondre. Le plan citait 300 s ;
  l'écart garde les 300 s de E5 atteignables. Sans limite reçue (autre client), le budget de 25 s
  d'ADR-048 s'applique, inchangé (golden cc-011, R9).

## Conséquences
- B272 n'est réglé qu'en partie : dans une requête ordinaire, `per_request.max_seconds` (120 s,
  `config/budgets.yaml`) coupe toujours l'appel plus tôt ; `code_checks` dispose alors d'au plus
  105 s. Relever ce budget relève de l'utilisateur ; `code_agent` aura un budget de tâche propre (commit 5).
- B282 est atténué pour `code_checks` (le budget des conteneurs finit avant la coupure) mais reste
  ouvert : un `docker kill` qui échoue laisse un conteneur vivant. `code_agent` le traite par
  `--init`, `--stop-timeout`, des étiquettes et un balayage.
- Un plugin qui déclare un long délai immobilise la requête jusqu'à cette limite : la revue d'un
  manifeste vérifie la justification du délai.
- ADR-048 (accepté) n'est pas modifié ; le présent ADR précise son budget de 25 s.
- Réversible : retirer la clé du manifeste rend le défaut de 30 s.
