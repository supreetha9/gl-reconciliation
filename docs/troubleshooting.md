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
