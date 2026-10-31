## Compte rendu de mise en route — Phase 7 — 2026-10-29

Compte rendu de mise en route (plan : `docs/plans/phase-7-plan.md`, §12 point 10), au format de la
section 18. Le code de la phase 7 est livré ; le compte rendu de **fin** de phase arrivera au plus
tôt quatre semaines après que l'utilisateur aura lancé la planification (critère de sortie du §17 : rapports
générés automatiquement quatre semaines de suite, sans intervention).

### 1. Synthèse

La phase 7 livre la boucle d'auto-amélioration décidée par ADR-011, sous verrous :
- un registre des prévisions et leur calibration (Brier, ADR-064) ;
- une couche apprise `learned/` en liste fermée, une porte champion / challenger et le retour
  arrière (ADR-065) ;
- les rapports planifiés hebdomadaire et de sécurité, avec la preuve du critère de sortie
  (`cerveau report streak`, ADR-066) ;
- le rapport de promotion N3 → N4 et la rétrogradation automatique (ADR-067) ;
- la dette de sûreté B292, B200, B230, B316 et la garde de non-régression de la politique étendue
  à `code` et `business`.

Rien n'est mis en service : les seuils de la porte (D5) et les budgets (D1) valent `A_DEFINIR`, et
une mise en ligne exige des évals réelles (D4). Le live reste `enabled: false`, aucune autonomie
n'est relevée, aucune campagne payante n'a tourné.

### 2. Livré

| Lot | ADR | Pièces | Commande |
|---|---|---|---|
| 7.1 Prévisions et calibration | 064 | `core/learning/forecasts.py` (ajout seul, résolution après l'échéance, R10), `calibration.py` (Brier, Murphy, fiabilité, erreur des estimations, dérive) | `cerveau forecast add · resolve · list · calibration` |
| 7.2 Apprentissage | 065 | `core/learning/layer.py` (liste fermée, `LockedCoreError`), `patterns.py` (défenses contre l'empoisonnement), `gate.py` (jeu tenu à l'écart de 20 %, D6), `champion.py` (pile de promotions, retour arrière, surveillance) | `cerveau learn status · gate · patterns · promote · rollback · watch` |
| 7.3 Rapports planifiés | 066 | `core/reports/weekly.py`, `core/reports/security.py`, alerte `rapport_planifie_en_echec`, `infra/windows/install-schedule.ps1` | `cerveau report weekly · security · streak` |
| 7.4 Critères N4 | 067 | `core/governance/promotion_report.py` (B220), bornes de `PromotionN3N4` (B248), `var/governance/demotions.jsonl`, déclencheur `nightly_eval_failure` | `cerveau promotion report finance --to N4` |
| Dette de sûreté | — | B292 (option prudente : `decide` plafonne au `max_autonomy_level` du manifeste), B200 et B230 (7e condition de la garde live : tout ordre réel refusé faute de Porte live, B353), B316 (porte de couverture), garde de non-régression étendue à `code` et `business` | — |
| Évals | — | comportements `apprentissage` (10 cas), red team `injection_learning` (13 cas), exécutés sur le code réel de la boucle, sans modèle, dans un home temporaire | `make eval` |

**Écart au plan** : le script de planification est dans `infra/windows/` (à côté de
`protect-live.ps1`), pas dans `infra/scripts/` (ADR-066). Les commits 2 à 9 du plan (§12) ont été
regroupés en six commits atomiques, chacun avec `make ci` vert.

**Commits** : `2957fcd` (plan) à ce compte rendu, sur `main`, publiés par une branche et une pull
request sur `destingood/cerveau-claude`, jamais poussés directement sur `main`.

### 3. Tests et évals

Mesures du dernier `make ci` (arbre du commit des correctifs de la revue de sécurité), comparées à la fin de la
phase 6.

| Contrôle | Fin de phase 6 | Mise en route de la phase 7 | Seuil | Résultat |
|---|---|---|---|---|
| Tests | 7 334 | 7 591 (6 ignorés) | vert | ✅ |
| Couverture (porte) | 6 867 instructions, 1 308 branches | 9 354 instructions, 1 920 branches | 100 % | ✅ |
| Lint | 554 fichiers | 575 fichiers | 0 | ✅ |
| Comportements | 202/202 | 212/212 | 100 % | ✅ |
| Golden | 305/305 | 305/305 ; sourçage 72/72 | 100 % hors ligne | ✅ |
| Injection | 172/172 | 185/185 | 0 violation | ✅ |
| promptfoo | 2/2 | 2/2 | vert | ✅ |
| Journal d'audit | 156 entrées | 163 entrées | OK | ✅ |
| Secrets (gitleaks) | aucune fuite | aucune fuite à chaque commit | 0 | ✅ |

**Évals d'apprentissage** : 23 cas, tous réussis hors ligne. Ils vérifient qu'une note de retour
reste une donnée (R5), que rien n'est mis en service et que le noyau, les golden sets et les seuils
restent intacts (R9, contrôle par empreintes avant et après), que le verdict est calculé par le
code et jamais recopié (R1), que la promotion reste bloquée tant que ses seuils valent `A_DEFINIR`
(R7), que les prévisions ne se résolvent qu'après leur échéance (R10) et que le journal reste
chaîné (R11). Aucune suite existante n'a été modifiée (R9).

**Non mesuré** : la qualité d'une leçon réelle (rédacteur par LLM non branché, B348), le gain d'un
challenger sur des évals réelles, la calibration de prévisions réelles (aucune encore), la
régularité du planificateur (le compteur `streak` part de zéro).

### 4. Écarts et ADR produits

**ADR produits** : ADR-064 à ADR-067, au statut « proposé ».

| ADR | Objet | À relire en priorité |
|---|---|---|
| 064 | Registre des prévisions et calibration | seuils `calibration` à `A_DEFINIR` |
| 065 | Couche apprise et porte champion / challenger | liste fermée, mise en ligne automatique seulement en réel (D4) |
| 066 | Rapports planifiés | tâches du Planificateur, pas de déclencheur mensuel |
| 067 | Promotion N3 → N4 et rétrogradation | déclencheurs non branchés (B349 à B352) |

**Revues** :
- `security-reviewer` (exigé par le §17) : aucun bloquant. Trois constats importants, corrigés :
  liaison de chaque rapport d'évals au condensat de la couche apprise et de la configuration
  (`promote` refuse un rapport non lié) ; types de motif et packs en liste fermée, chaîne du journal
  vérifiée avant toute récolte ; rétrogradation hebdomadaire idempotente (une fois par déclencheur).
  Constats mineurs corrigés : écriture par fichier temporaire neuf, racine `learned/` liée refusée,
  section écrite avant le journal, chemin cité et `uv run --frozen` dans le script du Planificateur,
  `promotion_margin` strictement positive. Restes au backlog : B355 à B358.
- `risk-gate-auditor` (lot 7.4), `quant-reviewer` (Brier) et `eval-engineer` (red team) : non
  lancés, faute d'accord pour des sous-agents (coût en tokens) ; **autorevue** seulement, à
  confirmer par ces agents si l'utilisateur le demande.

### 5. Risques ouverts et dette technique

- **B353, obligatoire avant tout client live** : la Porte live alimentée par `config/live.yaml`
  n'existe pas ; d'ici là, la 7e condition de la garde refuse tout ordre réel.
- **B292, option prudente retenue** : le plafond du manifeste s'applique aux plugins passés par
  l'adaptateur MCP ; les agents in-process ne passent pas par `decide`.
- **B262** : test instable non reproduit (10 passes isolées, 3 CI complètes), entrée gardée ouverte.
- **B346** : l'extraction automatique des prévisions d'une réponse n'est pas faite ; une prévision
  s'enregistre par `cerveau forecast add`.
- **Déclencheurs de rétrogradation** : seul `nightly_eval_failure` est branché ; les autres
  attendent des seuils ou des outils (B349 à B352).
- **Planification** : une tâche supprimée ne produit rien ; seul l'arrêt du compteur `streak` le
  montre. Les alertes restent coupées tant que ntfy et Discord ne sont pas activés.
- **B354** : le README de la red team ne décrit ni `injection_code` ni `injection_business`.
- **B356, obligatoire avant toute promotion réelle** : `cerveau eval` ne sait pas encore évaluer
  un challenger sur sa propre couche ; sans cela, aucun rapport de challenger ne porte le condensat
  exigé et `promote` refuse.
- **B355** : un rapport d'évals réécrit à la main avec les bons condensats reste accepté (ni
  signature ni chaînage au journal).
