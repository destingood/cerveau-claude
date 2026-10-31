# ADR-045 — Agent `deep_research` : recherche approfondie à citations vérifiées

- Statut : proposé (déclenchement, bornes et retrait des affirmations validés par D13 à D15 le
  21/10/2026 ; détails d'implémentation ci-dessous à valider par l'utilisateur)
- Date : 2026-10-22
- Phase : 6

## Contexte
Le pack `recherche` (P2, plan de phase 6 §5) doit répondre à une question ouverte par plusieurs
lectures, sans qu'un LLM invente une source ou un chiffre. Décisions : D12 (publications lues par
leur résumé, sans PDF), D13 (5 sous-questions et 12 lectures au plus ; jetons, secondes et appels à
`A_DEFINIR`), D14 (sur demande explicite seulement), D15 (affirmation non vérifiée retirée et
listée). Règles : R1, R4, R5, R7, R9, R11, R12.

Fait vérifié le 2026-10-22 ([Crossmark](https://www.crossref.org/documentation/crossmark/participating-in-crossmark/),
page mise à jour le 2026-08-12) : 12 types de mise à jour, dont `retraction`,
`partial_retraction`, `withdrawal`, `removal`, `correction`, `erratum`, `expression_of_concern`.

## Options
1. **Moteur maison `core/research/` et agent `plugins/deep_research/`** (prompts et version) :
   réutilise le lecteur sans outil, `check_quote`, la trace des chiffres et le budget de requête.
   Environ 600 lignes et leurs tests ; aucune dépendance.
2. **Bibliothèque gpt-researcher** : complète, mais ses propres appels réseau et LLM échappent au
   moteur de politique, au budget et au journal (R2, R11) ; dépendance lourde.
3. **Boucle du planificateur avec plus de tours** : rien à écrire, mais ni plan ni contrôle
   affirmation par affirmation (D15 impossible).

## Décision
Option 1 (inspirée de gpt-researcher et de STORM, aucun code repris) :
- **Déclenchement** : `cerveau ask --approfondi` seulement ; le routeur ne peut pas choisir ce mode
  et son prompt ne change pas (D14). Exclu avec `--comite`. Le domaine est le premier pack dont le
  manifeste déclare `agent: {plugin, mode: approfondi}` ; sans lui, refus avant tout outil.
- **Budget** : `RequestBudget.for_deep_research` remplace celui de la requête avant l'ouverture des
  outils, qui le débitent. `per_deep_research` à `A_DEFINIR` bloque la fonctionnalité
  `recherche.deep_research` (R7) ; `max_sub_questions ≤ 5` et `max_reads ≤ 12` sont bornés par le
  schéma (une valeur ne peut que baisser).
- **Plan** : JSON du rôle `planner` ; plus de 20 sous-questions = mal formé, au-delà de 5 = coupé
  et compté ; une seule reformulation, puis réponse partielle.
- **Collecte** : par sous-question, `web_search` (5 résultats) et `scholar_search` (3 notices) ;
  lectures alternées entre sous-questions, dédoublonnées par adresse, DOI et identifiant. Une
  notice sans résumé n'est pas lue ; une notice rétractée, retirée ou supprimée (4 types ci-dessus)
  n'est jamais lue ni citée ; une autre mise à jour est signalée (« [n] : correction »).
- **Rédaction** : le rédacteur ne voit que les extraits vérifiés, numérotés `n.m`. Le code garde une
  affirmation seulement si elle cite au moins un extrait connu et si chacun de ses chiffres et
  dates figure dans ce qu'elle cite (R1) ; sinon elle est retirée et listée sous « Points non
  vérifiés » avec sa raison (D15).
- **Arrêt** : budget dépassé, deux réponses mal formées ou kill switch donnent une réponse
  partielle bâtie sur les seuls extraits vérifiés ; le kill switch arrête la requête (R4).
- **Journal** : `var/<pack>/approfondi/<id>.json` (sous-questions, sources, extraits, retraits) ;
  la citation tirée d'un résumé Crossref y est remplacée par son sha256 (ADR-044). L'entrée
  DECISION cite le fichier par son sha256 avec des compteurs, sans texte (R11). La version de
  l'agent inclut l'empreinte de ses prompts (R9).
- **Textes libres du rédacteur** : justification, prochaines étapes et affirmations retirées
  formulées comme des consignes sont masquées, comme les titres de section (R5).

**Écarts au plan §5** : pas de type de source « flux » (la recherche n'appelle pas `feed_read` ;
la veille est à part) ; « article publié (relecture par les pairs non vérifiée) » au lieu
d'« article évalué », que rien ne prouve ; une année seule compte comme une date à retrouver ; le
renvoi `[n]` se place avant la ponctuation finale.

## Conséquences
- Plus simple : réponses longues dont chaque chiffre est retrouvé dans une source lue ; même
  gouvernance que le planificateur (politique, R5, budget, journal).
- Plus difficile : réponses courtes quand les résumés sont pauvres (D12) ; aucune recherche réelle
  tant que l'utilisateur n'a pas fixé `per_deep_research` et les budgets en euros (R7) ; qualité mesurée
  hors ligne seulement (D5).
- Réversible : agent retirable du manifeste du pack sans toucher au graphe.
- Backlog : flux dans la recherche avec la veille planifiée (phase 7) ; sens de `updated-by` à
  confirmer sur de vraies rétractations (`A_VERIFIER`, ADR-044) ; `p95_latency_ms` à `A_DEFINIR`.
