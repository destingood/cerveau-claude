# CERVEAU — developer commands. Each recipe is a single command so that it runs the same under
# sh (Git Bash, Linux) and cmd.exe (make launched from PowerShell).

UV ?= uv
NPX ?= npx
PROMPTFOO ?= promptfoo@0.124.1
COMPOSE ?= docker compose -f infra/docker-compose.yml

export PROMPTFOO_DISABLE_TELEMETRY := 1
export PROMPTFOO_DISABLE_UPDATE := 1

.DEFAULT_GOAL := help
.PHONY: help sync test lint format eval audit-verify secrets-scan audit-deps compose-config hooks ci

help:
	@echo Targets: sync test lint format eval audit-verify secrets-scan audit-deps compose-config hooks ci

sync:
	$(UV) sync --frozen

test:
	$(UV) run pytest

lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .

format:
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

eval:
	$(NPX) -y $(PROMPTFOO) eval -c evals/promptfoo/promptfooconfig.yaml --no-cache --no-write --no-table --no-progress-bar

audit-verify:
	$(UV) run cerveau audit verify

secrets-scan:
	gitleaks git --no-banner --redact

audit-deps:
	$(UV) run pip-audit --skip-editable

# Needs infra/.env (uv run python infra/scripts/generate_secrets.py); fails while it is missing.
compose-config:
	$(COMPOSE) --profile core --profile observability config --quiet

hooks:
	$(UV) run pre-commit install

ci: lint test eval audit-verify secrets-scan audit-deps
