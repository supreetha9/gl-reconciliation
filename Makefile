# =============================================================================
# Toolchain resolution
#
# This project strictly targets Python 3.13 via the `gl_env` pyenv virtualenv.
# We resolve every tool through the env prefix so things work whether or not
# pyenv-virtualenv auto-activation is configured in your shell.
#
# If `gl_env` doesn't exist yet, run:
#   pyenv install -s 3.13.3
#   pyenv virtualenv 3.13.3 gl_env
#   pyenv local gl_env
# =============================================================================

PYENV_VENV       := gl_env
GL_ENV_PREFIX    := $(shell pyenv prefix $(PYENV_VENV) 2>/dev/null)

PYTHON           := $(GL_ENV_PREFIX)/bin/python
PIP              := $(PYTHON) -m pip
DBT              := $(GL_ENV_PREFIX)/bin/dbt
RUFF             := $(GL_ENV_PREFIX)/bin/ruff
PYTEST           := $(GL_ENV_PREFIX)/bin/pytest
SPHINX_BUILD     := $(GL_ENV_PREFIX)/bin/sphinx-build
SPHINX_AUTOBUILD := $(GL_ENV_PREFIX)/bin/sphinx-autobuild

.PHONY: help _check-env all-env install up down generate load seed run \
        test lint fmt clean dbt-deps dbt-docs docs docs-build docs-clean \
        dagster recon-run recon-list streamlit

# -----------------------------------------------------------------------------
# Help
# -----------------------------------------------------------------------------

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -v '^_' | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# -----------------------------------------------------------------------------
# Environment guardrail. Every Python-using target depends on this so users
# get a helpful error before any tool runs against the wrong interpreter.
# -----------------------------------------------------------------------------

_check-env:
	@command -v pyenv >/dev/null 2>&1 || { \
		echo "ERROR: pyenv is not installed."; \
		echo "       See docs/getting_started.md (Prerequisites)."; \
		exit 1; \
	}
	@test -n "$(GL_ENV_PREFIX)" || { \
		echo "ERROR: pyenv virtualenv '$(PYENV_VENV)' not found."; \
		echo "       Run:"; \
		echo "         pyenv install -s 3.13.3"; \
		echo "         pyenv virtualenv 3.13.3 $(PYENV_VENV)"; \
		echo "         pyenv local $(PYENV_VENV)"; \
		exit 1; \
	}
	@$(PYTHON) -c "import sys; ok = sys.version_info[:2] == (3, 13); print(sys.version.split()[0]); sys.exit(0 if ok else 1)" >/tmp/.glrecon-pyver 2>/dev/null || { \
		echo "ERROR: $(PYENV_VENV) must be Python 3.13.x. Got: $$(cat /tmp/.glrecon-pyver 2>/dev/null || echo unknown)"; \
		echo "       Recreate the env:"; \
		echo "         pyenv uninstall -f $(PYENV_VENV)"; \
		echo "         pyenv install -s 3.13.3"; \
		echo "         pyenv virtualenv 3.13.3 $(PYENV_VENV)"; \
		echo "         pyenv local $(PYENV_VENV)"; \
		exit 1; \
	}
	@rm -f /tmp/.glrecon-pyver

# -----------------------------------------------------------------------------
# Bootstrap
# -----------------------------------------------------------------------------

install: _check-env ## Install core Python dependencies (dev tools only) into gl_env
	$(PIP) install -e ".[dev]"

all-env: _check-env ## Install ALL Python extras (dev + dbt + docs) and dbt packages -- one-shot bootstrap
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev,dbt,docs]"
	@echo "Python deps installed. Fetching dbt packages..."
	cd dbt_project && DBT_PROFILES_DIR=. $(DBT) deps
	@echo
	@echo "Environment ready. Next steps:"
	@echo "  make up      # start Postgres"
	@echo "  make seed    # generate + load synthetic data"
	@echo "  make run     # dbt build"
	@echo "  make docs    # browse the project documentation"

