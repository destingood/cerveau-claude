# ADR-074 — Les golden sets passés dans Claude Code, jugés par un autre modèle

- Statut : proposé
- Date : 2026-11-28
- Phase : plan du cerveau, Bloc B, étape B4, point 3 (« les jeux de cas passés dans Claude Code, un
  autre modèle juge », validé par l'utilisateur) ; complète l'ADR-009 (juge) et l'ADR-069

## Contexte
Le budget API est de 0 € depuis le 17/11/2026. Les golden sets (`domain_packs/*/evals/golden.jsonl`,
779 cas avec ceux des plugins) tournent soit hors ligne (modèles scriptés : on mesure les couches
déterministes, pas un modèle), soit en réel par l'orchestrateur LangGraph et le juge du routeur
(ADR-009), qui exigent une clé d'API : aucune campagne réelle n'a jamais eu lieu (B60). Claude Code,
sur l'abonnement, peut répondre et juger. Choix de l'utilisateur : la réponse est écrite par le modèle
de la session, la note par un sous-agent d'un autre modèle Claude, pour qu'un modèle ne se note
jamais lui-même ; les chiffres restent contrôlés par le code (R1).

Faits vérifiés le 28/11/2026 dans la documentation de Claude Code (code.claude.com/docs, pages
*Subagents*, *Skills*, *Run Claude Code programmatically*) :
- un sous-agent `.claude/agents/<nom>.md` a un frontmatter `model` (`sonnet`, `opus`, `haiku`,
  `fable`, un identifiant complet ou `inherit`), `tools`, `disallowedTools`, `maxTurns`,
  `omitClaudeMd` ; il démarre dans un contexte neuf, sans la conversation qui l'a lancé ;
- **le paramètre `model` passé à l'invocation l'emporte sur le frontmatter** : la séparation des
  modèles tient donc aussi à la discipline de la session (limite ci-dessous) ;
- une skill `.claude/skills/<nom>/SKILL.md` accepte `disable-model-invocation: true` et
  `$ARGUMENTS` ; `claude -p` (mode non interactif) utilise l'abonnement hors `--bare`.

## Options
1. **Attendre un budget API** pour `cerveau eval --live`. Écartée : décision de l'utilisateur (0 €).
2. **La session répond et se juge.** Écartée : un modèle qui se note est biaisé (ADR-009, limite
   connue du juge actuel déjà).
3. **La session répond, un sous-agent d'un autre modèle juge, le code contrôle et note.** Retenue.
4. **Le juge lancé par le code (`claude -p --model haiku`)**, qui capterait le verdict sans que la
   session le touche. Plus sûr, mais hors du choix validé et dépendant des conditions d'usage de
   l'abonnement en mode non interactif (A_VERIFIER, déjà noté à l'ADR-069) : à décider (B367).

## Décision
Option 3, en trois commandes `cerveau evals`, une skill et deux sous-agents :

- **`exporter --pack <p> --modele-reponse <id>`** écrit `var/evals/claude-code/<run>/` : par cas,
  le texte exact que reçoit le modèle qui répond (prompt système de l'annexe D rendu pour le pack,
  couche apprise comprise ; consignes du banc `core/evals/prompts/reponse_claude_code.md` ; question ;
  pages du cas numérotées, en `<donnees_externes>`, R5), jamais ce qui est attendu. Seuls les
  `golden.jsonl` sont lus : un fichier de cas candidats n'est jamais passé. Un cas qui demande les
  outils, le Comité, la recherche approfondie, une boucle, des sources de plugin, ou dont les
  attentes sont écrites par le code (signalements, mentions G9) est **exclu avec sa raison** ; un cas
  à données personnelles aussi (la session les lirait en clair, R6). Les 37 cas Généraliste sont
  exportables ; 21 de Recherche, 8 de Cyber, 7 de Finance, 6 de Juridique, 4 de Business, 1 de Code.
- **Répondre** : la skill `evals-claude-code` lance le sous-agent `repondant-evals`
  (`model: inherit`, Read et Write seuls, contexte neuf) par question ; il écrit un JSON au format
  7.3 avec, pour chaque page citée, un passage recopié mot pour mot.
- **`preparer-juge <run>`** valide les réponses, écrit un fichier de juge par réponse sous une
  étiquette anonyme (`j01`…, ordre mêlé par l'empreinte du run et du cas ; ni identifiant de cas ni
  nom de modèle) : grille du pack, complément `juge_claude_code.md`, points attendus numérotés, puis
  la question, les pages et la réponse en `<donnees_externes>`. Il refuse un juge du même modèle que
  la réponse et ne tourne qu'une fois par run : les réponses sont figées.
