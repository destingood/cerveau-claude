# Modèle de menace — CERVEAU

- Version : v1 (fin de phase 2)
- Date : 2026-10-19 (v0 : 2026-10-17, phase 0)
- Statut : proposé, à relire par Lucas ; mis à jour à chaque fin de phase (section 13). La v1
  rattrape la phase 1, que la v0 ne couvrait pas encore.

## 1. Périmètre de la v1
Couvert : le poste Windows 11 de Lucas, le dépôt `cerveau-plateforme`, Claude Code et ses
garde-fous (`.claude/`), la pile Docker locale (`infra/`), la CI GitHub Actions (pas encore
poussée). Depuis la phase 1 : l'orchestrateur (`core/orchestrator/`), le plugin de recherche web,
la pseudonymisation (ADR-010) et les évals. Depuis la phase 2 : le pack Finance en lecture (N0),
c'est-à-dire la base locale point-in-time (`core/finance/`, `var/finance/`), l'import des relevés
CSV de Lucas, la synchronisation BCE, cinq plugins MCP `finance_*` et le moteur de politique
(`core/policy/`).
Pas encore couvert, faute de code : mémoire, Porte de risque, broker, bot Discord, VPS. Les
menaces correspondantes sont listées avec les mesures prévues ; leur analyse sera détaillée dans
la phase qui les introduit.

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
| A8 | Données du portefeuille : base `var/finance/finance.db`, relevés importés, exports de plus-values | confidentialité ; intégrité point-in-time (R10) |
| A9 | Chiffres décisionnels (valeur, VaR, performance, plus-values) | exactitude et traçabilité jusqu'à l'outil qui les calcule (R1) |

