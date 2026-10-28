# Images de l'agent de code (phase 6, P3b)

Deux images, construites par Lucas seulement ; CERVEAU les lance avec `--pull never` et ne les
construit ni ne les télécharge jamais.

| Image | Fichier | Contenu | ADR |
|---|---|---|---|
| `cerveau-agent` | `agent.Dockerfile` | `python:3.12-slim`, `claude-agent-sdk` 0.2.172 (CLI de Claude Code embarqué), ruff, pytest, `core/code/agent_runner.py` | ADR-054 |
| `cerveau-llm-proxy` | `llm-proxy.Dockerfile` | `python:3.12-slim`, `core/code/llm_proxy.py` (bibliothèque standard seulement) | ADR-053 |

Le CLI embarqué dans `claude-agent-sdk` est sous licence restrictive (« All rights reserved »,
conditions commerciales d'Anthropic) : il reste dans l'image, jamais dans le dépôt
(`docs/licences.md`, R14).

## 1. Figer l'image de base

Relever le condensé de `python:3.12-slim` et le reporter à la place de `A_DEFINIR` dans les deux
Dockerfile (même valeur) :

```bash
docker buildx imagetools inspect python:3.12-slim
```

La ligne `Digest: sha256:…` est le condensé de l'index multi-plateformes : à copier tel quel.

## 2. Figer les paquets de l'agent

`requirements.txt` est produit depuis `requirements.in`, chaque paquet et chaque dépendance
figés par version et par empreinte, pour Linux x86_64 (sur une machine ARM : `aarch64-manylinux_2_28`) :

```bash
uv pip compile infra/agent/requirements.in --generate-hashes --python-version 3.12 --python-platform x86_64-manylinux_2_28 -o infra/agent/requirements.txt
```

Relire la liste avant la construction : tout paquet nouveau ou inattendu se vérifie (licence,
éditeur) avant d'aller plus loin. Une mise à jour du SDK passe par une revue `security-reviewer`
et relance les évals (R9).

## 3. Construire

Depuis la racine du dépôt :

```bash
docker build -f infra/agent/llm-proxy.Dockerfile -t cerveau-llm-proxy core/code
```

```bash
docker build -f infra/agent/agent.Dockerfile --build-context runner=core/code -t cerveau-agent infra/agent
```

Le second contexte (`runner`) demande BuildKit, actif par défaut dans Docker Desktop.

## 4. Déclarer les images

Relever l'identifiant local de chaque image :

```bash
docker image inspect --format "{{.Id}}" cerveau-agent cerveau-llm-proxy
```

Puis, dans `config/code.yaml`, section `agent` : `image` (cerveau-agent) et `proxy_image`
(cerveau-llm-proxy), sous la forme `sha256:<64 hex>`. Vérifier ensuite :

```bash
uv run cerveau config check
```

Une image reconstruite change d'identifiant : la nouvelle valeur doit être reportée, sinon
`code_agent` refuse de démarrer (image introuvable, jamais téléchargée).

## 5. Avant le premier appel réel (payant)

Rien ne part tant que ces valeurs restent `A_DEFINIR` (R7) :

- `config/code.yaml` : `repositories` (liste blanche), `agent.image`, `agent.proxy_image`,
  `agent.max_requests` ;
- `config/budgets.yaml` : budgets journalier et mensuel en euros ;
- la variable d'environnement `ANTHROPIC_API_KEY` de Lucas, reprise par son nom dans le seul
  conteneur du proxy (`docker run --env ANTHROPIC_API_KEY`), jamais écrite ni journalisée.

Points à vérifier lors du premier essai (`A_VERIFIER`, ADR-054) :

- un réseau `docker network create --internal` n'a aucune sortie sous Docker Desktop pour Windows.
  Essais depuis un conteneur de ce réseau, qui doivent tous échouer : `getent hosts example.com`
  (résolution DNS externe), `curl https://example.com`, puis `getent hosts host.docker.internal`
  suivi d'une connexion à l'adresse obtenue (accès à l'hôte) ;
- le CLI accepte la clé factice et se contente de `POST /v1/messages`, le seul chemin que le
  proxy laisse passer ; tout autre appel est refusé et compté dans l'état du proxy ;
- l'utilisateur 65534 peut écrire dans la copie montée (bind mount sous Docker Desktop ; sur un
  hôte Linux, droits du dossier `var/code/agent/<id>/`) ;
- mémoire utile au CLI dans la limite de 4096 Mo ; durée de démarrage du proxy (15 s au plus) ;
- un lien symbolique créé par l'agent dans la copie, vu depuis Windows : il est listé et écarté
  du patch, jamais suivi ;
- un fichier `governance/kill_switch/KILL` créé pendant une tâche apparaît dans le dossier monté
  du proxy et l'utilisateur 65534 peut le lire : le proxy s'arrête de lui-même ;
- `--ulimit fsize=104857600` borne un fichier à 100 Mio (valeur en octets) : depuis le conteneur,
  `ulimit -f` doit afficher 102400 (blocs de 1024 octets).

## 6. Après un arrêt brutal de CERVEAU

Les conteneurs et réseaux de `code_agent` portent l'étiquette `cerveau.code_agent=1`. Le runner
et le proxy s'arrêtent seuls à la fin de leur durée ; pour les retirer sans attendre :

```bash
docker ps --quiet --filter label=cerveau.code_agent=1
```

```bash
docker kill <identifiants listés>
```

```bash
docker network prune --force --filter label=cerveau.code_agent=1
```

La copie jetable reste sous `var/code/agent/runs/<id>/` (B283) : la supprimer à la main.
