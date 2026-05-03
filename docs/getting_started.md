# Getting Started

This guide walks you from a clean machine to a fully reconciled dataset in about ten minutes.

---

## Prerequisites

You need three things on your machine before you start:

| Tool | Version | Why |
|---|---|---|
| **Docker Desktop** | any recent | Runs the local PostgreSQL instance. |
| **pyenv + pyenv-virtualenv** | any recent | Pins the project to Python {{ python_version }}. |
| **Git** | any recent | Cloning the repository. |

If you do not already use pyenv, install it via `brew install pyenv pyenv-virtualenv` on macOS or follow the [official pyenv docs](https://github.com/pyenv/pyenv) on Linux.

```{note}
The project is locked to Python {{ python_version }} because dbt-core 1.11 has been validated on it. Other 3.13.x patch versions also work.
```

---

## Step 1 — Clone and enter the repository

```bash
git clone https://github.com/supreetha9/gl-reconciliation.git
cd gl-reconciliation
```

---

## Step 2 — Create the Python environment

The project uses a dedicated pyenv virtualenv called `gl_env` so it does not pollute your other Python projects.

```bash
pyenv install -s 3.13.3
pyenv virtualenv 3.13.3 gl_env
pyenv local gl_env          # writes .python-version pinning the project to gl_env
python --version            # should print: Python 3.13.3
```

---

## Step 3 — Install dependencies

```bash
cp .env.example .env        # default Postgres credentials, safe for local
make all-env                # one-shot bootstrap: all Python extras + dbt packages
```

`all-env` installs everything you need in a single command:

- runtime deps (`pydantic`, `pandas`, `sqlalchemy`, `Faker`, `typer`, `structlog`, …)
- dev tools (`pytest`, `ruff`, `mypy`)
- dbt (`dbt-core`, `dbt-postgres`)
- this documentation toolchain (`sphinx`, `furo`, `myst-parser`, `sphinx-autobuild`, `sphinxcontrib-mermaid`)
- dbt packages into `dbt_project/dbt_packages/` (`dbt-utils`, `dbt-expectations`, `dbt_project_evaluator`)

If you want a leaner install (no dbt or docs), use `make install` instead — it pulls only the core dev set. You can always upgrade later with `pip install -e ".[dev,dbt,docs]"` and `make dbt-deps`.

---

## Step 4 — Start PostgreSQL

```bash
make up
```

This launches the `glrecon_postgres` container from `docker-compose.yml` and waits for it to become healthy. The init scripts under `db/init/` run automatically the first time the container starts and create:

- five schemas (`raw`, `staging`, `intermediate`, `marts`, `audit`)
- all bronze-layer tables for AP, AR, Inventory, GL, and dimensions
- the SOX-style `audit.recon_runs` and `audit.recon_check_results` tables

You can verify the container is up at any time with `docker compose ps`.

---

## Step 5 — Generate and load synthetic data

```bash
make seed
```

`seed` is a convenience target that runs `generate` (Faker-based synthetic AP/AR/INV/GL with intentionally injected breaks) followed by `load` (truncate-and-COPY into Postgres). On a 30-day window with the default seed, you should see a row-count summary like:

```
raw.ap_invoices       10,000
raw.ap_payments        6,503
raw.ar_invoices       15,000
raw.ar_receipts       10,167
raw.gl_journal       100,050
…
```

and a breakdown of the five injected break classes:

```
timing_diff         2,002
fx_rounding           553
amount_mismatch       490
missing_gl_posting    150
```

---

## Step 6 — Build the reconciliation models

```bash
make run                    # dbt build: seeds + snapshot + 9 recon marts + 138 tests
```

(`make all-env` already installed the dbt packages. If you used the leaner `make install`, run `make dbt-deps` first.)

A clean run prints:

```
Done. PASS=208 WARN=8 ERROR=0 SKIP=0 NO-OP=2 TOTAL=218
```

The eight warnings come from `dbt_project_evaluator` (style/governance hints — they do not fail the build).

---

## Step 7 — Explore the results

```bash
python -m data_generator.cli summary
```

Prints row counts in `raw.*`. To inspect the recon results directly in Postgres:

```bash
docker compose exec postgres psql -U glrecon -d glrecon -c \
  "SELECT * FROM glrecon_marts.recon_summary;"
```

You should see the scorecard:

```
    check_name     | pass  | warn | fail | breaks_value_usd
-------------------+-------+------+------+------------------
 control_account   |     0 |    8 |  268 |      58247962.94
 roll_forward      |  2322 |    0 |    0 |             0.00
 transaction_level | 97955 |    0 | 2479 |        896855.37
```

---

## Step 8 — Browse the lineage graph

```bash
make dbt-docs
```

Opens dbt's auto-generated lineage and column-level documentation site at `http://localhost:8080`.

---

## Step 9 — Browse this documentation locally

```bash
make docs
```

Spins up the Sphinx documentation server you are reading right now at `http://localhost:8000`, with live reload as you edit pages under `docs/`.

---

## What's next

- Read [Architecture](architecture.md) to understand the medallion layout and data flow.
- Read [Reconciliation Engine](reconciliation_engine.md) to learn the nine checks.
- Read [Development](development.md) when you're ready to contribute a new check.
- If anything went wrong, check [Troubleshooting](troubleshooting.md).
