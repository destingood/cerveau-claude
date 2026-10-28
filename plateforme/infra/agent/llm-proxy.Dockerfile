# Image cerveau-llm-proxy (phase 6, P3b ; ADR-053) : le proxy de l'API d'Anthropic de l'agent de
# code, bibliothèque standard de Python seulement. Construite par Lucas, jamais par CERVEAU :
#   docker build -f infra/agent/llm-proxy.Dockerfile -t cerveau-llm-proxy core/code
# Le contexte de construction est core/code : ni var/, ni infra/.env, ni secrets/ n'y entrent (R6).
# Condensé de l'image de base : A_DEFINIR, relevé par Lucas (par exemple
# `docker buildx imagetools inspect python:3.12-slim`) ; tant qu'il manque, la construction
# échoue (R7). Un tag seul bouge : l'image est figée par son condensé.
FROM python:3.12-slim@sha256:A_DEFINIR

# Le seul fichier de CERVEAU dans l'image, en lecture seule. Ni paquet ni dépendance installés.
COPY --chown=0:0 --chmod=0444 llm_proxy.py /app/llm_proxy.py

# nobody:nogroup sous Debian, la base de python:3.12-slim : le proxy ne tourne jamais en root.
USER 65534:65534
EXPOSE 8080

# -I : mode isolé (ni variables PYTHON*, ni site de l'utilisateur, ni dossier courant dans le
# chemin d'import) ; -B : aucun .pyc écrit. Le plugin code_agent passe --settings et --state.
ENTRYPOINT ["python", "-I", "-B", "/app/llm_proxy.py"]
