
# Saathi developer shortcuts. Run `make` (or `make help`) to list them.
# Needs: make, docker, psql (Windows: run everything inside WSL2 Ubuntu).
#
# Every value in .env becomes a make variable AND an environment variable,
# so commands like `psql "$(DATABASE_URL)"` and scripts/run_golden.py just work.
# If a value in .env contains special characters ($, &, #, spaces), wrap it in quotes.

-include .env
export

.DEFAULT_GOAL := help

# Which migration file `make migrate` applies. Override: make migrate F=db/migrations/002_x.sql
F ?= db/migrations/001_init.sql

help: ## Show this list
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-12s %s\n", $$1, $$2}'

up: ; docker compose up -d --build ## Build and start n8n, api and dashboard
down: ; docker compose down ## Stop the stack
restart: ; docker compose restart ## Restart all containers
ps: ; docker compose ps ## Show container status
logs: ; docker compose logs -f --tail=100 ## Follow all container logs

migrate: ; psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 -f $(F) ## Apply one migration file (default 001_init.sql; run each file once)
seed: ; psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 -f db/seed.sql ## Insert you + the golden test user
psql: ; psql "$(DATABASE_URL)" ## Open an interactive SQL shell

test: ; cd services/api && python -m pytest -q ## Run unit tests (no DB or keys needed)
lint: ; cd services/api && ruff check app tests ## Lint the API code

export-wf: ; bash scripts/export_workflows.sh ## Save n8n workflows into n8n/workflows/ (commit them)
import-wf: ; bash scripts/import_workflows.sh ## Load n8n/workflows/*.json into n8n
golden: ; python scripts/run_golden.py ## Run end-to-end agent tests via WF03
backup: ; bash scripts/backup_db.sh ## Compressed database dump into backups/

prod-up: ; docker compose --profile prod up -d --build ## Start with the Cloudflare tunnel (production)

.PHONY: help up down restart ps logs migrate seed psql test lint export-wf import-wf golden backup prod-up
