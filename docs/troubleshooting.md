# Troubleshooting

A grab-bag of common issues and the fixes that work.

---

## `pyenv: dbt: command not found` (or any `gl_env` binary)

`pyenv-virtualenv` auto-activation isn't loaded in your shell. Two fixes:

1. **Recommended:** add the activation hook to your shell rc file:

   ```bash
   echo 'eval "$(pyenv virtualenv-init -)"' >> ~/.zshrc
   exec zsh
   ```

2. **Workaround:** call binaries by absolute path. The Makefile already does this for `dbt`. For ad-hoc commands, use:

   ```bash
   ~/.pyenv/versions/3.13.3/envs/gl_env/bin/dbt --version
   ```

---

## `dbt build` fails with `relation "raw.dim_entity" does not exist`

Postgres is up but you haven't loaded the synthetic data yet. Run:

```bash
make seed
```

If `seed` itself fails with the same error, the Postgres init scripts didn't run. Reset the volume:

```bash
docker compose down -v   # this destroys the database — only do this locally
make up
make seed
```

---

## `dbt deps` fails with `">=1.8" is not a valid semantic version`

You're on a project that pins `require-dbt-version` with comma syntax (`">=1.8,<1.10"`). Some dbt versions are stricter about parsing this. The repo uses the list syntax:

```yaml
require-dbt-version: [">=1.8.0", "<2.0.0"]
```

If you see this error, check `dbt_project.yml` and rewrite to that form.

---

## `pg_isready: command not found` when running `make up`

You're invoking `make up` but Docker Desktop isn't running. Start Docker Desktop and retry. The Makefile waits up to 30 seconds for Postgres to become healthy; if Docker isn't running, the wait loop will eventually time out.

---

## `assert_subledger_postings_balanced` fails after a generator change

The `int_subledger_postings` model translates each sub-ledger row into balanced double-entry pairs. If you changed the inventory account-routing logic in `data_generator/subledgers.py` and forgot to update the matching CASE expressions in `int_subledger_postings.sql`, the projection will be unbalanced.

Diagnose with:

```sql
SELECT source_system, source_doc_id,
       sum(debit_usd) AS td, sum(credit_usd) AS tc,
       sum(debit_usd) - sum(credit_usd) AS variance
FROM glrecon_intermediate.int_subledger_postings
GROUP BY source_system, source_doc_id
HAVING abs(sum(debit_usd) - sum(credit_usd)) > 0.01
LIMIT 10;
```

The first ten unbalanced rows usually point straight at the bug.

---

## `assert_gl_journal_balanced` reports hundreds of unbalanced journals

This is **expected** when break injection is enabled. The `AMOUNT_MISMATCH` and `FX_ROUNDING` break classes intentionally perturb single GL lines, which breaks the per-journal balance invariant. The test is configured to `warn_if > 0` and `error_if > 1500` for exactly this reason.

If the count climbs above 1500 on the seed dataset, then there's a real bug — likely in the GL generator or the break injector itself.

---

## Sphinx build fails with `Could not import extension sphinxcontrib.mermaid`

The `[docs]` extra wasn't installed. Run:

```bash
pip install -e ".[dev,dbt,docs]"
```

inside the `gl_env` virtualenv.

---

## `make docs` opens but mermaid diagrams don't render

Mermaid loads from a CDN. If you're on a restricted network, the diagrams will appear as raw `flowchart LR ...` text. Either whitelist `cdn.jsdelivr.net` or pin a local copy of mermaid.js under `docs/_static/`.

---

## Postgres takes forever to truncate before a reload

The `loader.py` truncate-and-COPY pattern uses `TRUNCATE ... CASCADE`, which acquires an `ACCESS EXCLUSIVE` lock. If anything (psql, pgAdmin, dbt) is connected to the database with an open transaction, the truncate will block.

Quick fix: close all the connections, then retry. To see what's blocking:

```sql
SELECT pid, usename, application_name, state, query
FROM pg_stat_activity
WHERE datname = 'glrecon' AND state <> 'idle';
```

---

## "Sandbox: write access denied" when installing into `~/.pyenv/...`

