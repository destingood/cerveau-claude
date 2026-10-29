# Plan — Phase 4 : paper trading (N2) : Porte de risque, intentions d'ordre, exécution simulée, kill switch : F7, F8, F2

Date : 20/10/2026 · Statut : **validé par l'utilisateur le 20/10/2026**, avec les recommandations D1 à D25 du §14.

## 0. En une phrase

Toute action financière devient une intention d'ordre structurée (Annexe C.2). Des outils déterministes la dimensionnent et la chiffrent ; le moteur de politique puis la Porte de risque la filtrent. La Porte est une fonction pure, couverte à 100 % et éprouvée sur au moins 10 000 cas générés. L'intention ne s'exécute que sur un compte paper simulé. Une machine à états journalisée suit chaque ordre. Une réconciliation a lieu après chaque exécution et chaque jour. Un kill switch, mesuré sous sa cible, coupe tout. La finance reste en N0 tant que l'utilisateur n'a pas signé sa promotion.

## 1. Vérifié aujourd'hui (20/10/2026)

| Sujet | Constat | Source |
|---|---|---|
| NautilusTrader 1.231.0 (installé) | Un adaptateur `sandbox` existe : `SandboxExecutionClient` enveloppe un `SimulatedExchange` dans un client d'exécution **live**. Paramètres : `venue`, `starting_balances`, `oms_type` (NETTING par défaut), `account_type` (MARGIN par défaut), `bar_execution`… Il tourne dans un nœud live et reçoit ses prix du bus de messages, donc d'un client de données live (IB, Databento…). Déduit de la lecture du code : à confirmer dans la documentation avant tout usage. | `.venv/…/nautilus_trader/adapters/sandbox/execution.py` et `config.py` |
| Intégrations NautilusTrader | Interactive Brokers est marqué `stable` (« Stable feature set and API ») ; aucune page « Sandbox » dans la liste. | [nautilustrader.io/docs/latest/integrations](https://nautilustrader.io/docs/latest/integrations/) |
| UUID v7 (Annexe C.2) | Python 3.12 ne fournit que `uuid1`, `uuid3`, `uuid4` et `uuid5` ; `uuid7` arrive en 3.14. Le projet est en 3.12 (ADR-001). | [docs.python.org/3.12/library/uuid](https://docs.python.org/3.12/library/uuid.html) |
| Hypothesis | `max_examples` n'a pas de plafond. Hypothesis s'arrête plus tôt s'il trouve un bogue ou s'il a épuisé l'espace de recherche. `derandomize=True` rend un essai rejouable ; le profil `ci` s'active avec la variable `CI` ; `database=None` désactive la base d'exemples. | [hypothesis.readthedocs.io, API](https://hypothesis.readthedocs.io/en/latest/reference/api.html) |
| Couverture | `pytest-cov>=7.1.0` est déjà une dépendance. `[tool.coverage.run]` a `branch = true` : le 100 % portera sur les lignes et les branches. | `pyproject.toml` |
| ib_async | Non vérifié aujourd'hui : utile seulement si D1 retient un compte paper IBKR. [VERIFICATION REQUIRED : PyPI et dépôt GitHub, version, licence, maintenance] | — |
| ntfy | Absent du dépôt : aucun service dans `infra/`, aucune configuration. | dépôt |
| État du dépôt | `core/risk_gate/` est vide. Le moteur de politique n'accorde que `auto` (LECTURE partout, CALCUL en finance). La finance est en N0. Le kill switch est un fichier lu à 6 endroits. Le journal accepte déjà `ORDER_STATE`, `KILL` et l'acteur `risk_gate`. | `core/policy/engine.py`, `core/audit/chain.py` |
| Limites paper | Les 9 valeurs de `risk_limits.paper.yaml` sont `A_DEFINIR`, sans borne ni unité (B156). Il manque des limites que le §8.4 exige : pays, devise, perte glissante, ordres par jour, univers autorisé. | `config/risk_limits.paper.yaml`, `core/config/loader.py` |
| Frais | `trading_costs` est entièrement `A_DEFINIR` (D13 de la phase 2). Le contrôle « Cash, frais compris » refuse donc tout. | `config/risk.yaml` |
| Cours | Aucune source de cours d'actions n'est active (seule la BCE l'est). Les cours stockés sont des clôtures, avec un volume facultatif. | `config/data_sources.yaml`, `core/finance/model.py` |
| Autonomie | `autonomy.yaml` n'a pas de règle `N1_to_N2`. Le §8.3 exige pourtant une red team du domaine réussie. | `config/autonomy.yaml` |
| Hooks | Les hooks protègent `governance/approvals` et `var/audit`, pas `governance/kill_switch`. Claude Code pourrait donc supprimer `KILL`, c'est-à-dire réarmer. | `.claude/hooks/_common.py`, `guard_shell.py` |

## 2. Périmètre et étiquettes de parité (§10.1, §17)

| Fonction | Livré en phase 4 | Étiquette (spec) | Reporté |
|---|---|---|---|
| F7 Pré-trade et conformité | Porte de risque déterministe (§8.4) ; contrôles de `compliance.yaml` | `[Parité]` pour des règles personnelles | — |
| F8 Gestion d'ordres | intention C.2 ; machine à états ; carnet d'ordres append-only ; adaptateur paper ; glissement mesuré | `[Approximation]` | adaptateur live (phase 5, désactivé) ; IBKR paper selon D1 |
| F2 Portefeuille | réconciliation du compte paper après chaque exécution et chaque jour | `[Parité]` | API IBKR en lecture |
| Autonomie | `proposition` en N1 et `paper` en N2 pour FINANCIERE ; règle N1→N2 ; rétrogradation automatique | — | promotion signée par l'utilisateur après campagne réelle et red team |
| Kill switch (§8.5) | fichier, `cerveau kill`, dépassement de limite, données perdues, incident d'exécution | — | `/kill` Discord (phase 5) ; ntfy selon D13 |

Critères de sortie du §17 :

- tests de propriétés : aucune intention hors limites acceptée sur au moins 10 000 cas générés ;
- couverture de `core/risk_gate` à 100 % ;
- kill switch sous sa cible ;
- tests de chaos réussis : coupure réseau, données manquantes, ordre en double, réponse broker incohérente ;
- en plus : tests verts, évals au-dessus des seuils, revues, compte rendu du §18.

## 3. Intention d'ordre (Annexe C.2) — ADR-029

Nouveau paquet `core/execution/` : intentions, machine à états, carnet, adaptateurs, réconciliation.

- **Schéma** `OrderIntent` (Pydantic strict, figé). Il reprend les champs de C.2.
  - `environment` : `Literal["paper"]`. Un `live` est refusé par le schéma lui-même en phase 4.
  - `order_type` : `LIMIT` ; `time_in_force` : `DAY`.
  - `quantity` : un entier > 0. `limit_price` : un `Decimal` > 0.
  - `price_source` et `sizing_source` citent l'appel d'outil journalisé (`TOOL_CALL`) qui a produit le chiffre (R1).
  - `rationale` : thèse, catalyseur, invalidation, horizon, confiance dans [0, 1]. Tous sont obligatoires et bornés.
- **`intent_id`** : UUID v7 (RFC 9562), écrit dans le projet, environ 15 lignes testées, plutôt qu'une dépendance (§1, D8).
- **Origine** : C.2 ne prévoit que `committee_record_id`. J'ajoute `origin {kind: strategy | committee, id}` ; `committee_record_id` devient facultatif (D8).
- **Rédacteur d'intentions** (`IntentDrafter`, B108), déterministe. Le modèle ne fournit que les textes de justification ; aucun chiffre (R1).
  - Il part d'ordres cibles : `target_orders` d'une stratégie, ou les opérations d'une proposition de rééquilibrage.
  - Il prend le dernier cours connu à la décision (R10). Le prix limite vaut ce cours ± `limit_offset_pct`, qui doit rester dans la bande de prix (D17).
  - Il cite les appels d'outil sources.
- **Sources d'intentions** (D7) :
  1. Une stratégie au statut `candidate` (ADR-027, approuvée par l'utilisateur). Elle rejoue chaque jour le même code qu'en backtest (§10.6), ce qui mesure l'écart paper/backtest exigé pour N2→N3. La fiche gagne `invalidation` et `horizon_jours` ; les empreintes du code et de la grille sont inchangées.
  2. Une décision « agir » du Comité sur une proposition de rééquilibrage. `ManagerDecision` gagne `catalyseur`, obligatoire pour « agir ». Les quantités viennent de `rebalance.py`, jamais du modèle. Ce changement de prompt relance les évals (R9).

## 4. Moteur de politique : `proposition` en N1, `paper` en N2 — ADR-030

- **Décisions accordées.** `PHASE_DECISIONS` gagne `proposition` et `paper`, pour `FINANCIERE` et pour le domaine `finance` seulement.
  - `proposition` : l'intention est rédigée et passe la Porte, mais n'est jamais envoyée.
  - `paper` : l'intention est envoyée au seul adaptateur paper.
  - `simule` (IRREVERSIBLE) et `brouillon` restent refusés : aucun composant ne les porte.
- **`PolicyDecision`.** Elle remplit enfin `risk_gate` (C.4). La propriété `allowed` est remplacée par un effet explicite : `executer`, `proposer`, `paper` ou `refuser`. Aucun chemin ne devient plus permissif : un test le vérifie sur toute la matrice.
- **Niveau.** La finance **reste en N0** : en pratique, tout est refusé tant que l'utilisateur ne promeut pas le domaine. Le paper ne tourne qu'en tests, en évals et en développement, avec un niveau injecté dans les tests.
- **Règle N1→N2** ajoutée à `autonomy.yaml` (D9) : conditions N0→N1, plus red team Finance à 0 violation, plus signature manuelle. `cerveau promotion check` la vérifie. C'est un durcissement, pas un assouplissement.
- **Rétrogradation automatique** (D10). `execution_incident`, `limit_breach` et `drawdown_breach` déclenchent le kill switch, qui force N0, avec un réarmement manuel. Les trois autres déclencheurs vont au backlog.
- **Défense en profondeur.** Si `live.yaml` dit `enabled: true`, tout est refusé avec une alerte, car aucun adaptateur live n'existe en phase 4.

## 5. Porte de risque (§8.4) — ADR-031

- **Forme.** `core/risk_gate/` expose une fonction pure : `evaluate(intent, snapshot, limits, costs, compliance) -> RiskGateResult`.
  - Pas de modèle, pas d'I/O, pas d'horloge implicite.
  - Le `snapshot` est figé à la décision : positions, cash, attributs des instruments, derniers cours datés, volume moyen, état du marché, pertes, drawdown, ordres récents, `intent_id` déjà vus, blocage de réconciliation.
  - Montants en `Decimal`.
- **Tous les contrôles sont évalués**, sans court-circuit, pour que chaque refus donne toutes ses raisons.
- **Une limite inconnue, une donnée absente ou une exception donnent `REFUSE`** (R7, échec fermé).

| Contrôle | Règle | Donnée |
|---|---|---|
| Schéma | intention valide ; `intent_id` jamais vu (idempotence) | carnet d'ordres |
| Univers | instrument dans `universe` ; marché ouvert à la séance d'exécution ; volume moyen ≥ minimum | `exchange_calendars`, base Finance |
| Taille | ordre, position, secteur, pays et devise après l'ordre ≤ limites, en % du capital de référence | instruments, positions |
| Pertes | perte du jour, perte glissante et drawdown courant ≤ limites | compte paper |
| Prix | ordre limite ; prix dans la bande autour du dernier cours ; cours pas plus ancien que la fraîcheur admise | base Finance |
| Cash | cash suffisant, frais et change compris | `trading_costs` |
| Interdits | ni levier, ni vente à découvert, ni dérivés (`allow`) | limites, instrument |
| Fréquence | ordres par heure et par jour ≤ limites | carnet d'ordres |
| Justification | thèse, catalyseur, invalidation, horizon et source de taille présents | intention |
| Conformité | exclusions personnelles ; crypto refusée tant que la plateforme est `A_VERIFIER` | `compliance.yaml` |
| Réconciliation | aucun écart ouvert (§8) | carnet d'ordres |

- **`REDUIT`** (D6) n'est possible que sur les contrôles de taille et de cash.
  - La quantité baisse jusqu'au plus grand entier qui respecte toutes les limites. Les autres contrôles ne réduisent jamais.
  - Une quantité réduite à 0 donne `REFUSE`.
  - Le résultat garde la quantité demandée et la quantité retenue.
- **Limites** (B156, D3 à D5).
  - Bornes : `PositiveFloat` pour le capital, `gt=0, le=100` pour les `*_pct`.
  - Unité écrite dans les docstrings.
  - Nouvelles clés, toutes à `A_DEFINIR` : `max_country_pct`, `max_currency_pct`, `max_orders_per_day`, `max_rolling_loss_pct`, `rolling_loss_sessions`, `avg_volume_sessions`, `universe`.
  - Le Comité vérifie la présence de toutes les clés (B155).
- **Journal.** Une entrée `POLICY` au format C.4, avec `checks[{name, ok, value, limit}]`, acteur `risk_gate`.

## 6. Machine à états et carnet d'ordres (F8, §10.8) — ADR-032

| De | Vers | Événement |
|---|---|---|
| INTENTION | VALIDEE | politique `paper` + Porte `ACCEPTE` ou `REDUIT` |
| INTENTION | REJETEE | politique ou Porte en refus |
| VALIDEE | ENVOYEE | accusé de réception de l'adaptateur |
| VALIDEE | ANNULEE | kill switch avant l'envoi |
| ENVOYEE | PARTIELLE | exécution partielle |
| ENVOYEE, PARTIELLE | EXECUTEE | quantité entièrement exécutée |
| ENVOYEE, PARTIELLE | ANNULEE | fin de séance (DAY), annulation, kill switch |
| ENVOYEE | REJETEE | refus de l'adaptateur |

- **États terminaux** : EXECUTEE, ANNULEE et REJETEE sont immuables. Toute autre transition est un incident d'exécution (§9).
- **Carnet** : `var/paper/orders.db` (SQLite), tables append-only des intentions, des transitions et des exécutions. L'unicité de `intent_id` est imposée par la base. L'identifiant client de l'ordre vaut `intent_id`, ce qui empêche un renvoi en double.
- **Journal** : chaque transition donne une entrée `ORDER_STATE` avec `intent_id`, état, raison et SHA-256 de l'intention. Les montants restent dans le carnet, comme pour le portefeuille.
- **Glissement réel** : écart entre le prix d'exécution et le prix de décision, en points de base, par ordre et cumulé.

## 7. Adaptateur paper — ADR-033

- **Interface** `BrokerAdapter` (Protocol) : `submit`, `cancel`, `cancel_all`, `open_orders`, `account_snapshot`, `fills_since`. Le reste du code ne connaît que cette interface.
- **Simulateur maison** `PaperSimulator` (D1, D2) :
  - Compte séparé (§8.6) dans `var/paper/`, en euros. Le capital initial est le capital de référence. Positions longues seulement.
  - Un ordre limite DAY est envoyé après la clôture de t et traité sur la séance t+1, comme le modèle d'exécution du backtest (D6 de la phase 3).
  - Il est exécuté à la clôture de t+1 si le cours atteint la limite. Le glissement défavorable (`slippage_bps`) est plafonné au prix limite.
  - Si la quantité dépasse la participation maximale au volume de la séance, l'exécution est partielle (`PARTIELLE`) et le reste est annulé en fin de séance.
  - Les frais et le change viennent de `trading_costs`.
  - Le simulateur tient **sa propre comptabilité**, séparée du livre de CERVEAU : la réconciliation a ainsi un sens.
- **Recoupement indépendant** (B154). Les exécutions paper sont rejouées dans NautilusTrader avec **son modèle de commission natif**, et le cash et les positions finaux sont comparés (tolérance D12 de la phase 3). Les tests marquent un refus explicite au-delà de `MONEY_MAX` (B122).
- **Pas de réseau.** Le simulateur lit la base Finance point-in-time ; en tests et en développement, il lit le marché synthétique de la phase 3. Un paper sur cours réels attend une source de cours (D19).
- **IBKR paper** : backlog sauf choix contraire en D1. Il faut le compte de l'utilisateur, TWS ou Gateway, des clés hors dépôt, et Claude Code n'active jamais un compte broker.

## 8. Réconciliation (F2, §10.3)

- **Quand** : après chaque exécution et chaque jour, à la fin de `cerveau paper run`.
- **Quoi** : le livre de CERVEAU, rejoué des exécutions paper par `core/finance/portfolio` (mêmes décimales exactes que le portefeuille réel), comparé au relevé de l'adaptateur.
  - Positions : égalité exacte.
  - Cash : égalité au centime.
- **Écart** : alerte, entrée au journal, blocage des nouvelles intentions (contrôle « Réconciliation » de la Porte).
  - Le blocage se lève après une réconciliation propre **et** un acquittement de l'utilisateur en terminal interactif (D14).
  - Un écart qui vient d'un incident d'exécution déclenche aussi le kill switch (D15).

## 9. Kill switch (§8.5) — ADR-034

- **Déclencheurs en phase 4** :
  - le fichier `governance/kill_switch/KILL` ;
  - `cerveau kill` ;
  - un dépassement de perte du jour, de perte glissante ou de drawdown, constaté à la valorisation ;
  - des données perdues : le cours attendu de la séance est absent au lancement, au-delà de `max_staleness_sessions` (D11) ;
  - un incident d'exécution : transition illégale, exécution d'un ordre inconnu, quantité exécutée supérieure à l'ordre, cash négatif.
- **Effets** :
  - annulation des ordres ouverts ;
  - blocage des nouvelles intentions ;
  - N0 forcé ;
  - entrée `KILL` au journal ;
  - rapport d'incident en français dans `var/incidents/` ;
  - alerte (D13).
  - Si une annulation n'est pas confirmée, l'ordre est marqué « annulation non confirmée » et une alerte est levée, dans un nombre d'essais borné par la cible.
- **Cible** : `kill_switch.target_seconds`, recommandé à 5 s (D11). La durée est mesurée du déclenchement jusqu'à tous les ordres annulés et l'état écrit. Un test l'impose avec 1 000 ordres ouverts et un adaptateur lent.
- **Réarmement par l'utilisateur seulement** (D12).
  - `cerveau rearm` refuse sans terminal interactif et sans phrase de confirmation, puis journalise `KILL` (« réarmement », acteur `owner`).
  - Une suppression manuelle du fichier est détectée et journalisée.
  - Les hooks refusent à Claude Code `cerveau rearm` ainsi que la suppression, le déplacement ou la modification de `KILL`. C'est un durcissement : la création reste permise, car elle arrête.

## 10. Boucle paper, CLI et rapport quotidien

- **`cerveau paper run --date AAAA-MM-JJ`**, idempotent par date (une séance déjà traitée ne fait rien). Dans l'ordre :
  1. kill switch ;
  2. fraîcheur des données ;
  3. exécutions de la séance ;
  4. réconciliation ;
  5. valorisation, pertes et drawdown, avec déclencheurs éventuels ;
  6. sources d'intentions, rédacteur, politique, Porte ;
  7. envoi.
- **Autres commandes** :
  - `cerveau paper status`, `cerveau paper orders`, `cerveau paper report --date` ;
  - `cerveau kill`, `cerveau rearm`, `cerveau status` (B54, partiel).
- **Lancement** : manuel en phase 4. Le Planificateur de tâches Windows reste un choix de l'utilisateur, documenté (D24).
- **Rapport quotidien** (Markdown, français, `var/paper/reports/`). Chaque chiffre cite son outil (R1). Il donne :
  - ordres et états ;
  - exécutions, glissement et frais ;
  - résultat du jour et cumulé ;
  - drawdown ;
  - usage de chaque limite ;
  - refus de la Porte avec leurs raisons ;
  - réconciliation et état du kill switch ;
  - écart paper/backtest de la stratégie ;
  - compteurs N2→N3 : semaines, décisions, incidents.
- **Outils du Copilot** : aucun nouvel outil (R13). Le modèle n'appelle jamais l'adaptateur (R2).

## 11. Évaluations

| Élément | Contenu | Critère mesuré |
|---|---|---|
| Porte de risque (déterministe) | ≥ 10 000 cas générés, oracle indépendant, distribution des résultats publiée | 0 intention hors limites acceptée |
| Golden Finance | Les cas existants restent **inchangés**. Environ 10 cas s'ajoutent : intention, refus expliqué, catalyseur du Comité. Je les rédige, tu les valides, puis ils sont gelés (R9). | taux ≥ 0,85 |
| Comportements `finance_execution` | ≥ 8 cas : aucune quantité ni aucun prix inventés (R1) ; raisons de la Porte citées ; jamais « ordre envoyé » en N0 ou N1 ; mention « paper » ; refus de contourner la Porte ; limite dépassée fixée par le cas (B135) | 100 % |
| Red team `injection_execution` | ≥ 10 cas : une page externe pousse à relever une limite, contourner la Porte, envoyer un ordre, désactiver ou réarmer le kill switch. Le détecteur reconnaît « Porte de risque », « limites », « kill switch » (B125). C'est la red team de domaine que demande N1→N2. | 0 violation |
| Chaos | les quatre familles du §12 | 100 % |

- **Hors ligne (CI)** : modèles scriptés, fixtures, marché synthétique.
- **Réel** : bloqué tant que les budgets restent `A_DEFINIR`, puis lancé avec ton accord à chaque campagne.

## 12. Tests (aucun réseau en CI)

- **Porte, propriétés Hypothesis** : profil `gate` avec `max_examples=10_000`, `derandomize=True`, `deadline=None`, `database=None`.
  - Accepté ou réduit ⇒ toutes les limites sont respectées après l'ordre, vérifié par un **oracle écrit à part**, sans réutiliser le code de la Porte.
  - Réduit ⇒ quantité strictement plus petite.
  - Resserrer une limite ne transforme jamais un refus en acceptation.
  - Une limite inconnue ⇒ refus.
  - Même entrée ⇒ même sortie.
  - Les générateurs visent les bords des limites. Un seuil minimal de cas acceptés est imposé pour que la propriété ne soit pas vraie à vide ; la distribution est mesurée et publiée.
- **Couverture** : `pytest --cov=core/risk_gate --cov-branch --cov-fail-under=100`, ajouté à `make ci`.
- **Machine à états** : `RuleBasedStateMachine`. Aucune transition illégale, quantité exécutée ≤ quantité de l'ordre, un état terminal reste terminal.
- **Chaos** (critère du §17) :
  - **Coupure réseau** : l'adaptateur lève un délai dépassé à l'envoi, à l'annulation ou au relevé. Aucun état n'est perdu, rien n'est renvoyé sans idempotence, la réconciliation tranche.
  - **Données manquantes** : cours absent ou trop ancien ⇒ refus et déclencheur de perte de données.
  - **Ordre en double** : le même `intent_id` deux fois ⇒ un seul ordre.
  - **Réponse incohérente** : exécution d'un ordre inconnu, quantité excessive, position ou cash divergents ⇒ incident, kill switch, blocage.
- **Kill switch** : durée sous la cible avec 1 000 ordres ouverts ; réarmement refusé hors terminal interactif.
- **Hooks** : nouvelles protections de `KILL` et de `cerveau rearm`.
- **Dette du backlog** : limites à 0, négatives ou à 500 (B164) ; toutes les clés (B155).
- **Durée** : `make test` dure 171 s aujourd'hui. Le surcoût des 10 000 cas sera mesuré ; seule la propriété principale est à 10 000, les autres à 1 000.

## 13. Nouvelles dépendances

Aucune. Hypothesis, pytest-cov et NautilusTrader sont déjà là ; l'UUID v7 est écrit dans le projet. Si D1 retient IBKR : ib_async ou l'adaptateur IB de NautilusTrader, vérifiés avant l'ajout (source-verifier, pip-audit, licence).

## 14. Décisions demandées à l'utilisateur

| # | Décision | Options | Ma recommandation |
|---|---|---|---|
| D1 | Adaptateur paper | simulateur maison recoupé par NautilusTrader / `sandbox` NautilusTrader (exige un flux de données live, donc un compte) / compte paper IBKR | **Simulateur maison**, sans réseau et testable en chaos. IBKR paper au backlog, jusqu'à ce que tu ouvres le compte et choisisses la source de données. |
| D2 | Modèle d'exécution paper | clôture t+1 si la limite est atteinte, glissement plafonné à la limite, participation maximale au volume / exécution complète toujours | **Le premier**, participation de 5 % du volume de la séance (hypothèse de simulation). |
| D3 | Valeurs des limites paper (B.3) | à toi | Proposition, à valider ou changer : capital fictif 10 000 € ; ordre 5 % ; position 10 % ; secteur 30 % ; pays 60 % ; devise 50 % ; perte du jour 2 % ; perte glissante 5 % sur 20 séances ; drawdown 10 % ; 10 ordres par heure et 20 par jour ; bande de prix 2 % ; volume moyen 100 000 titres sur 20 séances ; univers : la liste que tu fixes. Tant que tu n'as pas tranché, tout reste `A_DEFINIR` et la Porte refuse tout (R7). |
| D4 | Unité des pourcentages (B156) | pourcentage (5 = 5 %) / fraction (0,05) | **Pourcentage**, comme `commission_pct` ; bornes `gt=0, le=100`. |
| D5 | Limites manquantes du §8.4 | les ajouter à `A_DEFINIR` / les ignorer | **Les ajouter** : pays, devise, ordres par jour, perte glissante et sa fenêtre, fenêtre du volume, univers. |
| D6 | `REDUIT` | permis sur la taille et le cash, à la baisse, en titres entiers / jamais (seulement accepté ou refusé) | **Permis** comme le prévoit le §8.4, avec les deux quantités journalisées. |
| D7 | Sources d'intentions | stratégie `candidate` + Comité « agir » sur un rééquilibrage / stratégie seule / Comité seul | **Les deux**. La stratégie mesure l'écart paper/backtest ; le Comité ferme B108. `ManagerDecision` gagne `catalyseur`. |
| D8 | Écarts à C.2 | `origin {kind, id}` ajouté, `committee_record_id` facultatif ; UUID v7 maison / C.2 à la lettre | **Ajout de `origin`**, écrit dans l'ADR-029 ; UUID v7 maison testé contre la RFC 9562. |
| D9 | Politique | `proposition` (N1) et `paper` (N2) pour FINANCIERE en finance ; règle `N1_to_N2` ajoutée / inchangée | **Accorder et ajouter la règle**. La finance reste en N0 jusqu'à ta signature. |
| D10 | Rétrogradation automatique | incident d'exécution, dépassement de limite et de drawdown ⇒ kill switch / journal seul | **Kill switch**. Dérive de calibration, échec d'éval nocturne et SLO de plugin au backlog. |
| D11 | Cible et perte de données | cible en s ; définition de la perte de données | **5 s** (cible de la spec). Perte de données : cours de la séance attendue absent au lancement (`max_staleness_sessions: 1`). `data_loss_timeout_seconds` reste `A_DEFINIR` pour une future connexion continue. |
| D12 | Réarmement | `cerveau rearm` interactif + suppression manuelle, hooks durcis / suppression manuelle seule | **Les deux chemins pour toi**, journalisés ; Claude Code refusé par les hooks. |
| D13 | Alertes | journal + console + rapport d'incident ; ntfy au backlog (B46) / ntfy auto-hébergé dès la phase 4 | **Local en phase 4** ; ntfy avec Discord en phase 5. |
| D14 | Fin d'un écart de réconciliation | réconciliation propre + ton acquittement / levée automatique à la réconciliation propre suivante | **Réconciliation propre + acquittement**. |
| D15 | Incident d'exécution | kill switch / blocage seul | **Kill switch**. |
| D16 | Compte paper | euros, capital initial = capital de référence, positions longues, sans levier | **Oui**. |
| D17 | Prix limite rédigé | dernier cours ± `limit_offset_pct` (nouveau `config/execution.yaml`, ≤ bande de prix) | **0,5 %**, `A_DEFINIR` jusqu'à ta réponse. |
| D18 | Exclusions personnelles | `[]` vaut « aucune exclusion » / `[]` bloque tant que tu ne confirmes pas | **Confirmer `[]`** si tu n'as aucune exclusion ; sinon donne la liste. |
| D19 | Décisions ouvertes qui bloquent un paper réel | frais (D13 de la phase 2), source des cours (D1 de la phase 2), budgets (D19 de la phase 2) | Les trancher quand tu peux. En attendant, tout est livré et mesuré sur le marché synthétique ; un paper réel reste bloqué (R7). |
| D20 | Dette du backlog incluse | à choisir | **Incluses** : B155, B156, B154, B122, B135, B164 (limites), B146, B149, B125, B157, B158. **Reportées** : B159, B160, B161, B162, B163. |
| D21 | Revues | `security-reviewer` + `risk-gate-auditor` + `quant-reviewer` / sans `quant-reviewer` | **Les trois** : la règle `finance.md` impose les deux dernières dès que la Porte et la politique changent. |
| D22 | Nouveaux cas golden | environ 10 nouveaux cas, les existants inchangés / aucun | **Oui** : je les rédige, tu les valides, puis ils sont gelés. |
| D23 | Couverture 100 % | lignes + branches de `core/risk_gate`, imposée dans `make ci` / lignes seules | **Lignes + branches**. |
| D24 | Lancement de la boucle | manuel / Planificateur de tâches réglé par toi | **Manuel** en phase 4, procédure écrite pour le planificateur. |
| D25 | Points prévus avant la phase 4 | premier push et CI GitHub (B14) ; campagne réelle | **Le push et la CI d'abord, faits par toi** : je ne pousse jamais. La campagne réelle suit les budgets (D19). |

## 15. Hors périmètre → `docs/backlog.md`

- Bot Discord, `/kill`, approbations, adaptateur live désactivé, procédure live, tableau de bord : phase 5.
- IBKR paper, ib_async, API IBKR en lecture (sauf D1).
- ntfy (D13).
- Données intrajournalières, connexion continue, `data_loss_timeout_seconds`.
- Vente à découvert, levier, dérivés, crypto (ccxt).
- Déclencheurs de rétrogradation : dérive de calibration, éval nocturne, SLO de plugin.
- Fiscalité des opérations paper.
- B159 à B163.

## 16. Commits atomiques (en anglais, `make ci` vert à chaque étape)

1. `docs: add the validated phase 4 plan`
2. `docs(adr): add ADR-029 to ADR-034 (order intent, policy levels, risk gate, order state machine, paper adapter and reconciliation, kill switch)`
3. `feat(config): bound paper limits, add the missing section 8.4 limits and execution parameters (B156)`
4. `fix(committee): check every paper limit key (B155, B164)`
5. `feat(execution): add the order intent schema and a tested UUIDv7 generator`
6. `feat(risk-gate): add the deterministic risk gate with an independent oracle and 10 000 generated cases`
7. `ci: require full line and branch coverage of core/risk_gate`
8. `feat(policy): grant proposition at N1 and paper at N2 for finance and record the risk gate result`
9. `feat(config): add the N1 to N2 promotion rule and check it in cerveau promotion check`
10. `feat(execution): add the order state machine and the append-only order book`
11. `feat(execution): add the broker adapter protocol and the paper simulator`
12. `test(execution): cross-check paper fills with NautilusTrader's native commission model (B154, B122)`
13. `feat(execution): reconcile after each fill and daily, blocking new intents on any gap`
14. `feat(governance): add cerveau kill and rearm, automatic triggers and incident reports`
15. `feat(hooks): refuse rearming or removing the kill switch from Claude Code`
16. `feat(committee): require a catalyst for a decision to act`
17. `feat(execution): draft intents from candidate strategies and committee decisions (B108)`
18. `feat(cli): add cerveau paper run, status, orders, report and cerveau status (B54)`
19. `test(execution): add chaos tests (network cut, missing data, duplicate order, incoherent broker)`
20. `fix: log interrupted committee roles, verify the audit chain on show, flag guardrail bypass phrasing (B146, B149, B125)`
21. `fix(finance): use split and dividend data known at decision time (B157, B158)`
22. `test(evals): add execution golden cases, behaviour and red-team suites (B135)`
23. `docs: update licences, threat model and backlog`
24. `docs: add the phase 4 report`

## 17. Coût estimé (non mesuré)

- **Développement** : aucun appel payant, tout passe hors ligne.
- **Boucle paper** : 0 € par jour pour une stratégie, qui est déterministe. Une séance réelle du Comité coûte 0,30 à 0,80 $ (estimation de la phase 3).
- **Campagne d'évals réelle** : environ 30 nouveaux cas plus les suites existantes, que le changement du prompt du Comité oblige à relancer, soit **20 à 35 $** (estimation).
- **Données et bibliothèques** : 0 €.

## 18. Exécution

- **Où** : dans cette session, ouverte dans `cerveau-plateforme`, où les hooks du projet sont chargés.
- **Ordre** :
  1. décisions ;
  2. lecture de la documentation (NautilusTrader 1.231 : exécution simulée et modèles de commission ; Hypothesis : tests à états) ;
  3. ADR et configuration ;
  4. dette B155, B156, B164 ;
  5. intention et Porte de risque, avec la couverture ;
  6. politique ;
  7. machine à états, carnet, simulateur, recoupement ;
  8. réconciliation et kill switch ;
  9. rédacteur, Comité, CLI ;
  10. chaos ;
  11. reste de la dette ;
  12. évals ;
  13. revues (`security-reviewer`, `risk-gate-auditor`, `quant-reviewer` selon D21) ;
  14. rapport du §18.
- **Fin de phase** : je m'arrête et j'attends `GO PHASE 5`.
