# ADR-027 — Registre des stratégies, promotion manuelle, rapport standard et outil `strategy_lab`

- Statut : accepté (D13 et D14 du plan de phase 3, validées par l'utilisateur le 19/10/2026 ; l'approbation
  dans `governance/approvals/` et le comptage des essais du Copilot ci-dessous sont soumis à sa
  relecture au compte rendu de phase 3)
- Date : 2026-10-19
- Phase : 3

## Contexte
Le §10.6 interdit de promouvoir une stratégie qui échoue au protocole (ADR-026), et le §17 demande
un rapport de stratégie standard. Le Copilot doit aussi pouvoir répondre à « cette stratégie
passe-t-elle le protocole ? ». R13 limite un domaine à 3 à 5 outils, sauf si les évals justifient
une capacité de plus.

Faits relevés dans le code :

- Le registre (`core/registry/manifest.py`) exige `readOnlyHint` et `idempotentHint` pour la classe
  `CALCUL`. Un outil de calcul ne peut donc pas écrire dans le journal des essais.
- L'adaptateur MCP journalise chaque appel (`TOOL_CALL`) avec ses arguments, dans le journal chaîné.
- `governance/approvals/**` est réservé à l'utilisateur, et les hooks en refusent l'écriture à Claude Code.

## Options
1. Pas de registre : la stratégie est un module, et rien ne contrôle sa promotion.
2. Statut dans le seul YAML du registre : Claude Code pourrait l'écrire lui-même.
3. **Registre déclaratif**, avec une promotion approuvée par l'utilisateur dans `governance/approvals/`, et
   contrôlée par `config check`.

## Décision
Option 3.

- **Registre** : un fichier `domain_packs/finance/strategies/<id>.yaml` par stratégie, validé par
  Pydantic. Il contient :
  - l'hypothèse et la règle en français ;
  - le module (`core/finance/research/strategies/<id>.py`) ;
  - la grille et ses contraintes, l'univers et la fréquence ;
  - le statut : `recherche` pour une stratégie neuve, ou `candidate`.
- **Empreintes** : SHA-256 du source du module (`code_sha256`) et de la grille canonique
  (`grille_sha256`). Toute modification de l'un ou de l'autre fait une nouvelle version, qui
  invalide le verdict.
- **Promotion (D14)** : seul l'utilisateur l'accorde, en écrivant à la main
  `governance/approvals/strategies/<id>.yaml`, avec l'empreinte du rapport, les deux empreintes
  ci-dessus et la date. `cerveau strategy show <id>` affiche le texte à recopier ; aucune commande ne
  l'écrit. `cerveau config check` refuse le statut `candidate` dans les cas suivants :
  - pas d'approbation ;
  - empreintes de code ou de grille différentes de l'état actuel ;
  - quand la base locale existe : rapport absent, verdict autre que `reussi`, données
    synthétiques ou frais fictifs, ou empreinte du rapport absente du journal d'audit.

  En phase 3, aucune stratégie ne peut être promue : les frais réels sont encore `A_DEFINIR`.
- **Rapport standard** :
  - `cerveau strategy protocol <id>` écrit `var/finance/research/reports/<id>-<date>.md` en
    français, et le même contenu en `.json` ;
  - les neuf sections du plan (§8), avec un avertissement en tête quand les données sont
    synthétiques ;
  - chaque nombre porte l'identifiant de l'outil qui l'a calculé (R1) ;
  - l'empreinte SHA-256 du JSON est inscrite au journal d'audit par une entrée `DECISION`, ce qui
    rend une retouche détectable.
- **Outil `strategy_lab` (D13)** : sixième outil Finance, dans le nouveau plugin
  `finance_research` (MCP stdio, `CALCUL`, lecture seule).
  - Il n'utilise que le moteur maison, sans vectorbt (R14) ni NautilusTrader.
  - Ses entrées sont une stratégie du registre, `as_of` et un mode :
    - `signaux` : poids cibles et niveaux des indicateurs à `as_of`, par `PointInTimeView` ;
    - `backtest` : un point de la grille, sur une fenêtre bornée par `config/research.yaml` ;
    - `protocole` : le dernier verdict enregistré, sans relancer le protocole.
  - Chaque sortie est un résumé borné, jamais la courbe entière (B96). Elle rappelle :
    - le verdict du protocole, ou son absence : un bon résultat d'une stratégie qui n'est pas
      `reussi` est présenté comme tel ;
    - le nombre d'essais de la famille ;
    - l'étiquette des données (synthétiques ou réelles) et celle des frais (fictifs ou réels).
  - Le mode `backtest` sur données réelles est refusé tant que les frais sont `A_DEFINIR` (R7).
- **Essais du Copilot** : l'outil reste en lecture seule. `cerveau strategy protocol` relit les
  entrées `TOOL_CALL` du journal d'audit pour `strategy_lab` en mode `backtest`. Il les reporte dans
  `research_trials` avec l'origine `copilote` et la référence de l'entrée, une seule fois par
  entrée. Le Sharpe y est recalculé par le moteur, avec le code courant. N reste un compte brut,
  rendu inaltérable par la chaîne du journal.
- **R13** : la capacité est justifiée par le livrable F5 du §17.
  - Le routage, c'est-à-dire la part des cas golden où le planificateur choisit le bon outil, est
    mesuré avant et après l'ajout.
  - Hors ligne, la mesure couvre la sélection déterministe des outils. En réel, elle attend la
    première campagne autorisée par l'utilisateur.
  - Si le routage baisse sur les 60 cas existants, l'outil sort du pack, et le rapport le dit.

## Conséquences
- **Phase 4** : le paper n'acceptera que des stratégies `candidate`, ce qui suppose un protocole
  réussi sur données et frais réels.
- **Mise à jour** : une approbation périmée (code modifié) fait échouer `config check`. L'utilisateur
  relance alors le protocole, ou repasse la stratégie en `recherche`.
- **Tests** :
  - promotion refusée sans approbation, avec une empreinte périmée, et sur un verdict synthétique ;
  - serveur `finance_research` en client/serveur en mémoire ;
  - report unique des essais du Copilot ;
  - sorties bornées.
