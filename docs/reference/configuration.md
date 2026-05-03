# Configuration

The project is configured in three places. This reference covers each.

---

## `.env` — environment variables

Copied from `.env.example` on first checkout. Read by `docker-compose`, the data generator (via `pydantic-settings`), and the dbt profile.

| Variable | Default | Used by |
|---|---|---|
| `POSTGRES_USER`         | `glrecon`  | docker-compose, loader, dbt profile |
| `POSTGRES_PASSWORD`     | `glrecon`  | docker-compose, loader, dbt profile |
| `POSTGRES_DB`           | `glrecon`  | docker-compose, loader, dbt profile |
| `POSTGRES_HOST`         | `localhost`| loader, dbt profile |
| `POSTGRES_PORT`         | `5432`     | docker-compose (host port), loader, dbt profile |
| `GLRECON_SEED`               | `42`         | data generator |
| `GLRECON_DAYS`               | `90`         | data generator |
| `GLRECON_OUTPUT_DIR`         | `./data/raw` | data generator |
| `SLACK_WEBHOOK_URL`          | (empty)      | Slack alerter — when unset the alerter is a no-op |
| `MATERIALITY_THRESHOLD_USD`  | `10000`      | Slack alerter — minimum break value to surface in the alert body |
| `DAGSTER_HOME`               | `$CURDIR/.dagster_home` | Dagster local instance state (set by `make dagster`) |

---

## `data_generator.config.Settings`

Top-level pydantic-settings model in [`data_generator/config.py`](https://github.com/supreetha9/gl-reconciliation/blob/main/data_generator/config.py). All fields can be overridden via environment variables prefixed with `GLRECON_`. Nested fields use double-underscore separators (e.g., `GLRECON_BREAKS__TIMING_DIFF`).

### Top-level

| Field | Type | Default |
|---|---|---|
| `seed`                    | int       | `42`            |
| `days`                    | int       | `90`            |
| `end_date`                | date      | today           |
| `output_dir`              | Path      | `./data/raw`    |
| `reporting_currency`      | str       | `USD`           |
| `transaction_currencies`  | list[str] | `[USD, EUR, INR]` |

### `volumes` sub-model

| Field | Default |
|---|---|
| `ap_invoices`           | 10,000 |
| `ap_payments`           | 8,000  |
| `ap_accruals`           | 500    |
| `ar_invoices`           | 15,000 |
| `ar_receipts`           | 12,000 |
| `ar_credit_memos`       | 300    |
| `inv_receipts`          | 4,000  |
| `inv_cogs`              | 4,000  |
| `inv_adjustments`       | 400    |
| `manual_je_per_day`     | 5      |

Override with e.g. `GLRECON_VOLUMES__AP_INVOICES=50000`.

### `breaks` sub-model

| Field | Default | What it injects |
|---|---|---|
| `timing_diff`             | `0.020` | posting_date shifted by 1-2 days on the GL side |
| `amount_mismatch`         | `0.005` | `±$0.01-$0.50` USD noise on a single GL line |
| `missing_gl_posting`      | `0.003` | Drops the entire journal entry from the GL feed |
| `unauthorized_manual_je`  | `0.002` | Re-points a manual JE credit line to a control account |
| `fx_rounding`             | `0.010` | `±$0.01-$0.05` noise on non-USD postings |

All rates are fractions of the eligible row population. Override with e.g. `GLRECON_BREAKS__MISSING_GL_POSTING=0.05`.

---

## dbt configuration

### `dbt_project/dbt_project.yml`

The dbt project config. Highlights:

- `require-dbt-version: [">=1.8.0", "<2.0.0"]`
- Per-folder materialization defaults (staging → view, intermediate → view, marts → table)
- Per-folder schema mapping (`+schema: staging` → `glrecon_staging`)
- Project-wide `vars`:
  - `default_materiality_usd: 1000`
  - `amount_tolerance_usd: 0.05`
  - `timing_tolerance_days: 1`
  - `fx_tolerance_pct: 0.001`

### `dbt_project/profiles.yml`

Env-driven Postgres connection. **Do not commit credentials.** Profile is loaded by setting `DBT_PROFILES_DIR=.` when running dbt from inside `dbt_project/`.

### Tolerance and materiality seeds

These are version-controlled CSVs:

- `dbt_project/seeds/tolerance_rules.csv`
- `dbt_project/seeds/materiality.csv`

See [Reconciliation Engine → Tolerance and materiality](../reconciliation_engine.md#tolerance-and-materiality) for what the columns mean and how to tune them. Re-load with `cd dbt_project && DBT_PROFILES_DIR=. dbt seed`.

---

## Postgres

### Schemas (auto-created on first start)

| Schema | Purpose |
|---|---|
| `raw`                  | Bronze landings |
| `staging`              | (reserved; dbt actually writes to `glrecon_staging`) |
| `intermediate`         | (reserved; dbt actually writes to `glrecon_intermediate`) |
| `marts`                | (reserved; dbt actually writes to `glrecon_marts`) |
| `audit`                | SOX-style run log |
| `glrecon_*` schemas    | Created by dbt at first build, prefixed with the project name |

### `docker-compose.yml`

Single-service Postgres 16 with:

- A persistent named volume `pgdata`
- Init scripts mounted from `./db/init`
- A `pg_isready` health check on a 5-second interval

---

## Dagster

The `dagster_pipeline` package reads three resources from environment variables (defined in `dagster_pipeline/resources.py`):

| Resource | Backed by | Env vars |
|---|---|---|
| `PostgresResource` | SQLAlchemy `Engine`             | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB` |
| `DbtCliResource`   | `dagster-dbt`'s `DbtProject`    | (uses the project's `profiles.yml`)                                                    |
| `SlackResource`    | `recon_engine.alerts.SlackAlerter` | `SLACK_WEBHOOK_URL`, `MATERIALITY_THRESHOLD_USD`                                    |

`DAGSTER_HOME` controls where Dagster persists run history and the daemon's state. The `make dagster` target points it at `$CURDIR/.dagster_home` (gitignored) so each developer has an isolated local instance.

The daily schedule (`daily_recon_schedule`) is defined as `STOPPED` by default — flip it to `RUNNING` in the Dagster UI when promoting to a deployment.

---

## Streamlit

The cockpit reads the same `POSTGRES_*` env vars as the rest of the project. There are no Streamlit-specific env vars today; if you add one (for example, an OAuth issuer), wire it through `streamlit_app/lib/db.py` so it stays consistent with the other resources.
