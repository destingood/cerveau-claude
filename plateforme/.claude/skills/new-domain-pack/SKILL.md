---
name: new-domain-pack
description: Crée un pack de domaine CERVEAU conforme à la section 9.1 (manifeste, prompts de rôle et de grille, sources autorisées, golden set, suite de comportements). À utiliser quand un nouveau domaine est ouvert dans la phase en cours.
argument-hint: "<domaine>"
---
# Nouveau pack de domaine : $ARGUMENTS

1. Vérifie que le pack est prévu dans la phase en cours (sections 9.2 et 17). Sinon, `docs/backlog.md`.
2. Crée l'arborescence de la section 9.1 :
   ```
   domain_packs/<domaine>/
   ├── manifest.yaml           # périmètre, plugins, autonomie maximale, sources autorisées
   ├── prompts/role.md         # rôle et méthode du domaine
   ├── prompts/rubric.md       # critères d'une bonne réponse
   ├── knowledge/sources.yaml  # corpus autorisé + fréquence de mise à jour
   ├── evals/golden.jsonl      # ≥ 30 cas au départ
   ├── evals/behaviors.yaml    # comportements propres au domaine
   └── README.md
   ```
3. Autonomie maximale initiale : celle du tableau 9.2, jamais plus. Toute valeur inconnue :
   `A_DEFINIR` (R7).
4. Les sources autorisées sont vérifiées (licence, CGU, R14, R15) — agent `source-verifier`.
5. Le golden set et les comportements sont écrits avec l'agent `eval-engineer` ; ils couvrent R1, R5,
   R12 et R16 pour ce domaine.
6. Lance `make eval` et rapporte le score. Le pack reste « inactif » tant que son seuil n'est pas atteint.

Termine par : fichiers créés, nombre de cas, score obtenu contre seuil, `A_DEFINIR` rencontrés.
