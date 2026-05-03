# Makefile Targets

The `Makefile` at the project root provides a small set of convenience targets that wrap the underlying tools (Docker, pytest, dbt, Sphinx). Run `make help` to see the inline summary.

| Target | What it does |
|---|---|
| `make help`        | Prints every target with its inline description. |
| `make all-env`     | One-shot bootstrap: installs all Python extras (`dev` + `dbt` + `docs`) **and** dbt packages. Use this on a fresh checkout. |
| `make install`     | Leaner alternative: `pip install -e ".[dev]"` (core dev set only). |
| `make up`          | Starts the Postgres container and waits for it to become healthy. |
| `make down`        | Stops the Postgres container (volume preserved). |
| `make generate`    | Generates synthetic CSVs to `./data/raw`. |
| `make load`        | Loads the most recent CSVs into Postgres `raw.*` tables. |
| `make seed`        | `generate` + `load` end-to-end. |
| `make dbt-deps`    | Installs dbt packages (`dbt-utils`, `dbt-expectations`, `dbt_project_evaluator`). |
| `make run`         | Full `dbt build` (seeds + snapshot + 9 marts + 138 tests). |
| `make dbt-docs`    | Generates and serves the `dbt docs` lineage site at `http://localhost:8080`. |
| `make docs`        | Builds and serves *this* documentation at `http://localhost:8000` (live reload). |
| `make dagster`     | Starts the Dagster UI at `http://localhost:3000` (orchestrator + asset graph). |
| `make recon-run`   | Manually triggers the full recon pipeline (data load + dbt + audit + Slack), no Dagster needed. |
| `make recon-list`  | Lists the last 10 recon runs from the audit trail. |
| `make streamlit`   | Starts the Streamlit Recon Cockpit at `http://localhost:8501`. |
| `make test`        | Runs the pytest smoke suite. |
| `make lint`        | Lints with `ruff`. |
| `make fmt`         | Auto-formats with `ruff format`. |
| `make clean`       | Removes generated CSVs from `./data/raw`. |

---

## Typical sequences

### Cold start (recommended)

```bash
make all-env && make up && make seed && make run
```

### Cold start (leaner — skips docs and waits to install dbt packages)

```bash
make install && make up && make seed && make dbt-deps && make run
```

### After editing a Python file

```bash
make test && make lint
```

### After editing a dbt model

```bash
make run
```

### After editing a docs page

```bash
make docs   # live-reloads automatically; just save and refresh the browser
```

### Reset everything to a clean state

```bash
docker compose down -v   # destroys the Postgres volume — local-only
make up && make seed && make run
```

### Run the full demo end-to-end

```bash
make all-env && make up && make seed && make run \
    && make recon-run     # writes one row to audit.recon_runs
make streamlit            # browse http://localhost:8501 in another shell
```

### Start the orchestrator UI

```bash
make dagster   # http://localhost:3000 — asset graph, schedule, run history
```