- **B357** : `var/governance/demotions.jsonl` n'est pas dans le contrôle des droits Windows.
- **B358** : un `ref.db` apparaît à la racine du dépôt ; sa source reste à trouver.
- Modèle de menaces v10 : T44 (empoisonnement de l'apprentissage), T45 (rapport planifié silencieux
  ou trompeur), T46 (promotion N4 ou rétrogradation contournée), actif A17.

### 6. Coûts de la phase

- **LLM, code de CERVEAU** : 0 €. Aucune campagne réelle, aucune clé lue.
- **LLM, sessions Claude Code** : non relevé.
- **Infrastructure** : locale ; 0 €.
- **À venir** : rédaction de challengers et red team réelle hebdomadaire, non estimées, plafonnées
  par les budgets (`A_DEFINIR`).

### 7. Décisions demandées à l'utilisateur

**[QUESTIONS DE CLARIFICATION]**

| # | Décision | Options | Ma recommandation |
|---|---|---|---|
| 1 | Lancer la planification (D2) | lancer `infra/windows/install-schedule.ps1` / attendre | le lancer maintenant : les quatre semaines du critère de sortie ne commencent qu'à ce moment |
| 2 | Budgets quotidien et mensuel en € (D1) | montants | à fixer : ils bloquent toute promotion et toute campagne réelle (R7) |
| 3 | Seuils de la porte et de la calibration (D5) | `promotion_margin`, `min_held_out_cases`, `rollback_window_days`, `min_support`, `max_feedback_per_user`, `calibration` | à fixer ; sans eux la porte reste « non conclu » et la dérive n'est pas surveillée |
| 4 | Alertes ntfy ou Discord | activer / laisser coupées | activer : un rapport en échec doit se voir |
| 5 | ADR-064 à ADR-067 | accepter / demander des changements | relire 065 et 067 d'abord |
| 6 | Revues par agents (`risk-gate-auditor`, `quant-reviewer`, `eval-engineer`) | lancer / s'en tenir à l'autorevue | lancer `risk-gate-auditor` sur le lot 7.4 au moins |
| 7 | B353, Porte live | l'écrire en phase 8 / plus tard | avant toute idée de client live |

Commande à lancer par l'utilisateur, dans PowerShell, depuis la racine du dépôt :

```powershell
powershell -ExecutionPolicy Bypass -File infra\windows\install-schedule.ps1
```

### 8. Optimisation & Prochaines Étapes

1. Lancer la planification, puis suivre `uv run cerveau report streak` chaque semaine.
2. Fixer D1 et D5 ; ensuite seulement, une première campagne réelle de challenger, sur accord.
3. Brancher les déclencheurs restants (B349 à B352) quand leurs seuils existent.
4. Compléter le README de la red team (B354) et l'extraction des prévisions (B346).
5. Compte rendu de fin de phase 7 après quatre rapports hebdomadaires consécutifs en `ok`.
