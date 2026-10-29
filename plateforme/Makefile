# CERVEAU — developer commands. Each recipe is a single command so that it runs the same under
# sh (Git Bash, Linux) and cmd.exe (make launched from PowerShell).

UV ?= uv
COMPOSE ?= docker compose -f infra/docker-compose.yml
BOT := interfaces/discord_bot
GATE_COVERAGE := --cov=core/risk_gate --cov=core/policy --cov=core/approvals --cov=core/governance --cov=core.execution.live --cov=core/net --cov=core/research --cov=core/code --cov=plugins/legifrance --cov=core/business --cov=plugins/business_calc --cov=plugins/entreprises --cov=plugins/insee_stats --cov=core.learning.calibration --cov=core.learning.forecasts --cov=core.learning.layer --cov=core.learning.gate --cov=core.learning.patterns --cov=core.learning.champion --cov=core/reports --cov=interfaces.cli.report --cov=core/cyber --cov=plugins.cyber_cve.common --cov=plugins.cyber_cve.epss --cov=plugins.cyber_cve.kev --cov=plugins.cyber_cve.models --cov=plugins.cyber_cve.nvd --cov=plugins.cyber_cve.priority --cov=plugins.cyber_cve.server --cov=plugins.cyber_cve.settings --cov=plugins.cyber_attack.models --cov=plugins.cyber_attack.search --cov=plugins.cyber_attack.server --cov-branch --cov-fail-under=100 --cov-report=term-missing:skip-covered

export PROMPTFOO_DISABLE_TELEMETRY := 1
export PROMPTFOO_DISABLE_UPDATE := 1

.DEFAULT_GOAL := help
.PHONY: help sync test bot-test lint format eval eval-live audit-verify secrets-scan audit-deps compose-config hooks ci

help:
	@echo Targets: sync test bot-test lint format eval eval-live audit-verify secrets-scan audit-deps compose-config hooks ci

sync:
	$(UV) sync --frozen

# The Risk Gate needs full line and branch coverage (ADR-031); the rest has no threshold.
test:
	$(UV) run pytest $(GATE_COVERAGE)

# The Discord bot's tests: no network, no Discord (ADR-037). Install scripts never run.
bot-test:
	npm --prefix $(BOT) ci --ignore-scripts --no-audit --no-fund
	npm --prefix $(BOT) test

lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .

format:
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

eval:
	$(UV) run cerveau eval

# Paid: only for a campaign Lucas agreed to (D8). make eval-live CAMPAIGN=<name> SUITES="<suites>"
eval-live:
	$(UV) run cerveau eval --live --campaign "$(CAMPAIGN)" $(SUITES)

audit-verify:
	$(UV) run cerveau audit verify

secrets-scan:
	gitleaks git --no-banner --redact

audit-deps:
	$(UV) run pip-audit --skip-editable
	npm --prefix $(BOT) audit --omit=dev

# Needs infra/.env (uv run python infra/scripts/generate_secrets.py); fails while it is missing.
compose-config:
	$(COMPOSE) --profile core --profile observability config --quiet

hooks:
	$(UV) run pre-commit install

ci: lint test bot-test eval audit-verify secrets-scan audit-deps
