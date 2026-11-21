# Réglages et prérequis

D'après `skills/reverse-api-engineer/references/setup.md` du dépôt kalil0321/reverse-api-engineer (MIT), adapté.

## Prérequis
- Python 3.11 ou plus, et `uv` (ou `pipx` / `pip`). Plateformes : Linux, macOS Apple Silicon, Windows 64 bits.
- Node.js 20.19 ou plus, avec `npx` dans le PATH, pour le mode agent.
- `chrome-mcp` avec fenêtre : Chrome 146 ou plus ouvert, débogage à distance activé dans
  `chrome://inspect/#remote-debugging` (« Enable auto-connect »).
- Mode manuel seulement : `uv tool install "reverse-api-engineer[manual]"`, puis `playwright install chromium`.

## Accès au modèle
rae appelle un modèle par le SDK choisi dans ses réglages :

| `sdk` | Authentification |
|---|---|
| `claude` (défaut) | `ANTHROPIC_API_KEY`, ou la connexion Claude Code déjà en place |
| `opencode` | un serveur OpenCode que rae démarre ou réutilise ; modèle gratuit par défaut ; peut passer par Ollama (modèles locaux) |
| `copilot` | GitHub Copilot (`GITHUB_COPILOT_TOKEN`) |
| `cursor` | `CURSOR_API_KEY` |

`agent --dry-run` dit ce qu'il voit. Une variable absente est un `warn`, pas une `error` : certains SDK trouvent
leurs identifiants seuls. Ne jamais demander, afficher ni copier une clé.

## Le fichier de réglages
`~/.reverse-api/config.json`. Seuls deux réglages ont un drapeau par capture sur `agent` : `-o/--output-dir` et
`-m/--model` (SDK `claude`). Les autres se changent dans le fichier, ou avec `/settings` dans la session
`reverse-api-engineer` — avec l'accord de l'utilisateur, car ils valent pour toutes les captures suivantes.

| Clé | Valeurs |
|---|---|
| `agent_provider` | `auto` (Playwright MCP, HAR enregistré ; défaut en 0.14), `chrome-mcp` (vrai Chrome de l'utilisateur, pas de HAR ; défaut des versions suivantes pour un nouveau fichier), `agent-browser` (CLI agent-browser de Vercel, HAR) |
| `output_language` | `python`, `javascript`, `typescript`, `go`, `java`, `csharp`, `php`, `ruby`, `c`, `powershell` |
| `sdk` | `claude`, `opencode`, `copilot`, `cursor` |
| `claude_code_model` | modèle du SDK `claude` ; `agent -m` le remplace pour une capture ; liste à jour dans `/model` |
| `output_dir` | dossier des captures ; `null` = `~/.reverse-api/runs` |
| `real_time_sync` | `true` : copie aussi le client dans `./scripts/<nom>/` du dossier courant |

Langages : C demande une chaîne POSIX avec les en-têtes libcurl (Mac, Linux, WSL ou MSYS2 sous Windows) ;
PowerShell demande `pwsh` 7 ou plus (PowerShell Core, pas Windows PowerShell 5.1).

## Où vont les fichiers
- `~/.reverse-api/runs/scripts/<run_id>/` : stockage permanent (client, README, exemple).
- `~/.reverse-api/runs/har/<run_id>/` : la capture réseau (cookies et jetons dedans : jamais partagée).
- `./scripts/<nom_lisible>/` : copie locale quand `real_time_sync` est actif.
- `./collected/<nom>/` : résultats du mode collector (`items.json`, `items.csv`, `README.md`).
