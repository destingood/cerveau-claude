# ADR-066 — Rapports planifiés : hebdomadaire, sécurité mensuelle et série de semaines

- Statut : proposé
- Date : 2026-10-29
- Phase : 7 (lot 7.3 du plan validé le 2026-10-29)

## Contexte
La phase 7 se clôt après quatre semaines de rapports sans intervention (§17). Il faut donc des
rapports produits seuls, vérifiables et sans chiffre de LLM (R1), et une preuve du critère.
L'utilisateur a choisi le Planificateur de tâches Windows (D2). Un rapport qui échoue en silence ne prouve
rien : l'échec doit se voir (R11, ADR-038 pour les alertes). Les sorties des outils de sécurité
peuvent citer ce qu'elles trouvent, y compris un secret : elles ne doivent pas être recopiées (R6).

Fait vérifié le 29/10/2026 sur ce poste (Windows 11, `Get-Command`) : le module PowerShell
ScheduledTasks offre des déclencheurs `-Once`, `-Daily`, `-Weekly`, `-AtLogOn` et `-AtStartup`,
pas de déclencheur mensuel ; `New-ScheduledTaskSettingsSet -StartWhenAvailable` existe.

## Options
1. **Rapports écrits par l'orchestrateur (LLM)** : lisibles, mais contraires à R1 et payants.
2. **Rapports déterministes en Python, planifiés par le Planificateur Windows** (retenue) :
   chaque chiffre vient d'un fichier ou du journal, gratuit, testable avec une horloge figée.
3. **Planification par un service Docker (cron)** : indépendant de Windows, mais demande Docker
   allumé et un accès au dépôt monté ; écartée par D2.

## Décision
- `core/reports/weekly.py` construit le rapport de la dernière semaine ISO complète avant
  l'exécution (bornes à minuit local, chaque borne avec son propre décalage horaire) : un
  rattrapage tardif couvre la même semaine. Sections : évals hors ligne (suites, groupes par pack,
  seuils, coûts du run), calibration (Brier, prévisions échues), coûts réels du mois (journal, D9),
  journal (événements, requêtes, refus, incidents, alertes, apprentissage), porte d'apprentissage
  (promotions en service). Statut `echec` si une source est illisible, si le rapport d'évals est
  absent ou antérieur à la semaine, ou si un seuil est manqué ; les raisons sont écrites.
- Chaque exécution ajoute une entrée `scheduler` / `DECISION` avec la semaine, le résultat et
  l'empreinte SHA-256 du rapport. `cerveau report streak` compte les semaines consécutives dont
  la dernière exécution est `ok` : c'est la preuve du critère de clôture.
- `core/reports/security.py` lance des commandes fixes, sans shell : gitleaks, pip-audit,
  npm audit, `audit verify`, `config check`, tests des hooks, et les dépendances dépassées
  (informatif). Seuls le code de sortie et le nombre de lignes sont gardés (R6) ; un outil absent
  est un échec. L'écart au modèle de menaces liste les ADR postérieurs au dernier qu'il cite.
- Un rapport en échec sort avec le code 1 et envoie l'alerte `rapport_planifie_en_echec`
  (gravité 4) sur les canaux configurés.
- `infra/windows/install-schedule.ps1` (à côté de `protect-live.ps1`, et non dans
  `infra/scripts/` comme le prévoyait le plan) installe deux tâches hebdomadaires, lancées par
  l'utilisateur : lundi 07:00 évals hors ligne puis rapport ; lundi 07:30 rapport de sécurité seulement si
  celui du mois manque, faute de déclencheur mensuel.

## Conséquences
- Plus simple : un rapport se rejoue à l'identique ; aucun appel payant (les évals planifiées
  sont hors ligne ; la red team réelle reste sur accord, D8).
- Limites : les SLO des plugins ne sont pas mesurés (« non mesuré » dans le rapport, R7) ; les
  tâches ne tournent que si l'utilisateur est connecté (pas de mot de passe enregistré), le rattrapage
  couvre l'arrêt du PC ; la série suppose une horloge système juste.
- Réversible : `install-schedule.ps1 -Remove` supprime les tâches ; les rapports restent.
- Backlog : B349 (SLO des plugins mesurés dans le rapport hebdomadaire).
