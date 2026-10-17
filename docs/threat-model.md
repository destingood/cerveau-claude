# Modèle de menace — CERVEAU

- Version : v0 (phase 0)
- Date : 2026-10-17
- Statut : proposé, à relire par Lucas ; mis à jour à chaque fin de phase (section 13)

## 1. Périmètre de la v0
Couvert : le poste Windows 11 de Lucas, le dépôt `cerveau-plateforme`, Claude Code et ses
garde-fous (`.claude/`), la pile Docker locale (`infra/`, non démarrée en phase 0), la CI GitHub
Actions (pas encore poussée).
Pas encore couvert, faute de code : orchestrateur, mémoire, plugins MCP, broker, bot Discord, VPS.
Les menaces correspondantes sont listées avec les mesures prévues ; leur analyse sera détaillée
dans la phase qui les introduit.

## 2. Actifs
| Id | Actif | Propriété à protéger |
|---|---|---|
| A1 | Capital et comptes broker (futurs) | aucune action réelle sans N4 et sans Lucas |
| A2 | Secrets : `infra/.env`, futures clés API et broker | confidentialité |
| A3 | Journal d'audit `var/audit/` | intégrité, append-only (R11) |
| A4 | Gouvernance : `config/live.yaml`, `config/*.yaml`, `governance/approvals/` | intégrité ; seul Lucas modifie |
| A5 | Mémoire et données personnelles (futures) | intégrité, confidentialité |
| A6 | Budgets API et machine | disponibilité, coût maîtrisé |
| A7 | Code, CI, dépendances | intégrité de la chaîne de livraison |

## 3. Sources de menace
- Contenu externe : pages web, documents, courriels, réponses d'API, sorties d'outils (R5).
- Claude Code et les futurs agents : erreur, excès de zèle, ou injection reçue par un outil.
- Dépendances, images Docker et actions GitHub tierces.
- Attaquant réseau (futur VPS, services exposés).
- Erreur de manipulation de Lucas.

## 4. Menaces
Échelle du risque résiduel : faible, moyen, élevé, ou « sans objet » quand le composant n'existe
pas encore.

| # | Menace | Scénario | Mesures en place (phase 0) | Mesures prévues | Résiduel |
|---|---|---|---|---|---|
| T1 | Injection indirecte | Un document lu demande d'exécuter une commande ou de modifier la config | R5 dans `CLAUDE.md` et `.claude/rules/` ; aucun serveur MCP (`.mcp.json` vide) ; les hooks refusent les commandes dangereuses même si Claude est manipulé | Séparation lecteur / acteur (CaMeL), schémas de sortie, moteur de politique déterministe, évals `evals/redteam/` (phase 1+) | moyen |
| T2 | Empoisonnement de la mémoire | Un fait faux ou une consigne cachée est mémorisé puis réutilisé | Sans objet (pas de mémoire) | Provenance obligatoire, quarantaine du contenu externe, revue des écritures, évals dédiées | sans objet |
| T3 | Fuite de secrets | Un secret part dans git, un log, un prompt ou la conversation | gitleaks en pre-commit et en CI (`--redact`) ; `.env*` et `secrets/` ignorés par git et interdits en lecture (règles + hooks) ; secrets générés sans affichage (testé) ; masquage dans le journal d'audit | Docker secrets ou sops sur le VPS ; Presidio avant tout envoi distant ; rotation | moyen |
| T4 | Compromission du VPS | Accès SSH, service exposé, sauvegarde lisible | Sans objet ; en local, ports publiés sur 127.0.0.1 uniquement | SSH par clé, pare-feu, mises à jour automatiques, réseau privé (`A_DEFINIR`), sauvegardes chiffrées hors VPS, restauration testée | sans objet |
| T5 | Erreur d'ordre | Ordre non voulu, mauvaise taille, mauvais compte | Aucun code d'ordre ; `live.yaml` : `enabled: false`, limites à 0 ; chargeur bloquant sur `A_DEFINIR` ; protection à trois niveaux (R3, ADR-003) | Porte de risque, niveaux N0–N4, paper trading, kill switch | faible |
| T6 | Dépendance malveillante | Paquet, image ou action compromis, dépôt homonyme | `uv.lock` + `uv sync --frozen` ; pip-audit en CI ; gitleaks téléchargé avec somme SHA-256 vérifiée ; licences relevées (`docs/licences.md`) ; dépôt `openbq-org/OpenBB` signalé comme probable homonyme | Épinglage par SHA et par digest, Dependabot ou Renovate, audit npm | moyen |
| T7 | Abus d'API | Clé volée ou boucle d'appels | Aucune clé ni appel de modèle en phase 0 (éval témoin : fournisseur `echo`) | Quotas, limites de débit, clés à droits minimaux (trading seul, sans retrait) | sans objet |
| T8 | Coûts incontrôlés | Boucle d'agent, éval trop large | Aucun appel payant ; cache désactivé et versions figées pour promptfoo | Budgets par jour et par tâche (`A_DEFINIR`), suivi Langfuse, coût affiché par éval | sans objet |
| T9 | Claude Code (erreur ou injection) | Modifier `live.yaml`, lire un secret, `rm -rf`, `push --force`, réécrire le journal, baisser un seuil (R9) | Règles `deny` ; hooks en échec fermé, 270 tests ; journal chaîné ; script d'ACL ; règles R3, R6, R9 dans `CLAUDE.md` | ACL appliquée par Lucas ; contrôle de propriétaire dans le chargeur ; décision sur la protection de `.claude/` | moyen |
| T10 | Falsification du journal d'audit | Entrée modifiée, supprimée ou fin de journal tronquée | Chaîne SHA-256 et `cerveau audit verify` ; écriture interdite à Claude dans `var/audit/` | Copie hors machine (hors VPS) et ancre externe du dernier hash | moyen |

