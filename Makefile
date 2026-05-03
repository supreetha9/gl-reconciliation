.PHONY: help install up down generate load seed run test lint fmt clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install Python dependencies into the active env (use `pyenv local gl_env` first)
	pip install -e ".[dev]"

up: ## Start Postgres in Docker
	docker compose up -d
	@echo "Waiting for Postgres to be healthy..."
	@until docker compose exec -T postgres pg_isready -U $${POSTGRES_USER:-glrecon} -d $${POSTGRES_DB:-glrecon} >/dev/null 2>&1; do sleep 1; done
	@echo "Postgres is ready."

down: ## Stop Postgres
	docker compose down

generate: ## Generate synthetic AP/AR/Inventory/GL CSVs to ./data/raw
	python -m data_generator.cli generate

load: ## Load generated CSVs into Postgres bronze (raw.*) tables
	python -m data_generator.cli load

seed: generate load ## Generate + load synthetic data end-to-end

run: ## Phase 2+: run dbt build (placeholder until dbt project lands)
	@echo "dbt project not yet present (Phase 2)."

test: ## Run pytest
	pytest

lint: ## Lint with ruff
	ruff check .

fmt: ## Format with ruff
	ruff format .

clean: ## Remove generated data
	rm -rf data/raw/*.csv data/raw/*.parquet
