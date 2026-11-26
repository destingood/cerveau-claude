# ADR-071 — Pont MCP : un journal en empreintes, des plafonds comptés dans le journal

- Statut : proposé (les deux plafonds sont ta décision du 26/11/2026 ; le reste attend ta validation)
- Date : 2026-11-26
- Phase : plan, Bloc B « Le pont MCP », points 2 et 3 (étapes B1.2 et B1.3) ; complète l'ADR-069

## Contexte
La relecture du 20/11 du pont `cerveau-plateforme` (ADR-069, pas encore branché) a reproduit
qu'il gardait au journal les arguments en clair (nom, adresse, IBAN, jeton dans une URL : R6,
G-2), qu'un refus ou une panne n'y laissait aucune trace (R11, G-3), que l'entrée n'était écrite
qu'après l'appel (G-6), et qu'aucun plafond ne bornait les appels d'une session ou d'un jour (R7,
G-7). L'adaptateur des plugins (`core/mcp/adapter.py`) sert aussi l'orchestrateur : ce qui change
dans son journal change pour les deux.

## Options
1. **Garder les valeurs, masquées** (pseudonymisation, comme `journaled` aujourd'hui). Écartée :
   le masque ne voit que ce que l'utilisateur a écrit ; un jeton dans une URL trouvée en ligne
   passe.
2. **Noms des arguments et SHA-256 du JSON canonique de chaque valeur.** Retenue. L'empreinte
   prouve quelle valeur a été envoyée sans la garder. Limite connue : une valeur courte (un nom,
   un IBAN) se confirme par qui la devine ; d'où l'empreinte prise sur la forme masquée
   (`journaled`) de ce que l'utilisateur a écrit. Une empreinte à clé fermerait ce point, mais il
   faudrait une clé hors du dépôt (R6) : à décider plus tard.
3. **Plafonds en mémoire** du pont. Écartée : un redémarrage ou une deuxième session remet le
   compte à zéro.
4. **Plafonds comptés dans le journal d'audit**, seule source qu'aucun redémarrage n'efface.
   Retenue.

## Décision
- **Journal (B1.2)** : `arguments` ne garde que `{nom: "sha256:…"}` (`redactions` le dit). Une
  seule exception, nommée dans `KEPT_ARGUMENTS` : les arguments de `finance_research.strategy_lab`
  vont aussi en clair dans `replay_arguments`, car `cerveau strategy protocol` rejoue chaque
  backtest du Copilote depuis le journal pour ne jamais sous-compter N (ADR-027) ; ce sont un
  identifiant du registre, un point de la grille et des dates, bornés par le schéma de l'outil.
- **Deux entrées par appel** : `en_cours` une fois les contrôles passés, avant le démarrage du
  serveur et l'appel, puis le résultat. Un processus qui meurt en cours d'appel laisse donc sa
  trace. Le pont journalise lui-même (acteur `interface`) ce qui n'atteint pas l'adaptateur :
  domaine ou outil inconnu, nom d'outil ambigu (deux plugins), plugin qui ne démarre pas,
  plafond. Aucune erreur, rendue ou journalisée, ne garde un chemin absolu.
- **Plafonds (B1.3)** : `budgets.yaml › per_bridge`, 200 appels par session et 1 000 par jour
  (heure locale), ta décision du 26/11. Toute demande à `appeler` compte, refus compris : une
  boucle de refus doit s'arrêter aussi. Le compte du jour est le nombre d'identifiants
  `mcp-appel-…` distincts parmi les `TOOL_CALL` du jour (`core/budget/calls.py`) ; une demande
  refusée au plafond prend le préfixe `mcp-plafond-…` et ne compte plus. Un marqueur dans
  `per_bridge` ou un journal illisible refuse l'appel (R7).
- **Démarrage, kill switch, contenu externe** : un serveur qui ne démarre pas est coupé à 30 s
  (la limite d'un appel, ADR-052) ; le kill switch est relu toutes les 0,2 s pendant un appel,
  qui est annulé (`arret_urgence`) ; il est engagé si son dossier est remplacé par un fichier ou
  illisible. La sortie d'un outil `openWorldHint` revient marquée `donnees_externes`, avec un
  avertissement (R5).

## Conséquences
- Le journal ne permet plus de relire ce qu'un outil a reçu, sauf `strategy_lab` : un incident se
  rejoue en comparant les empreintes à une valeur connue.
- Deux sessions lancées au même instant peuvent dépasser le plafond du jour d'un appel chacune
  (outil personnel, même réserve que l'ADR-005).
- Le contrôle du budget quotidien en euros (`BudgetGate`) n'est pas appelé par le pont : tant que
  `llm_budget_eur` vaut `A_DEFINIR`, il refuserait tous les appels (R7). À décider : le pont
  ne dépense aucun euro d'API ; ce contrôle doit-il s'y appliquer ?
- Reste du point 4 du plan : `proposer_action` sans suite, un processus par appel.