## 5. Contournements connus des garde-fous de Claude Code
Les hooks et les règles `deny` sont un confort (R3) : ils arrêtent les erreurs et les injections
simples, pas un adversaire déterminé. Limites connues à ce jour :
1. Scripts lancés : `bash script.sh`, `pwsh -File`, `python fichier.py` ne sont pas analysés. Un
   script écrit dans un dossier libre peut ensuite écrire un chemin protégé.
2. Commandes construites dynamiquement (variables, substitutions, encodage) : l'analyse reconnaît
   `eval`, `Invoke-Expression`, `bash -c` et `pwsh -Command`, pas tous les montages possibles.
3. Git : une sous-commande qui nomme un chemin protégé est refusée, mais `git stash`, `git pull`
   ou `git checkout <branche>` sans chemin peuvent changer `live.yaml` par effet de bord.
4. Archives : `tar`, `unzip` et `Expand-Archive` sont refusés près d'un chemin protégé, mais une
   archive préparée ailleurs et extraite par un script échappe à l'analyse.
5. Dossier parent : renommer ou supprimer `config/` contourne l'ACL du seul fichier (ADR-003).
6. Docker : `docker compose config` sans `--quiet` affiche les secrets interpolés depuis
   `infra/.env` ; `docker inspect` et `docker compose exec … env` aussi. La cible
   `make compose-config` utilise `--quiet`.
7. Outils hors matchers : les hooks surveillent `Bash`, `PowerShell`, `Edit`, `Write` et
   `NotebookEdit`. Un futur serveur MCP aura besoin de son propre contrôle.
8. `.claude/` n'est pas protégé : Claude peut modifier `settings.json` ou un hook. La modification
   reste visible dans `git diff` ; la protéger est une décision de Lucas.
9. Portée : les réglages du projet ne s'appliquent que si la session démarre dans le dépôt.
10. Disponibilité : sans `python` dans le PATH, ou si le dossier courant est inconnu, tout est
    refusé (échec fermé voulu).

## 6. Infrastructure locale (`infra/docker-compose.yml`)
- Ports publiés sur 127.0.0.1 seulement (PostgreSQL 5432, Langfuse 3000, MinIO 9090) ; console
  MinIO non publiée ; ClickHouse et Redis sans port publié.
- Télémétrie Langfuse coupée ; secrets obligatoires (`${VAR:?}`), le Compose refuse de démarrer
  sans eux ; base et rôle `langfuse` séparés de la base `cerveau`.
- Images non épinglées par digest : `langfuse:4`, `langfuse-worker:4`, MinIO Chainguard sans
  étiquette. MinIO amont archivé depuis 2026-04 : plus de correctifs (backlog).
- Redis 7.4 : licence RSALv2 / SSPLv1, sans effet sur un usage interne ; Valkey à évaluer.
- Inscriptions Langfuse ouvertes jusqu'à la création du premier compte par Lucas.
- Empreinte mémoire et comportement au démarrage non mesurés (Docker arrêté en phase 0).

## 7. Hypothèses
- Le poste de Lucas n'est pas compromis ; son compte Windows est protégé.
- GitHub, PyPI, npm, Docker Hub et le registre Langfuse servent les artefacts attendus.
- Lucas applique lui-même l'ACL (`infra/windows/protect-live.ps1`) et génère `infra/.env`.
- Aucun secret n'est collé dans la conversation avec Claude.