- **Juger** : le sous-agent `juge-evals` (`model: sonnet`, Read et Write seuls, `omitClaudeMd`)
  écrit un verdict JSON strict : les cinq notes de la grille, un verdict `couvert` / `partiel` /
  `absent` par point attendu, son modèle. Il n'écrit aucun score.
- **`noter <run> [--report evals/reports/<nom>]`** : les contrôles déterministes de
  `core/evals/checks.py` (canaris, hôtes, statut, format 7.3, calibration, **chaque nombre et chaque
  date tracés** par `core/verification/trace.py` contre la question, la date du jour et les pages,
  sinon marqués `[VERIFICATION REQUIRED]`, sourçage) ; les extraits exacts des pages citées ; chaque
  point non facultatif `couvert` ; une complétude de 2 cohérente avec les points. Score d'un cas : la
  moyenne des notes (`judge.score`, comme en réel) ; réussite : tous les contrôles et score au seuil
  du pack de `config/evals.yaml`, **lu, jamais écrit** (R9). Une porte de plus, « cas exportables
  jugés » (tous ceux du pack), empêche un run partiel d'afficher « portes franchies ». Rapport au format existant
  (`report.md` / `report.json`, mode `claude_code`) avec ce qu'il mesure.
- **Journal (R11)** : une entrée `DECISION` (acteur `interface`, statut `evals_claude_code`) par
  étape, par l'API d'ajout, avec empreintes et comptes seulement : manifeste à l'export, réponses à
  la préparation du juge, verdicts et rapport à la notation. Un manifeste, une question, une réponse
  ou la table du juge modifiés après coup sont refusés.
- **Jeu tenu à l'écart** (20 %, `core/learning/gate.py`) : ses cas sont mesurés et marqués
  `held_out` ; ce banc n'écrit ni `FEEDBACK` ni `ERROR` ni couche apprise : aucune étape
  d'apprentissage ne voit ses résultats, ni ceux des autres cas.

## Ce que le banc mesure, et ce qu'il ne mesure pas
Il mesure **le modèle de la session répondant comme CERVEAU**, sur les pages du cas, avec les mêmes
contrôles du code que l'orchestrateur. Il ne mesure ni l'orchestrateur LangGraph (classifieur,
routeur, appels d'outils, lecteur, vérificateur, pseudonymisation, politique), ni les modèles de
`config/models.yaml`, ni les cas à outils. Un rapport `claude_code` ne vaut **ni pour une
promotion** (`cerveau promotion check` exige un rapport réel scellé, D16) **ni pour la porte de la
couche apprise** (deux rapports réels, D4) : les deux le refusent déjà.

## Conséquences
- Une mesure à 0 € devient possible pour le pack Généraliste entier ; la reproductibilité dépend du
  modèle de la session, déclaré à l'export et écrit au rapport.
- Limites connues : la session peut passer un `model` à l'invocation du juge, ou réécrire un verdict
  avant `noter` (les verdicts ne sont journalisés qu'à la notation) ; le modèle que le juge déclare
  n'est pas prouvé. La skill l'interdit ; le juge lancé par le code (option 4, B367) le fermerait.
- Les consignes du banc et la grille sont versionnées et hachées au manifeste (R9, R11).
- Essai du 28/11/2026 (3 cas Généraliste, run `20261128T140255-5a1cfa`, un essai et non une
  mesure) : réponses écrites par Opus 5.5 dans la session, verdicts par trois sessions Claude Code
  sur Haiku (l'agent qui faisait l'essai n'avait pas d'outil de sous-agent), recopiés tels quels ;
  2 cas réussis (scores 1,00 et 0,90), 1 en erreur : Haiku a omis les verdicts par point, refusés
  par le code. L'essai a montré que le juge ne voyait pas la date de publication que le code écrit
  dans la liste des sources : les pages de référence la portent depuis (`juge_claude_code` 1.1) ;
  et qu'un juge qui répond `"modele": "inconnu"` est compté au modèle du fichier de l'agent.
- Suites (backlog) : B366 (un hook qui refuse à la session l'écriture de `verdicts/` et un `model`
  passé au juge), B367 (juge lancé par le code), B368 (cas exclus, par le pont MCP une fois
  branché ; date de publication absente des pages du juge réel).
