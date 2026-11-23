# CERVEAU — la plateforme

Plateforme d'IA personnelle de son utilisateur, inspirée d'Aladdin et d'Aladdin Copilot : des outils
enregistrés et évalués (plugins MCP), regroupés par domaine (« packs »), derrière une gouvernance
déterministe qui filtre toute action. C'est un outil personnel d'aide à la décision, pas un service pour des
tiers (R16).

- Le plan à jour : [`docs/plans/plan-cerveau.md`](docs/plans/plan-cerveau.md) (le seul ; les anciens plans et
  comptes rendus sont dans [`docs/archive/`](docs/archive/)).
- Les consignes pour Claude Code et les règles R1 à R16 : [`CLAUDE.md`](CLAUDE.md).
- La spécification complète : [`docs/MEGA-PROMPT-CERVEAU.md`](docs/MEGA-PROMPT-CERVEAU.md).

## État au 21/11/2026

**Budget API à 0 €** (décision de l'utilisateur du 17/11/2026). Le chef d'orchestre LangGraph appelle l'API
à chaque étape : il est en place mais ne tourne pas. À sa place, Claude Code (sur l'abonnement de
l'utilisateur) dirigera la plateforme par le pont MCP `cerveau-plateforme` (ADR-069).

Ce qui marche aujourd'hui :
- la ligne de commande `cerveau` : vérification des réglages (`config check`), du journal d'audit
  (`audit verify`) et des manifestes de plugins (`registry validate`), finance (portefeuille, stratégies,
  Comité, compte paper), approbations, kill switch, rapports (hebdomadaire, sécurité du mois) ;
- 7 packs de domaine (`domain_packs/`) et leurs plugins (`plugins/`) : généraliste, finance, recherche,
  code, cyber (défensif), juridique français (lecture seule), business ;
- la gouvernance : moteur de politique, Porte de risque, kill switch, journal d'audit chaîné, approbations
  N3 par code à usage unique ; le mode live est désactivé (`config/live.yaml`, R3) ;
- les évals hors ligne et les red teams du banc hors ligne, en CI ;
- le pont MCP `cerveau-plateforme` (`interfaces/mcp_server/`) : fait et testé, **pas encore branché**
  (`.mcp.json` vide). Des corrections passent avant de le brancher (plan, bloc B).

Niveaux d'autonomie (`config/autonomy.yaml`) : N1 pour le généraliste, N0 partout ailleurs ; seul
l'utilisateur relève un plafond (`max_level`).

Ce qui est prévu (plan, blocs B à D) : deux dépôts privés (plateforme, projets) ; les corrections puis la
mise en service du pont ; une seule mémoire avec le plugin « cerveau » ; les réglages encore bloqués ; une
seule chaîne d'approbation ; une mesure réelle à 0 € par Claude Code ; puis la finance au niveau Aladdin,
le contenu et la vidéo, les clients, l'emploi, le PC et le réseau, le code et l'automatisation.

## Installer

Prérequis : [uv](https://docs.astral.sh/uv/) (il installe Python 3.12, exigé par `pyproject.toml`),
Node.js pour promptfoo et le bot Discord, Docker pour `infra/` (facultatif), gitleaks pour le scan des secrets.

```bash
make sync          # uv sync --frozen : dépendances exactes de uv.lock
```

Sous Windows, `make` se lance depuis Git Bash ou PowerShell ; chaque recette est une seule commande.

## Vérifier

```bash
make test          # pytest, dont les tests des hooks ; couverture complète exigée sur la Porte de risque
make lint          # ruff check + ruff format --check
make eval          # évals hors ligne (aucun appel payant)
make audit-verify  # chaîne du journal d'audit
make secrets-scan  # gitleaks sur l'historique git
make bot-test      # tests du bot Discord, sans réseau
make ci            # tout ce qui précède, et l'audit des dépendances
uv run cerveau --help
uv run cerveau config check                # après toute modification de config/*.yaml
uv run cerveau registry validate plugins/<nom>
```

`make eval-live` lance une campagne payante : seulement avec l'accord de l'utilisateur (aujourd'hui, budget
à 0 €). `make compose-config` demande `infra/.env`, créé par `uv run python infra/scripts/generate_secrets.py`.

## Carte du dépôt

```
CLAUDE.md, .mcp.json   consignes pour Claude Code ; serveurs MCP (vide tant que l'utilisateur n'en décide pas)
.claude/               réglages, hooks (garde-fous), agents de revue, skills
config/                réglages chargés et validés par core/config/ (live.yaml : à la main seulement)
governance/            approbations (à la main), kill switch
core/                  audit, politique, Porte de risque, exécution, finance, évals, orchestrateur…
plugins/               un dossier par serveur MCP
domain_packs/          un dossier par domaine (manifeste, prompts, sources, golden set)
evals/                 promptfoo, golden sets, comportements, red teams, rapports
interfaces/            CLI `cerveau`, API locale, dashboard, bot Discord, pont MCP
infra/                 docker-compose (profils core et observability), scripts Windows
docs/                  plan, ADR, backlog, modèle de menaces, licences, procédure live, archives
tests/                 pytest ; tests/hooks/ pour les garde-fous de Claude Code
```

## Gouvernance

Aucun chiffre décisionnel ne vient d'un modèle : il vient d'un outil qui l'a calculé (R1). Toute action
passe par le moteur de politique et, en finance, par la Porte de risque (R2) ; les actions externes,
irréversibles ou financières ne deviennent que des intentions, soumises à approbation selon le niveau du
domaine. Le kill switch arrête tout et passe avant le reste (R4). Chaque requête, décision et action entre
au journal d'audit chaîné par empreintes (R11). Le mode live reste désactivé : seul l'utilisateur le change,
à la main (R3, [`docs/procedure-live.md`](docs/procedure-live.md)). Les hooks de `.claude/hooks/` refusent
les actions interdites à Claude Code ; la protection effective de `config/live.yaml` est l'ACL Windows ou
les droits Unix (ADR-003).

## Documents

- Décisions d'architecture : [`docs/adr/`](docs/adr/) ; celles qui attendent l'utilisateur :
  [`docs/adr/A-VALIDER.md`](docs/adr/A-VALIDER.md).
- Ce qui reste à faire : [`docs/backlog.md`](docs/backlog.md) (chaque élément ouvert dit sa suite).
- Modèle de menaces : [`docs/threat-model.md`](docs/threat-model.md) ; licences : [`docs/licences.md`](docs/licences.md).