# -----------------------------------------------------------------------------
# Postgres
# -----------------------------------------------------------------------------

up: ## Start Postgres in Docker
	docker compose up -d
	@echo "Waiting for Postgres to be healthy..."
	@until docker compose exec -T postgres pg_isready -U $${POSTGRES_USER:-glrecon} -d $${POSTGRES_DB:-glrecon} >/dev/null 2>&1; do sleep 1; done
	@echo "Postgres is ready."

down: ## Stop Postgres
	docker compose down

# -----------------------------------------------------------------------------
# Synthetic data
# -----------------------------------------------------------------------------

generate: _check-env ## Generate synthetic AP/AR/Inventory/GL CSVs to ./data/raw
	$(PYTHON) -m data_generator.cli generate

load: _check-env ## Load generated CSVs into Postgres bronze (raw.*) tables
	$(PYTHON) -m data_generator.cli load

seed: generate load ## Generate + load synthetic data end-to-end

# -----------------------------------------------------------------------------
# dbt
# -----------------------------------------------------------------------------

run: _check-env ## Run full dbt build (seeds + snapshot + models + tests)
	cd dbt_project && DBT_PROFILES_DIR=. $(DBT) build --no-version-check

dbt-deps: _check-env ## Install dbt packages (re-fetch dbt-utils, dbt-expectations, project-evaluator)
	cd dbt_project && DBT_PROFILES_DIR=. $(DBT) deps

dbt-docs: _check-env ## Generate and serve the dbt lineage docs site (port 8080)
	cd dbt_project && DBT_PROFILES_DIR=. $(DBT) docs generate && DBT_PROFILES_DIR=. $(DBT) docs serve --port 8080

# -----------------------------------------------------------------------------
# Orchestration (Phase 3)
# -----------------------------------------------------------------------------

DAGSTER := $(GL_ENV_PREFIX)/bin/dagster

dagster: _check-env ## Start the Dagster UI on port 3000 (orchestrator + asset graph)
	@mkdir -p .dagster_home
	DAGSTER_HOME=$(CURDIR)/.dagster_home $(DAGSTER) dev -m dagster_pipeline.definitions

recon-run: _check-env ## Manually trigger a full recon run (data load + dbt + audit + Slack), no Dagster needed
	$(PYTHON) -m recon_engine.cli run-recon

recon-list: _check-env ## List the last 10 recon runs from the audit trail
	$(PYTHON) -m recon_engine.cli list-runs

# -----------------------------------------------------------------------------
# Streamlit Recon Cockpit (Phase 4)
# -----------------------------------------------------------------------------

STREAMLIT := $(GL_ENV_PREFIX)/bin/streamlit

streamlit: _check-env ## Start the Streamlit Recon Cockpit on port 8501
	$(STREAMLIT) run streamlit_app/Home.py --server.port 8501

# -----------------------------------------------------------------------------
# Project documentation (Sphinx)
# -----------------------------------------------------------------------------

docs: _check-env ## Build and serve the project documentation with live reload (port 8000)
	$(SPHINX_AUTOBUILD) docs docs/_build/html --port 8000 --open-browser

docs-build: _check-env ## One-shot build of the project documentation to docs/_build/html
	$(SPHINX_BUILD) -b html docs docs/_build/html

docs-clean: ## Remove generated documentation artifacts
	rm -rf docs/_build docs/_autosummary

# -----------------------------------------------------------------------------
# Quality
# -----------------------------------------------------------------------------

test: _check-env ## Run pytest
	$(PYTEST)

lint: _check-env ## Lint with ruff
	$(RUFF) check .

fmt: _check-env ## Format with ruff
	$(RUFF) format .

# -----------------------------------------------------------------------------
# Cleanup
# -----------------------------------------------------------------------------

clean: ## Remove generated data
	rm -rf data/raw/*.csv data/raw/*.parquet
