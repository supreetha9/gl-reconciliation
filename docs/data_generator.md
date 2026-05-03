# Data Generator

The Python package under [`data_generator/`](https://github.com/supreetha9/gl-reconciliation/tree/main/data_generator) produces realistic synthetic AP, AR, Inventory, and General Ledger postings, intentionally injects five classes of reconciliation breaks, and loads everything into Postgres.

It exists for two reasons: to make the project runnable on a clean machine without any real ERP data, and to give the recon engine something *interesting* to find.

---

## Module layout

| Module | Responsibility |
|---|---|
| [`config.py`](https://github.com/supreetha9/gl-reconciliation/blob/main/data_generator/config.py)             | Centralised `pydantic-settings` configuration. Sub-models for `Volumes` and `BreakRates`. Reads `.env`. |
| [`logging_setup.py`](https://github.com/supreetha9/gl-reconciliation/blob/main/data_generator/logging_setup.py) | `structlog` JSON logging in CI, pretty console output in TTYs. |
| [`reference.py`](https://github.com/supreetha9/gl-reconciliation/blob/main/data_generator/reference.py)        | Chart of accounts (24 accounts, control-account flagged), 3 legal entities, deterministic FX random walk. |
| [`utils.py`](https://github.com/supreetha9/gl-reconciliation/blob/main/data_generator/utils.py)                | Helpers: deterministic ID minting, business-day sampling, USD conversion. |
| [`subledgers.py`](https://github.com/supreetha9/gl-reconciliation/blob/main/data_generator/subledgers.py)      | AP / AR / Inventory generators — one function per sub-table. |
| [`gl.py`](https://github.com/supreetha9/gl-reconciliation/blob/main/data_generator/gl.py)                       | Translates each sub-ledger row into a balanced double-entry journal entry, plus daily manual JEs. |
| [`inject_breaks.py`](https://github.com/supreetha9/gl-reconciliation/blob/main/data_generator/inject_breaks.py) | Five break classes applied to the clean GL feed; emits a side-channel `_breaks_log` for assertions. |
| [`pipeline.py`](https://github.com/supreetha9/gl-reconciliation/blob/main/data_generator/pipeline.py)          | End-to-end orchestrator returning a `GeneratedDataset`. |
| [`loader.py`](https://github.com/supreetha9/gl-reconciliation/blob/main/data_generator/loader.py)              | Truncate-and-`COPY` Postgres loader, FK-aware load order. |
| [`cli.py`](https://github.com/supreetha9/gl-reconciliation/blob/main/data_generator/cli.py)                    | Typer CLI wrapping the pipeline + loader. |

---

## Determinism guarantees

The pipeline is **fully deterministic for a given `--seed`**. This matters because:

- The smoke tests in [`tests/test_pipeline_smoke.py`](https://github.com/supreetha9/gl-reconciliation/blob/main/tests/test_pipeline_smoke.py) assert on exact break counts.
- The auditor evidence pack must reproduce identical numbers when re-run on the same inputs.
- CI builds need byte-identical outputs to be cacheable.

The seeded `numpy.random.Generator` is threaded through every generator function. There is no global RNG state, no implicit `time.time()` calls, no Faker without an explicit seed.

---

## Realistic break injection

The five break classes the generator injects are **the same five classes the recon engine recognises**. This is by design — the engine's `categorize_break` macro is kept in lockstep with `inject_breaks.py`.

| Class | Default rate | What it does |
|---|---|---|
| `timing_diff`             | 2.0%   | Shifts `posting_date` on the GL row forward by 1-2 days, leaving the sub-ledger row at T. |
| `amount_mismatch`         | 0.5%   | Adds `±$0.01-$0.50` noise to the GL line's USD amount. |
| `missing_gl_posting`      | 0.3%   | Drops the entire journal entry from the GL feed (the most impactful class). |
| `unauthorized_manual_je`  | 0.2%   | Re-points a manual JE's credit line to a control account (SOX red flag). |
| `fx_rounding`             | 1.0%   | Adds `±$0.01-$0.05` noise on non-USD GL postings. |

All rates are tunable in `config.BreakRates`. To stress-test the recon engine, override them at the CLI level (or in `.env` via `GLRECON_BREAKS__TIMING_DIFF=0.10`).

The injector emits a `_breaks_log.csv` alongside the data CSVs containing one row per perturbation: `(journal_id, journal_line_id, break_class, detail)`. The smoke test suite uses this to assert that the breakdown of break classes matches the rates exactly.

---

## CLI

The Typer CLI exposes four commands. See [Reference → CLI](reference/cli.md) for the full flag reference.

```bash
# Generate CSVs to ./data/raw (no Postgres needed)
python -m data_generator.cli generate --days 30 --seed 42

# Truncate the raw.* tables and COPY the most recently generated CSVs
python -m data_generator.cli load

# generate + load in one shot (skips writing CSVs to disk)
python -m data_generator.cli seed

# Print row counts in raw.* (sanity check after load)
python -m data_generator.cli summary
```

The `seed` command is the one most developers use day-to-day; `generate` and `load` exist for cases where you want to inspect the CSVs or load a pre-existing dataset.

---

## Volume defaults (90-day window)

```{eval-rst}
================================  ========
Table                             Default
================================  ========
``raw.ap_invoices``                10,000
``raw.ap_payments``                 8,000
``raw.ap_accruals``                   500
``raw.ar_invoices``                15,000
``raw.ar_receipts``                12,000
``raw.ar_credit_memos``               300
``raw.inv_transactions``            8,400
Manual JEs / business day               5
================================  ========
```

Override any of these via the `Volumes` sub-model in `config.py` or the `GLRECON_VOLUMES__*` environment variables.

---

## Smoke tests

Five tests in [`tests/test_pipeline_smoke.py`](https://github.com/supreetha9/gl-reconciliation/blob/main/tests/test_pipeline_smoke.py) lock down the most important invariants:

1. The pipeline runs end-to-end and produces all eleven expected tables.
2. The clean GL feed (before break injection) is journal-balanced — every `journal_id` has `sum(debit) = sum(credit)` in USD.
3. Break injection is reproducible — same `(seed, settings)` produce byte-identical breaks logs.
4. All five break classes are present at elevated injection rates.
5. The chart of accounts contains the required AP, AR, and Inventory control accounts.

Run them with `make test`. The full suite executes in under 10 seconds on a standard laptop.

---

## API reference

For the canonical API, read the source directly — every public function and class has a docstring:

- [`data_generator.config`](https://github.com/supreetha9/gl-reconciliation/blob/main/data_generator/config.py)
- [`data_generator.reference`](https://github.com/supreetha9/gl-reconciliation/blob/main/data_generator/reference.py)
- [`data_generator.subledgers`](https://github.com/supreetha9/gl-reconciliation/blob/main/data_generator/subledgers.py)
- [`data_generator.gl`](https://github.com/supreetha9/gl-reconciliation/blob/main/data_generator/gl.py)
- [`data_generator.inject_breaks`](https://github.com/supreetha9/gl-reconciliation/blob/main/data_generator/inject_breaks.py)
- [`data_generator.pipeline`](https://github.com/supreetha9/gl-reconciliation/blob/main/data_generator/pipeline.py)
- [`data_generator.loader`](https://github.com/supreetha9/gl-reconciliation/blob/main/data_generator/loader.py)
