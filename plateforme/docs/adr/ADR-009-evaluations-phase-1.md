# ADR-009 — Harnais d'évaluation de la phase 1

- Statut : proposé
- Date : 2026-10-18
- Phase : 1

## Contexte
Les critères de la phase 1 (section 17) se mesurent : golden Généraliste ≥ 30 cas et score ≥ seuil,
100 % des réponses factuelles sourcées, 0 violation R5, coût moyen publié. R9 : un seuil ou un
golden set ne baisse jamais. promptfoo 0.124.1 est déjà épinglé (phase 0). La CI n'a ni clé ni
réseau ; une campagne réelle coûte de l'argent (estimation 6 à 12 $, non mesurée).

## Options
1. **promptfoo + provider Python + assertions Python** : outil déjà en place, rapports JSON.
2. **DeepEval** : métriques prêtes, mais dépendance de plus et juge hors de notre routeur.
3. **Harnais pytest maison seulement** : simple, mais pas de rapport d'éval standard.

## Décision
Option 1.
- Le provider Python appelle le graphe complet ; les assertions Python lancent nos contrôles
  déterministes (format 7.3, sourçage, citations, chiffres, violations R5).
- Le juge passe par notre routeur (tier `deep`, différent du modèle évalué) : son coût entre dans
  le grand livre et les budgets (ADR-005). Il note au rubric du pack (0 à 1).
- Deux modes : **hors ligne** (CI, `make eval`) avec modèles factices et pages fixtures, qui
  vérifie la plomberie et tous les contrôles déterministes ; **réel** (`make eval-live`), avec
  vrais modèles, pages fixtures pour la reproductibilité et un petit lot en web réel, lancé
  seulement avec l'accord de l'utilisateur pour chaque campagne (D8).
- Seuil du golden Généraliste : 0,80, écrit dans `config/evals.yaml` avant la première mesure (D6).
  Le golden set est gelé après validation de l'utilisateur.
- Rapport : `evals/reports/phase-1-<date>.md` + JSON (scores, taux, coût, latence) et un
  échantillon de 20 jugements à relire par l'utilisateur.

## Conséquences
- Plus simple : un seul outil d'éval, déjà épinglé ; le mode hors ligne tourne à chaque commit.
- Plus difficile : le score réel n'existe qu'après une campagne payante ; un juge LLM se trompe
  (relecture humaine hebdomadaire de 20 jugements, `config/evals.yaml`).
- Réversible : oui ; les cas sont en JSONL / YAML, lisibles par un autre outil.
