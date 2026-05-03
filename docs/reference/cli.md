# CLI Reference

The `data_generator.cli` module exposes a Typer command-line interface for generating synthetic data, loading it into Postgres, and inspecting the result.

Invoke as:

```bash
python -m data_generator.cli <command> [options]
```

All commands accept `--help` for the canonical flag list.

---

## `generate`

Generate synthetic AP, AR, Inventory, and General Ledger CSVs to disk.

```bash
python -m data_generator.cli generate \
    --days 30 \
    --seed 42 \
    --output-dir ./data/raw \
    --log-level INFO
```

| Flag | Default | Description |
|---|---|---|
| `--days`        | 90              | Window length in calendar days. End-date is `today`. |
| `--seed`        | 42              | RNG seed. Same seed → byte-identical output. |
| `--output-dir`  | `./data/raw`    | Where the CSVs are written. |
| `--log-level`   | `INFO`          | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

Side effects: writes one CSV per `raw.*` table to `output_dir`, plus `_breaks_log.csv` listing every injected perturbation.

---

## `load`

Truncate the `raw.*` tables and `COPY` the most recently generated CSVs into Postgres.

```bash
python -m data_generator.cli load --output-dir ./data/raw
```

| Flag | Default | Description |
|---|---|---|
| `--output-dir`  | `./data/raw`    | Directory to read CSVs from. |
| `--log-level`   | `INFO`          | Logging verbosity. |

The loader is **destructive** — it truncates child tables first (FK-aware order) and reloads from scratch. This is the right pattern for a synthetic-data dev loop; the production pipeline would use dbt incremental upserts instead.

---

## `seed`

Convenience target — runs `generate` followed by `load` without writing CSVs to disk.

```bash
python -m data_generator.cli seed --days 30 --seed 42
```

| Flag | Default | Description |
|---|---|---|
| `--days`        | 90 | Window length. |
| `--seed`        | 42 | RNG seed (note: the underlying flag here is `--seed`, not `--seed-value`). |
| `--log-level`   | `INFO` | Logging verbosity. |

This is the most commonly used command day-to-day.

---

## `summary`

Print row counts for every table in the `raw` schema. Sanity check after a load.

```bash
python -m data_generator.cli summary
```

Sample output:

```
       Postgres raw.* row counts
┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┓
┃ Table                ┃    Rows ┃
┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━┩
│ raw.ap_invoices      │  10,000 │
│ raw.ap_payments      │   6,503 │
│ raw.ar_invoices      │  15,000 │
│ raw.gl_journal       │ 100,050 │
│ raw.inv_transactions │   8,400 │
└──────────────────────┴─────────┘
```

---

## Environment-variable overrides

Every CLI flag can also be set via an environment variable prefixed with `GLRECON_`:

| Flag | Env var |
|---|---|
| `--days`        | `GLRECON_DAYS`        |
| `--seed`        | `GLRECON_SEED`        |
| `--output-dir`  | `GLRECON_OUTPUT_DIR`  |

Pydantic-settings nesting works for the volume and break-rate sub-models too:

```bash
GLRECON_BREAKS__TIMING_DIFF=0.10 python -m data_generator.cli seed
```

This bumps the timing-difference injection rate to 10% just for that one run.

---

## Exit codes

| Code | Meaning |
|---|---|
| `0`  | Success.   |
| `1`  | Generic failure — check the logs. |
| `2`  | Invalid CLI flags (Typer exit code). |

---

## Recon engine

The `recon_engine.cli` module provides a Dagster-free entry point to the full reconciliation pipeline. Use it from cron, GitHub Actions, or for ad-hoc backfills.

```bash
python -m recon_engine.cli <command> [options]
```

### `run-recon`

End-to-end: synthetic data load → `dbt build` → audit-trail write → Slack alert.

```bash
python -m recon_engine.cli run-recon
python -m recon_engine.cli run-recon --skip-data-load     # use existing raw.* data
python -m recon_engine.cli run-recon --skip-dbt           # use existing marts
python -m recon_engine.cli run-recon --triggered-by manual:vsg
```

| Flag | Default | Description |
|---|---|---|
| `--skip-data-load`  | false           | Skip the synthetic data generator + Postgres load step. |
| `--skip-dbt`        | false           | Skip the `dbt build`; use the existing marts as-is. |
| `--triggered-by`    | `manual:cli`    | Recorded verbatim in `audit.recon_runs.triggered_by`. |

Reads `MATERIALITY_THRESHOLD_USD` and `SLACK_WEBHOOK_URL` from the environment (see [Configuration](configuration.md)).

### `list-runs`

Show the most recent rows in `audit.recon_runs`.

```bash
python -m recon_engine.cli list-runs --limit 20
```

### `show-run`

Detailed view of a single run plus its per-check results. Accepts a full UUID or an 8-character prefix:

```bash
python -m recon_engine.cli show-run abc12345
python -m recon_engine.cli show-run 3b3d2635-8ba2-4a0f-a1a7-801f81e1b8c3
```
