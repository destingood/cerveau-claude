# ADR-051 — Classe d'action EXECUTION_ISOLEE pour l'agent de code

- Statut : **proposé** (F7 du complément de plan P3b, validé par Lucas le 22/10/2026 avec la revue
  `risk-gate-auditor`)
- Date : 2026-10-22
- Phase : 6 (P3b)

## Contexte
Le plugin `code_agent` (P3b) confie une tâche de code à Claude Code dans un conteneur Linux sans
Internet, sur une copie jetable d'un dépôt listé ; sa seule sortie est un patch rangé sous
`var/code/agent/<id>/`, que Lucas applique lui-même (N0, F9). Les six classes de l'Annexe C.4
décrivent mal cette action :
- `CALCUL` suppose un calcul déterministe, testé et évalué (R1, ADR-022, ADR-049) ; la sortie d'un
  modèle ne l'est pas ;
- `ECRITURE_INTERNE` vaut `refus` à N0 et désigne une écriture dans les fichiers ou la mémoire de
  Lucas : l'agent n'écrit que dans sa copie et CERVEAU que dans `var/` ;
- `LECTURE` cacherait à la politique qu'un programme s'exécute et dépense des jetons.
ADR-049 avait écarté une classe dédiée en P3a et renvoyé la question au backlog (B266).

## Options
1. Classer `code_agent` en `CALCUL` : aucun changement de la matrice ; inexact au regard de R1.
2. Classer `code_agent` en `ECRITURE_INTERNE` et passer le domaine `code` à N1 : inexact (rien n'est
   écrit chez Lucas) et contraire à D3 (un nouveau domaine entre à N0).
3. **Ajouter `EXECUTION_ISOLEE`** : une ligne de plus dans la matrice et dans les listes de classes ;
   la politique voit ce qui est demandé.

## Décision
Option 3.
- Définition : tâche exécutée dans un conteneur jetable, sans accès réseau autre que l'API du
  modèle à travers le proxy de CERVEAU, sur une copie ; sa seule sortie est une proposition rangée
  sous `var/`. Écrire dans un dépôt de Lucas, pousser ou ouvrir une PR n'en relèvent pas
  (`ECRITURE_INTERNE`, `COMMUNICATION_EXTERNE` : N2, plus tard).
- `ActionClass` et `ACTION_CLASSES` (`core/config/loader.py`, `core/orchestrator/state.py`) gagnent
  la classe ; `config/autonomy.yaml` lui donne `auto` à tous les niveaux ; le moteur ne l'accorde
  qu'au domaine `code` (`PHASE_DOMAIN_ACTION_CLASSES`) : elle se décide donc après le routage,
  comme `CALCUL` (`ROUTED_ACTION_CLASSES`).
- Annotations MCP attendues : `readOnlyHint` faux (une proposition est écrite sous `var/`),
  `destructiveHint` faux (la copie est jetable), `idempotentHint` faux (sortie d'un modèle).
- Restent prioritaires : kill switch (R4), configuration live activée (R3), refus d'une décision
  qui porterait une réponse de la Porte de risque. La dépense est bornée par le budget de la tâche
  et le proxy (ADR-053, ADR-054) ; tant que les budgets valent `A_DEFINIR`, aucun appel réel (R7).

## Conséquences
- La section 8.2 et l'Annexe C.4 du méga-prompt sont complétées par cet ADR, sans modifier le
  méga-prompt ; `tests/test_policy.py` recopie la nouvelle ligne et vérifie que la matrice n'a ni
  classe en plus ni classe en moins.
- Le contrôle d'entrée doit pouvoir rendre la classe : son prompt change avec le plugin (commit de
  `code_agent`), ce qui relance les évals (R9).
- Revue `risk-gate-auditor` demandée (F7).
- Réversible : retirer `EXECUTION_ISOLEE` du domaine `code` refuse `code_agent` partout ; retirer la
  classe demande de retirer sa ligne de la matrice.