If you're running these commands inside a sandboxed shell (some IDEs or AI agents apply this), you need to escalate to a non-sandboxed run. For local development this never applies — your normal terminal is unrestricted.

---

## My Streamlit cockpit doesn't refresh when the data changes

Streamlit caches query results aggressively. After a `make seed && make run`, hit `R` in the Streamlit app or restart it with `streamlit run streamlit_app/Home.py` to pick up the new data.

---

## I want to run against Snowflake, not Postgres

The dbt project is warehouse-portable by design. You need to:

1. Add `dbt-snowflake` to `pyproject.toml` (`[dbt-snowflake]` extra) and reinstall.
2. Replace `dbt_project/profiles.yml` with a Snowflake profile (or extend it as a second target).
3. Use a Snowflake-compatible loader instead of `data_generator/loader.py` (the COPY-from-stdin pattern won't work; use Snowflake's `COPY INTO` from S3 or the Snowpark API).
4. Re-run `make dbt-deps` to fetch packages compiled for Snowflake.

The recon SQL itself does not need to change — only the storage and ingestion layers.

---

## `make dagster` says `dagster: command not found`

The `[dagster]` extra isn't installed. Run:

```bash
pip install -e ".[dagster]"
```

Or do the all-in-one bootstrap that includes Dagster, Streamlit, and the docs toolchain:

```bash
make all-env
```

---

## Dagster UI loads but assets show "no manifest"

The `dagster-dbt` integration needs the dbt manifest to exist before it can build the asset graph. Run a dbt build first:

```bash
make run    # produces dbt_project/target/manifest.json
make dagster
```

If the manifest is stale (you've changed dbt models but didn't rebuild), the UI may fail to materialise. Re-run `make run` and refresh the Dagster UI.

---

## My Slack alerts aren't firing

Three things to check, in order:

1. `SLACK_WEBHOOK_URL` is unset — the alerter is intentionally a no-op in that case (it logs a `slack.alert.skipped` warning). Set the env var in `.env` and restart Dagster / your CLI.
2. The webhook URL is malformed or revoked — Slack will return non-200 and the alerter logs `slack.alert.failed` with the status code.
3. Every check is below `MATERIALITY_THRESHOLD_USD` (defaults to `$10,000`) — the alert is sent but the body says "No checks above the materiality threshold". Drop the threshold to verify: `MATERIALITY_THRESHOLD_USD=0 make recon-run`.

---

## Streamlit cockpit shows "No recon runs found yet"

The `audit.recon_runs` table is empty. Trigger a run:

```bash
make recon-run
```

Then refresh the cockpit. If you see the same message after a successful run, double-check the `POSTGRES_*` env vars in your shell match those in the cockpit's environment.

---

## Streamlit pages show stale data after a new run

The pages are wrapped in `@st.cache_data(ttl=60)`. Wait 60 seconds and refresh, or hit `R` in the Streamlit window to force a rerun and bypass the cache.

---

## Auditor evidence pack download is empty / corrupt

If the workbook downloads but Excel can't open it, the `recon_engine.evidence` builder probably hit an unexpected NULL in one of the marts. Check the Streamlit terminal for a Python traceback — the most common culprit is `recon_transaction_level` being missing for a run that didn't get past the dbt build (status = `ERROR` in `audit.recon_runs`).

Pick a different run from the dropdown. The evidence pack only makes sense for runs whose status is `PASS`, `WARN`, or `FAIL`.

---

## `recon_engine.cli run-recon` exits non-zero

Three usual suspects:

- **Postgres unreachable** — check `make up` and the `POSTGRES_*` env vars.
- **`dbt build` hard-error (exit code 2)** — the CLI surfaces dbt's exit code. dbt logs everything to stdout; scroll up in your terminal to find the failing model.
- **Synthetic data generation crashed** — usually a stale dbt schema mismatch after a model change. Run `make seed && make run` once manually to re-bootstrap.

The CLI always writes the failure to `audit.recon_runs` with `status = 'ERROR'` so the failure is captured even when the run aborted mid-flight.
