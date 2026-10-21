# ADR-034 — Kill switch : déclencheurs, effets mesurés sous 5 s, réarmement par Lucas seul

- Statut : accepté (D10 à D13 et D15 du plan de phase 4, validées par Lucas le 20/10/2026 ; cible
  de 5 s écrite à sa demande le 20/10/2026)
- Date : 2026-10-20
- Phase : 4

## Contexte
Le §8.5 et R4 imposent un arrêt total, prioritaire sur tout, sous une cible mesurée. Le kill switch
est aujourd'hui un fichier `governance/kill_switch/KILL` lu à six endroits. Le journal accepte déjà
le type `KILL`.

Faits relevés le 20/10/2026 : les hooks protègent `governance/approvals` et `var/audit`, pas
`governance/kill_switch`. Claude Code pourrait donc supprimer `KILL`, c'est-à-dire réarmer.
`kill_switch.target_seconds` et `data_loss_timeout_seconds` sont `A_DEFINIR`.

## Options
1. Fichier seul, réarmé par sa suppression manuelle.
2. **Fichier, commande et déclencheurs automatiques**, avec un réarmement interactif journalisé et
   des hooks durcis.

## Décision
Option 2.

- **Déclencheurs** :
  - le fichier `KILL` ou `cerveau kill` ;
  - un dépassement de perte du jour, de perte glissante ou de drawdown à la valorisation ;
  - des données perdues : cours de la séance attendue absent au lancement, au-delà de
    `max_staleness_sessions` (1) ;
  - un incident d'exécution : transition illégale, exécution d'un ordre inconnu, quantité exécutée
    excessive, cash négatif, écart de réconciliation issu d'un incident.
- **Effets** : annulation des ordres ouverts, blocage des nouvelles intentions, N0 forcé, entrée
  `KILL` au journal, rapport d'incident en français dans `var/incidents/`, alerte locale (journal et
  console ; ntfy au backlog, D13). Une annulation non confirmée est marquée comme telle et lève une
  alerte, dans un nombre d'essais borné par la cible.
- **Cible (D11)** : `kill_switch.target_seconds` = 5 s, fixée par Lucas le 20/10/2026. La durée va
  du déclenchement à l'état écrit, tous ordres annulés. `data_loss_timeout_seconds` reste
  `A_DEFINIR` jusqu'à une connexion continue.
- **Réarmement (D12)** : `cerveau rearm` refuse sans terminal interactif et sans phrase de
  confirmation, puis journalise `KILL` (« réarmement », acteur `lucas`). Une suppression manuelle
  du fichier est détectée et journalisée au lancement suivant.
- **Hooks** : ils refusent à Claude Code `cerveau rearm`, la suppression, le déplacement et la
  modification de `KILL`. La création reste permise, car elle arrête.

## Conséquences
- Seul Lucas sort d'un arrêt. Les hooks sont un confort ; la protection effective reste l'ACL
  Windows (ADR-003).
- **Tests** : durée sous la cible avec 1 000 ordres ouverts et un adaptateur lent ; réarmement
  refusé hors terminal interactif ; suppression manuelle détectée ; hooks.

## Mise en œuvre (21/10/2026)
`core/execution/kill_switch.py` et `cerveau kill` / `cerveau rearm` (`interfaces/cli/kill_switch.py`).

- **Ordre des effets** : fichier `KILL` d'abord (l'arrêt survit au processus), entrée `KILL`
  « déclenchement », courtier, carnet, rapport, état, entrée `KILL` « arrêt ». Rien n'interrompt
  l'arrêt : un journal qui refuse, un carnet illisible ou une configuration invalide deviennent une
  erreur du rapport et une sortie 1.
- **Courtier** : « tout annuler » (3 essais), relevé des ordres encore travaillés, puis annulation
  ordre par ordre (3 essais ; un refus n'est pas retenté). Passé la cible, plus aucun appel n'est
  tenté, sauf le premier ; chaque appel sauté est compté dans le rapport.
- **Carnet** : un seul passage à `ANNULEE`, en une transaction (ADR-032). Un ordre `VALIDEE` n'y
  passe que si le courtier a dit ne pas le travailler ; sinon son annulation reste non confirmée.
  Un ordre annulé chez le courtier mais absent du carnet, ou sans carnet lisible, lève une alerte.
- **Durée** : horloge monotone, de l'appel à `engage` à l'état écrit. Le démarrage de la commande
  n'est pas compté (B170) ; un appel au courtier en cours n'est pas coupé (B171).
- **Rapport** `var/incidents/AAAAMMJJTHHMMSSZ-<déclencheur>.md` : jamais écrasé (suffixes `-2` à
  `-999`). Journal et rapport ne portent que des nombres d'ordres, des identifiants et des types
  d'erreur : ni montant, ni texte du courtier (R5, R6).
- **État** `var/incidents/kill_switch.json` : il distingue un arrêt journalisé d'un fichier `KILL`
  créé ou supprimé à la main. `cerveau rearm` l'affiche (rapport, annulations non confirmées) avant
  de demander la phrase `REARMER`.
- **Pertes** : `loss_breaches` reprend les trois contrôles de pertes de la Porte (ADR-030) ; une
  propriété Hypothesis vérifie qu'ils se déclenchent ensemble. Une valeur inconnue lève une erreur au
  lieu de passer pour « pas de perte ». Le branchement à la valorisation et aux incidents vient avec
  la CLI paper.
- **Hooks Claude Code** : Claude Code peut arrêter CERVEAU, jamais le réarmer. `protect_paths`
  refuse Edit et NotebookEdit sur `KILL`, et Write dès qu'il existe. `guard_shell` refuse
  `cerveau rearm`, y compris par `uv run`, un interpréteur ou un shell imbriqué, et toute commande
  qui supprime, déplace ou réécrit `KILL` ou l'un de ses dossiers ; `git stash -u` ou `-a` est
  refusé quand `KILL` existe. Créer un `KILL` absent reste permis. Durcissement hors plan :
  `var/incidents/` est protégé en écriture, comme `var/audit/`.
- **Limites des hooks** : un script écrit puis lancé, ou un appel direct à `rearm()` dans du code
  de test, leur échappe ; un interpréteur dont la ligne cite `rearm` et `kill_switch`, `interfaces`
  ou `cerveau` est refusé (`python -m pytest tests/test_execution_kill_switch.py -k rearm` :
  passer par `uv run pytest`). La protection effective reste l'ACL (ADR-003, B173) et la phrase
  tapée dans un terminal interactif.
- **Mesure** : le test des 1 000 ordres, sur disque, avec le vrai journal et un courtier qui répond
  en 0,5 s après un premier délai dépassé, reste sous 5 s.
