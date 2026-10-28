# ADR-005 — Routage des modèles, coûts déterministes et budgets

- Statut : proposé
- Date : 2026-10-18
- Phase : 1

## Contexte
L'orchestrateur appelle plusieurs modèles (classifieur, lecteur, planificateur, juge). La section 5
et l'Annexe B.1 fixent quatre tiers (`deep`, `standard`, `fast`, `local`). Règles en jeu : R1 (un
coût est un chiffre décisionnel, donc calculé par du code), R7 (budgets `A_DEFINIR` = blocage),
R11 (tout passe par le journal d'audit). Faits vérifiés le 2026-10-18 :
- tarifs (platform.claude.com/docs/en/about-claude/models/overview) : `claude-opus-5-5`
  4 $ / 20 $ par MTok, `claude-sonnet-5-5` 2 $ / 10 $, `claude-haiku-5-5` à partir de
  0,10 $ / 0,50 $ ; lecture de cache : 5 % du prix d'entrée (Opus et Sonnet 5.5) ;
- `langchain-anthropic` 1.7.6 (source installée) : champ `reasoning_effort` (alias `effort`,
  valeurs `low` à `max`) qui règle `output_config.effort` ; `thinking` accepte
  `{"type": "adaptive"}` ; sur Opus 5.5 la réflexion ne peut pas être désactivée ;
- taux BCE de référence du 2026-10-16 : 1 EUR = 1,1253 USD (décision D5).

## Options
1. **Table de prix de Langfuse** : rien à maintenir, mais coût invisible sans Langfuse, table non
   vérifiée par nous (`A_VERIFIER`), et Langfuse est optionnel.
2. **Coût renvoyé par le fournisseur** : l'API Messages renvoie l'usage en tokens, pas de prix.
3. **`config/pricing.yaml` + calcul `Decimal` + grand livre dérivé du journal d'audit** : prix
   datés et sourcés, calcul reproductible, une seule source de vérité.
4. **Option 3 avec une base de coûts séparée (SQLite)** : requêtes plus rapides, mais deux
   sources de vérité à garder cohérentes.

## Décision
Option 3.
- `ModelRouter` lit `models.yaml` et associe un rôle à un tier : `fast` pour le classifieur et le
  lecteur, `standard` pour le planificateur, `deep` pour les requêtes complexes et le juge (juge
  différent du modèle évalué). Un tier dont un champ vaut `A_DEFINIR` ou `A_VERIFIER` est refusé
  (`local` reste bloqué ; `langchain-ollama` reporté).
- Chaque appel relève l'usage (entrée, sortie, écriture et lecture de cache, recherches web). Le
  coût est calculé en USD (`Decimal`, arrondi à 1e-6) depuis `pricing.yaml`, puis converti en EUR
  au taux fixe daté. Le coût part dans la charge utile des entrées `DECISION` / `TOOL_CALL`.
- Le grand livre jour / mois se recalcule en relisant le journal. Avant chaque requête, la porte de
  budget refuse si un budget vaut `A_DEFINIR` (R7) ou si 100 % est atteint (D9). Les seuils
  50 / 80 / 100 % produisent une alerte dans la CLI et une entrée `POLICY` dans le journal.
- Par requête : 25 appels d'outils, 150 000 tokens (D4), 120 s. Au dépassement, la réponse est
  partielle et le dit.

## Conséquences
- Plus simple : coût identique avec ou sans Langfuse ; un audit vérifie aussi les dépenses.
- Plus difficile : les prix se tiennent à jour à la main (date et URL obligatoires) ; relire le
  journal coûte O(n) par requête (acceptable au volume personnel ; index au backlog si besoin).
- Le gain du cache de prompt est `A_VERIFIER` : il sera mesuré, pas supposé.
- `cerveau ask` réel reste bloqué tant que les budgets jour et mois ne sont pas fixés par Lucas.
- Réversible : oui ; le schéma des coûts dans le journal est versionné.