## 3. Sources de menace
- Contenu externe : pages web, documents, courriels, réponses d'API, sorties d'outils (R5).
- Fichiers que Lucas importe (relevés de courtier, référentiel d'instruments) : leur texte libre
  est une donnée externe comme une page (R5).
- Fournisseurs de données de marché (BCE en phase 2) et de modèles (Anthropic) : erreur, retard,
  indisponibilité ; le fournisseur de modèle voit ce qui lui est envoyé.
- Claude Code et les futurs agents : erreur, excès de zèle, ou injection reçue par un outil.
- Dépendances, images Docker et actions GitHub tierces.
- Attaquant réseau (futur VPS, services exposés).
- Erreur de manipulation de Lucas.

## 4. Menaces
Échelle du risque résiduel : faible, moyen, élevé, ou « sans objet » quand le composant n'existe
pas encore.

| # | Menace | Scénario | Mesures en place (phase 2) | Mesures prévues | Résiduel |
|---|---|---|---|---|---|
| T1 | Injection indirecte | Un document lu demande d'exécuter une commande ou de modifier la config | R5 dans `CLAUDE.md` et `.claude/rules/` ; aucun serveur MCP pour Claude Code (`.mcp.json` vide) et outils MCP non listés refusés (B7) ; les hooks refusent les commandes dangereuses même si Claude est manipulé. Depuis la phase 1 : séparation lecteur / acteur (ADR-008), le lecteur n'a aucun outil ; détecteur de consignes sur les extraits et les titres (`core/guardrails/injection.py`), qui reconnaît aussi depuis la phase 2 les balises de rôle espacées (`[ SYSTEM ]`), `<<SYS>>` et les préfixes `System:` ou `Assistant:` (revue F1) ; liens hors sources retirés de la réponse ; red team `evals/redteam/` (60 cas, 0 violation R5 hors ligne) | Homoglyphes (« ignоre » écrit avec un о cyrillique, B101) ; ordre de bourse en clair (B99) ; mesure du modèle réel en campagne payante (B60) | moyen |
| T2 | Empoisonnement de la mémoire | Un fait faux ou une consigne cachée est mémorisé puis réutilisé | Sans objet (pas de mémoire) | Provenance obligatoire, quarantaine du contenu externe, revue des écritures, évals dédiées | sans objet |
| T3 | Fuite de secrets | Un secret part dans git, un log, un prompt ou la conversation | gitleaks en pre-commit et en CI (`--redact`) ; `.env*` et `secrets/` ignorés par git et interdits en lecture (règles + hooks) ; secrets générés sans affichage (testé) ; masquage dans le journal d'audit. Depuis la phase 1 : pseudonymisation Presidio de la question avant tout envoi au modèle (ADR-010) ; clés posées par Lucas en variables d'environnement utilisateur, jamais lues par Claude ; évals hors ligne lancées sans les clés | Docker secrets ou sops sur le VPS ; rotation | moyen |
| T4 | Compromission du VPS | Accès SSH, service exposé, sauvegarde lisible | Sans objet ; en local, ports publiés sur 127.0.0.1 uniquement | SSH par clé, pare-feu, mises à jour automatiques, réseau privé (`A_DEFINIR`), sauvegardes chiffrées hors VPS, restauration testée | sans objet |
| T5 | Erreur d'ordre | Ordre non voulu, mauvaise taille, mauvais compte | Aucun code d'ordre ; `live.yaml` : `enabled: false`, limites à 0 ; chargeur bloquant sur `A_DEFINIR` ; protection à trois niveaux (R3, ADR-003). Depuis la phase 2 : moteur de politique déterministe (`core/policy/`, ADR-022), finance en N0 : seules LECTURE et CALCUL passent ; toute demande d'ordre est refusée (suite `finance_n0`) ; la promotion N0 → N1 exige une campagne réelle et la signature de Lucas (D16) | Porte de risque, paper trading, kill switch (phase 3+) | faible |
| T6 | Dépendance malveillante | Paquet, image ou action compromis, dépôt homonyme | `uv.lock` + `uv sync --frozen` ; pip-audit en CI ; gitleaks téléchargé avec somme SHA-256 vérifiée ; licences relevées (`docs/licences.md`) ; dépôt `openbq-org/OpenBB` signalé comme probable homonyme | Épinglage par SHA et par digest, Dependabot ou Renovate, audit npm | moyen |
| T7 | Abus d'API | Clé volée ou boucle d'appels | Clés Anthropic, Brave et Langfuse hors du dépôt (variables d'environnement de Lucas) ; plafonds par requête (appels d'outils, jetons) ; `cerveau ask` réel bloqué tant que les budgets en € restent `A_DEFINIR` (R7) | Quotas côté fournisseur, limites de débit, clés à droits minimaux (trading seul, sans retrait) | moyen |
| T8 | Coûts incontrôlés | Boucle d'agent, éval trop large | Budgets journalier et mensuel `A_DEFINIR` : une requête réelle est refusée ; jetons par requête plafonnés (D4) ; évals réelles seulement sur accord de Lucas, campagne par campagne ; cache désactivé et versions figées pour promptfoo ; coût affiché par éval | Suivi Langfuse des coûts réels | faible |
| T9 | Claude Code (erreur ou injection) | Modifier `live.yaml`, lire un secret, `rm -rf`, `push --force`, réécrire le journal, baisser un seuil (R9) | Règles `deny` ; hooks en échec fermé, outils MCP compris (B7), testés dans `tests/hooks/` ; journal chaîné ; script d'ACL ; règles R3, R6, R9 dans `CLAUDE.md` | ACL appliquée par Lucas ; contrôle de propriétaire dans le chargeur ; décision sur la protection de `.claude/` | moyen |
| T10 | Falsification du journal d'audit | Entrée modifiée, supprimée ou fin de journal tronquée | Chaîne SHA-256 et `cerveau audit verify` ; écriture interdite à Claude dans `var/audit/` | Copie hors machine (hors VPS) et ancre externe du dernier hash | moyen |
| T11 | Injection par un fichier importé | Un relevé CSV porte une consigne dans un nom d'instrument, un secteur ou un libellé d'opération ; elle atteindrait les sorties des outils Finance, puis le planificateur | Chaque champ texte passe par le détecteur de consignes à l'import (`core/finance/model.py`) ; une seule ligne piégée fait refuser tout le fichier, avant toute écriture. Revue M1 : une consigne coupée entre deux champs ou deux lignes passait champ par champ ; les champs d'une ligne et les lignes d'un fichier sont désormais aussi lus à la suite, et la sortie entière d'un outil est relue par le détecteur avant d'atteindre le planificateur, qui reçoit un refus à la place (`core/orchestrator/planner.py`) ; red team `evals/redteam/injection_finance/fichiers_importes.yaml` (13 cas) | Hôte ou adresse cité sans tournure de consigne : accepté, seul le retrait des liens protège la réponse (B100) ; nom du fichier importé et texte des erreurs d'outil non contrôlés (revue F2, B102) ; ordre en clair (B99) ; homoglyphes (B101) | moyen |
| T12 | Chiffre faux ou non traçable | Le modèle invente, arrondit mal ou recopie de travers une valeur, une VaR ou une plus-value, et Lucas décide sur ce chiffre (R1) | Tout chiffre vient d'un outil déterministe ; chaque chiffre de la réponse est rapproché des sorties d'outils (`core/verification/figures.py`) et un chiffre orphelin est marqué `[VERIFICATION REQUIRED]` ; le journal garde la table chiffre → appel d'outil ; contrôle croisé de deux méthodes (D11) ; golden set Finance (60 cas) et suite `finance_tracabilite` | Sens d'un écart et unités (B92, B94) ; tolérance d'arrondi à resserrer | moyen |
| T13 | Fuite de point-in-time | Un calcul « au 31 mars » lit un prix, une correction ou un import enregistré après cette date : une décision passée paraît meilleure qu'elle ne l'était (R10) | Base bitemporelle, date de valeur et date d'enregistrement (ADR-012) ; lecture stricte à `as_of` ; heures de publication des fournisseurs (ADR-017) ; suite `finance_point_in_time` | Fraîcheur d'une série jugée à la date du score enregistré, pas à `as_of` (B105) | moyen |
| T14 | Source de marché fausse ou interdite | Série BCE erronée, en retard ou corrigée après coup ; source dont les CGU interdisent la collecte (R15) | Seule la BCE est activée ; yfinance désactivé (CGU de Yahoo, ADR-013) ; contrôles qualité des séries : trous, sauts, valeurs aberrantes, fraîcheur (ADR-016, D12) ; qualité basse signalée et plafonnée (suite `finance_qualite`) ; rapprochement des positions (ADR-018) | Second fournisseur pour recouper ; contrôles des séries de change et de taux (B85) | moyen |
| T15 | Fuite des données du portefeuille | Positions, montants et plus-values partent chez le fournisseur du modèle, dans une trace ou dans un fichier hors de `var/` | Base et exports sous `var/finance/`, ignoré par git ; export des plus-values écrit sous `var/finance/exports/` seulement ; traces Langfuse vers un serveur local uniquement. Revue M2 : dans une requête Finance, le planificateur tient à la fois les sorties d'outils et la recherche web, qu'un texte piégé pouvait pousser à chercher « positions FICT-GLOBEX 21,59 % » chez Brave ; une requête de recherche qui reprend un identifiant ou un nombre d'au moins 4 chiffres significatifs d'une sortie d'outil est refusée, n'est ni envoyée ni journalisée, et le refus est compté dans les évals (`evals/redteam/injection_finance/exfiltration_portefeuille.yaml`). Revue F3 : un refus de la base ne cite plus que la table et les clés, jamais les valeurs | Vue réduite ou pseudonymisée des sorties Finance pour le modèle, sans casser R1 (B95) ; limites connues du refus de recherche : un identifiant collé à un nombre (« FICT-GLOBEX-21-59 »), un montant arrondi ou écrit en lettres, un nombre de moins de 4 chiffres passent (B104) ; chemins libres de `--store` et `--journal` (revue F4, B103) | moyen |
| T16 | Formule exécutée à l'ouverture d'un export | Un nom de compte, de fichier ou d'instrument commençant par `=`, `+`, `-` ou `@` devient une formule quand Lucas ouvre `plus-values-AAAA.csv` dans un tableur (revue F2) | Toute cellule texte de l'export qui commence par l'un de ces caractères, une tabulation ou un retour chariot est préfixée d'une apostrophe ; les montants restent des nombres (`core/finance/capital_gains.py`, testé) | Contrôle du nom du fichier importé dès l'import (B102) | faible |

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
7. Outils hors matchers : les hooks surveillent `Bash`, `PowerShell`, `Edit`, `Write`,
   `NotebookEdit` et, depuis la phase 1, tout outil MCP (`^mcp__`, hook `guard_mcp.py`, B7). Ce
   hook refuse et journalise tout outil MCP non listé. La liste garde les outils de l'app sans
   effet hors de l'app et la lecture web dans le navigateur de l'app. Elle exclut le terminal de
   l'app et les serveurs d'aperçu, qui contourneraient `guard_shell`, ainsi que Chrome, le
   pilotage de l'ordinateur, les connecteurs, les tâches planifiées et la fusion automatique.
   Un serveur déclaré dans `.mcp.json` n'emprunte jamais un nom listé. Il reste trois limites :
   - `WebFetch` et `WebSearch` ne passent par aucun hook (B37) ;
   - `navigate` peut aussi faire sortir des données par l'URL : une page piégée peut faire charger
     une adresse qui porte le contenu du dépôt dans ses paramètres (revues M3 de phase 1 et de
     phase 2, B64, décision de Lucas) ;
   - un serveur MCP de portée utilisateur nommé comme un outil de l'app passerait.
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
- Images non épinglées par digest : `langfuse:4.63.0` et `langfuse-worker:4.63.0` (épinglées par
  étiquette, D12), MinIO Chainguard sans étiquette. MinIO amont archivé depuis 2026-04 : plus de
  correctifs (backlog).
- Traces (phase 1) : `cerveau ask` n'envoie de trace que vers un serveur Langfuse local
  (`localhost`, `127.0.0.1`, `::1`) et seulement si les deux clés sont présentes ; sans URL, le SDK
  viserait Langfuse Cloud, donc CERVEAU coupe les traces. Une trace contient le texte pseudonymisé
  envoyé aux modèles et les extraits web, jamais la réponse ré-identifiée.
- Redis 7.4 : licence RSALv2 / SSPLv1, sans effet sur un usage interne ; Valkey à évaluer.
- Inscriptions Langfuse ouvertes jusqu'à la création du premier compte par Lucas.
- Empreinte mémoire et comportement au démarrage non mesurés (Docker arrêté en phase 0).

## 7. Hypothèses
- Le poste de Lucas n'est pas compromis ; son compte Windows est protégé.
- GitHub, PyPI, npm, Docker Hub et le registre Langfuse servent les artefacts attendus.
- Lucas applique lui-même l'ACL (`infra/windows/protect-live.ps1`) et génère `infra/.env`.
- Aucun secret n'est collé dans la conversation avec Claude.
