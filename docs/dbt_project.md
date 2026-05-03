# dbt Project

The dbt project under [`dbt_project/`](https://github.com/supreetha9/gl-reconciliation/tree/main/dbt_project) implements the reconciliation engine as code. This page describes its structure and the conventions that hold across it.

For the *what does each model do* deep dive, see [Reconciliation Engine](reconciliation_engine.md).

---

## Versions and packages

| Component | Version |
|---|---|
| `dbt-core`    | {{ dbt_version }}+ |
| `dbt-postgres` | 1.9+   |

External packages declared in `packages.yml`:

| Package | Used for |
|---|---|
| [`dbt-utils`](https://hub.getdbt.com/dbt-labs/dbt_utils/)                    | `unique_combination_of_columns`, `expression_is_true`, generate_series, etc. |
| [`dbt-expectations`](https://hub.getdbt.com/metaplane/dbt_expectations/)      | Distribution and statistical tests on staging models. |
| [`dbt_project_evaluator`](https://hub.getdbt.com/dbt-labs/dbt_project_evaluator/) | Lints the project for fanout, missing PK tests, hard-coded refs, naming conventions. |

Install them with `make dbt-deps` (which is just `dbt deps` under the hood).

---

## Directory layout

```
dbt_project/
├── dbt_project.yml         # project config + per-folder materialization defaults
├── packages.yml            # external dbt package dependencies
├── profiles.yml            # env-driven Postgres connection
├── seeds/                  # tolerance_rules.csv + materiality.csv (the recon-as-code surface)
├── snapshots/              # SCD2 history (chart of accounts)
├── macros/                 # reusable Jinja+SQL: assert_balanced, get_tolerance, categorize_break
├── models/
│   ├── _sources.yml        # 11 raw.* tables, freshness on gl_journal, generic tests
│   ├── staging/            # one stg_ model per source table (materialised as views)
│   ├── intermediate/       # joined / enriched int_ models (materialised as views)
│   └── marts/recon/        # 9 reconciliation marts (materialised as tables)
└── tests/                  # singular SQL tests using the assert_balanced macro
```

---

## Schema layout in Postgres

dbt writes to one schema per layer, all prefixed with the project name (`glrecon_*`):

```
glrecon                  -- the dbt connection's default schema (unused; we always specify one)
glrecon_seeds            -- tolerance_rules, materiality
glrecon_staging          -- stg_* views
glrecon_intermediate     -- int_* views
glrecon_marts            -- recon_* tables
snapshots                -- SCD2 snapshot tables
```

Configured in `dbt_project.yml`:

```yaml
models:
  glrecon:
    staging:      { +schema: staging,      +materialized: view }
    intermediate: { +schema: intermediate, +materialized: view }
    marts:
      recon:      { +schema: marts,        +materialized: table }
```

---

## Modelling conventions

### Naming

| Prefix | Layer | Example |
|---|---|---|
| `stg_` | Staging      | `stg_gl_journal` |
| `int_` | Intermediate | `int_subledger_postings` |
| `recon_` | Mart         | `recon_control_account` |

### Materialisation

- **Staging**: views. Cheap to rebuild and rarely queried directly.
- **Intermediate**: views. They are heavy joins, but the recon marts always materialise downstream so we don't double-cache.
- **Marts**: tables. Queried by Streamlit, exported to the auditor pack — they need to be cheap to read.
- **`recon_transaction_level`**: incremental table, `merge` strategy, 14-day overlap window for late-arriving rows.

### Tests

Generic tests live next to each model in the corresponding `_*.yml`. Singular SQL tests that span multiple models live under `tests/` and use the `assert_balanced` macro. dbt unit tests live colocated with the model they exercise (in `_recon.yml`) and use synthetic input rows — they don't touch Postgres.

### Model contracts

Two recon marts have **enforced model contracts** (`+contract: { enforced: true }`):

- `recon_control_account`
- `recon_transaction_level`

This makes the column names, types, and not-null constraints part of the public API. Downstream consumers (Streamlit, the audit trail writer) can rely on them not silently changing.

### Source freshness

`gl_journal` declares freshness on `ingested_at`:

- `warn_after`: 12 hours
- `error_after`: 24 hours

In production this would be checked by the orchestrator before each daily run.

---

## Macros

| Macro | What it does |
|---|---|
| `assert_balanced(model, group_by, …)` | Returns one row per unbalanced group. Used in singular SQL tests. |
| `tolerance_for(account_code_col)`     | Emits `LEFT JOIN`s that resolve the per-account tolerance with `DEFAULT` fallback. |
| `coalesce_tolerance(field)`           | Companion to `tolerance_for`; emits the `coalesce(…specific.…, …default.…)` expression. |
| `categorize_break(...)`               | Maps the structural shape of a break to one of five named classes. Stays aligned with `data_generator/inject_breaks.py`. |

---

## Snapshots

`chart_of_accounts_snapshot` uses `strategy: check` against five columns: `account_name`, `account_type`, `parent_account_code`, `is_control_account`, `subledger_source`. Whenever any of those change, dbt closes the old `dbt_valid_to` and opens a new row. This is what enables historical recon backfills against a point-in-time COA.

Run `dbt snapshot` independently of `dbt build` if you want to capture the COA without a full rebuild.

---

## Exposures

Two exposures are declared in `_recon.yml`:

- `streamlit_recon_cockpit` (type: `dashboard`) — depends on six recon marts
- `auditor_evidence_pack` (type: `analysis`) — depends on four recon marts

They show up in the `dbt docs` lineage so reviewers can see the full path from `raw.gl_journal` to the controller's morning dashboard.

---

## Running the project

| Command | What it does |
|---|---|
| `make dbt-deps`       | Installs the three external packages into `dbt_project/dbt_packages/`. |
| `make run`            | Full build: `dbt build` (seeds + snapshot + models + 138 tests). |
| `make dbt-docs`       | Generates and serves the `dbt docs` lineage site at `http://localhost:8080`. |
| `dbt test --select stg_*` | Runs only the staging-layer tests (handy after a source-schema change). |
| `dbt run --full-refresh --select recon_transaction_level` | Forces a full rebuild of the incremental matching engine. |

For ad-hoc invocations from the project root, you need to set the profiles directory:

```bash
cd dbt_project && DBT_PROFILES_DIR=. dbt <command>
```

The Makefile targets do this for you.
