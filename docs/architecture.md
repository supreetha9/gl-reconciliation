# Architecture

This page explains the system end-to-end: what each layer is responsible for, why we made the design choices we did, and how data flows from synthetic source systems all the way to the auditor evidence pack.

---

## High-level diagram

```{mermaid}
flowchart LR
  subgraph sources [Source Systems - simulated]
    AP[AP Sub-ledger]
    AR[AR Sub-ledger]
    INV[Inventory Sub-ledger]
    GL[General Ledger]
  end

  subgraph bronze [Bronze - raw landed]
    rawTbls[raw.* tables in Postgres]
  end

  subgraph silver [Silver - dbt staging + intermediate]
    stg[staging models]
    int[intermediate models]
  end

  subgraph gold [Gold - recon marts]
    rcChecks[9 recon checks]
  end

  subgraph ops [Orchestration + Audit]
    dag[Dagster daily schedule]
    audit[audit.recon_runs immutable log]
    slack[Slack alerts above materiality]
  end

  subgraph ui [Consumption]
    st[Streamlit Recon Cockpit]
    ev[Auditor Evidence Pack]
  end

  sources --> bronze --> silver --> gold --> st
  gold --> ev
  dag --> bronze
  dag --> silver
  dag --> gold
  gold --> audit
  gold --> slack
```

---

## The medallion layers

The project follows the standard **bronze → silver → gold** layout you would find in any 2026-era warehouse. Each layer has a precise responsibility, and we never skip layers.

### Bronze (raw)

PostgreSQL schema: `raw`.

