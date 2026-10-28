# Image cerveau-agent (phase 6, P3b ; ADR-054) : Claude Code (Agent SDK et son CLI embarqué), ruff
# et pytest, sur une copie jetable d'un dépôt, sans accès à Internet. Construite par Lucas, jamais
# par CERVEAU (commandes dans infra/agent/README.md) :
#   docker build -f infra/agent/agent.Dockerfile --build-context runner=core/code \
#     -t cerveau-agent infra/agent
# Contextes de construction : infra/agent (requirements.txt) et core/code (le runner seul est
# copié) ; ni var/, ni infra/.env, ni secrets/ n'y entrent (R6).
# Condensé de l'image de base : A_DEFINIR, le même que pour cerveau-llm-proxy ; tant qu'il manque,
# la construction échoue (R7).
FROM python:3.12-slim@sha256:A_DEFINIR

# requirements.txt : produit par Lucas depuis requirements.in, chaque paquet figé par version et
# par empreinte. --require-hashes refuse tout paquet sans empreinte ; --only-binary refuse toute
# construction depuis les sources (aucun setup.py exécuté) ; --no-deps : la liste est complète.
COPY --chown=0:0 --chmod=0444 requirements.txt /tmp/requirements.txt
RUN PIP_DISABLE_PIP_VERSION_CHECK=1 python -m pip install --no-cache-dir --require-hashes \
        --only-binary=:all: --no-deps -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Le seul fichier de CERVEAU dans l'image, en lecture seule.
COPY --from=runner --chown=0:0 --chmod=0444 agent_runner.py /app/agent_runner.py

# nobody:nogroup sous Debian : l'agent ne tourne jamais en root. HOME et la configuration de
# Claude Code vont sur le tmpfs /tmp que le plugin monte (racine en lecture seule).
USER 65534:65534
ENV HOME=/tmp
WORKDIR /work

# -I : mode isolé (ni variables PYTHON*, ni site de l'utilisateur, ni dossier courant dans le
# chemin d'import) ; -B : aucun .pyc écrit. Le plugin code_agent passe --task.
ENTRYPOINT ["python", "-I", "-B", "/app/agent_runner.py"]