- Untouched landings from the AP, AR, Inventory, and GL "source systems".
- Foreign-key constrained where it makes sense (every sub-ledger row is FK'd to `raw.dim_entity`).
- Indexed on `posting_date` for downstream filtering.
- Loaded by [`data_generator/loader.py`](https://github.com/supreetha9/gl-reconciliation/blob/main/data_generator/loader.py) using `COPY` for performance.
- Initialised on first Postgres start by the SQL files under `db/init/`.

### Silver (staging + intermediate)

PostgreSQL schemas: `glrecon_staging`, `glrecon_intermediate`.

- **Staging**: one `stg_` model per source table. Type-cast, light renaming, dedup. Materialised as views.
- **Intermediate**: joined and enriched models. Materialised as views. The four key intermediate models are:
  - `int_subledger_postings` — UNION-ALL translation of every AP / AR / Inventory event into the GL line shape
  - `int_subledger_trial_balance` — running balance per `(entity, account, posting_date)`
  - `int_gl_trial_balance` — symmetric to above but built from the GL feed
  - `int_dim_account_hierarchy` — recursive CTE walking the chart-of-accounts tree

### Gold (recon marts)

PostgreSQL schema: `glrecon_marts`.

- Nine reconciliation marts, materialised as tables.
- Two of the marts (`recon_control_account`, `recon_transaction_level`) have **enforced model contracts** that pin column names, types, and not-null constraints.
- `recon_transaction_level` is **incremental** (`merge` strategy, 14-day overlap window).
- The remaining marts are full-refresh tables.
- See [Reconciliation Engine](reconciliation_engine.md) for the deep dive.

### Audit

PostgreSQL schema: `audit`.

- `audit.recon_runs` — append-only run log capturing run id, started/finished timestamps, git sha, dbt manifest hash, source row counts, and an evidence-pack URL.
- `audit.recon_check_results` — per-check pass/warn/fail counts, total break value, materiality threshold, and JSON details.
- The schema and tables are auditor-readable but not mutable from application code.

---

## Data flow

The system is a daily batch pipeline. A single run looks like:

```{mermaid}
sequenceDiagram
    participant SRC as Source ERPs
    participant LOAD as data_generator
    participant RAW as Postgres raw.*
    participant DBT as dbt build
    participant MARTS as Postgres marts
    participant DASH as Streamlit
    participant SLACK as Slack
    participant AUDIT as audit.recon_runs

    SRC->>LOAD: nightly extracts (CSV)
    LOAD->>RAW: COPY into bronze tables
    DBT->>RAW: read sources
    DBT->>MARTS: write 9 recon marts
    DBT->>AUDIT: write run + check results
    MARTS->>DASH: queried by Recon Cockpit
    MARTS->>SLACK: alert if breaks above materiality
```

In production the Source ERPs would be real systems (NetSuite, SAP, Workday Financials, etc.) and a tool like Fivetran or Airbyte would take the place of the local `data_generator` script. Everything downstream of `raw.*` is unchanged.

---

## Why these choices

### Why PostgreSQL locally?

We built and validated the project on Postgres because it is free, runs in Docker in seconds, and uses the same SQL surface (window functions, recursive CTEs, `MERGE`-equivalent upserts) as the cloud warehouses everyone uses in production. Every dbt model in the project compiles unchanged on Snowflake or BigQuery; only the connection profile changes.

### Why dbt for the recon engine?

Because reconciliation logic is, fundamentally, transformation logic with assertions. dbt gives us four things at once:

1. **Versioned SQL** in git, with PR review.
2. **Generic and singular tests** built into the same toolchain that runs the transformations.
3. **Snapshots** so we can prove what the chart of accounts looked like on any historical period close.
4. **Lineage** — `dbt docs` shows every column, every test, every downstream consumer.

The alternative ("run a Python ETL that emits results, then bolt validation on top") loses the lineage and the testing in one move.

### Why a separate sub-ledger postings model?

The cleanest way to compare two ledgers is to project both into the same shape, then anti-join. `int_subledger_postings` is exactly that projection: every AP invoice, AP payment, AR invoice, AR receipt, inventory receipt, COGS posting, and inventory adjustment is translated into one or two GL-line-shaped rows that can be matched against `stg_gl_journal` directly. The translation rules are described in [Reconciliation Engine](reconciliation_engine.md).

### Why tolerance-based matching, not strict equality?

Real recons allow for `$0.01` rounding deltas, T+1 timing differences, and FX rounding noise. A strict-equality matcher would flag thousands of false positives every day and quickly lose the trust of the controllers who depend on it. We model tolerances explicitly in `seeds/tolerance_rules.csv` so they can be tuned per control account, version-controlled, and reviewed.

### Why an immutable audit trail?

SOX requires evidence that controls were operating effectively over time. An auditor walking through a quarterly review wants to see that the daily recon ran, what version of the code produced the result, and what the result was. The `audit.recon_runs` table captures all of that and is never updated in place — a re-run is a new row.

### Why the recon engine is incremental but the dashboards are full-refresh

The transaction-level matching engine handles tens of millions of rows in steady state, so it is configured as `incremental` with a 14-day overlap window (long enough to catch any timing-related break that posts late). The downstream marts that drive the Streamlit cockpit (aging, summary, variance) are small enough to full-refresh in seconds.

---

## What lives where (cheat sheet)

| Concern | Location |
|---|---|
| Sub-ledger row generation             | [`data_generator/subledgers.py`](https://github.com/supreetha9/gl-reconciliation/blob/main/data_generator/subledgers.py) |
| GL row generation (double-entry)      | [`data_generator/gl.py`](https://github.com/supreetha9/gl-reconciliation/blob/main/data_generator/gl.py) |
| Break injection                       | [`data_generator/inject_breaks.py`](https://github.com/supreetha9/gl-reconciliation/blob/main/data_generator/inject_breaks.py) |
| Postgres bootstrap (DDL)              | [`db/init/`](https://github.com/supreetha9/gl-reconciliation/tree/main/db/init) |
| dbt sources                           | [`dbt_project/models/_sources.yml`](https://github.com/supreetha9/gl-reconciliation/blob/main/dbt_project/models/_sources.yml) |
| Sub-ledger → GL projection            | [`int_subledger_postings.sql`](https://github.com/supreetha9/gl-reconciliation/blob/main/dbt_project/models/intermediate/int_subledger_postings.sql) |
| Trial balances                        | [`int_subledger_trial_balance.sql`](https://github.com/supreetha9/gl-reconciliation/blob/main/dbt_project/models/intermediate/int_subledger_trial_balance.sql), [`int_gl_trial_balance.sql`](https://github.com/supreetha9/gl-reconciliation/blob/main/dbt_project/models/intermediate/int_gl_trial_balance.sql) |
| Recon marts                           | [`dbt_project/models/marts/recon/`](https://github.com/supreetha9/gl-reconciliation/tree/main/dbt_project/models/marts/recon) |
| Tolerance + materiality configuration | [`dbt_project/seeds/`](https://github.com/supreetha9/gl-reconciliation/tree/main/dbt_project/seeds) |
| Reusable recon macros                 | [`dbt_project/macros/`](https://github.com/supreetha9/gl-reconciliation/tree/main/dbt_project/macros) |
| Singular SQL tests                    | [`dbt_project/tests/`](https://github.com/supreetha9/gl-reconciliation/tree/main/dbt_project/tests) |
| Audit trail schema                    | [`db/init/05_audit.sql`](https://github.com/supreetha9/gl-reconciliation/blob/main/db/init/05_audit.sql) |
