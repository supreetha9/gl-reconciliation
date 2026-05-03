# Development

This page covers the local development workflow: running the test suite, linting, and the cookbook for adding a new reconciliation check end-to-end.

If you're setting up the project for the first time, start with [Getting Started](getting_started.md). This page assumes you already have `gl_env` activated and the project running locally.

---

## Daily loop

The fastest inner loop:

```bash
# Edit a SQL file under dbt_project/...
make run                    # full dbt build (~6s on the seed dataset)

# Edit a Python file under data_generator/...
make test                   # pytest smoke suite (~10s)
make lint                   # ruff (~1s)

# Edit a docs page under docs/...
# `make docs` runs sphinx-autobuild, which live-reloads the browser as you save.
```

If a build breaks, the `dbt build` summary line at the bottom tells you what failed and where the compiled SQL lives. You can copy-paste that compiled SQL into `psql` directly:

```bash
docker compose exec postgres psql -U glrecon -d glrecon \
  -f dbt_project/target/compiled/glrecon/models/marts/recon/recon_control_account.sql
```

---

## Testing

| Command | Scope |
|---|---|
| `make test`                                                | All pytest smoke tests on the data generator |
| `pytest tests/test_pipeline_smoke.py::test_clean_gl_is_journal_balanced -v` | A single Python test |
| `make run`                                                 | All dbt tests (138 generic + singular + 3 unit + the build) |
| `cd dbt_project && DBT_PROFILES_DIR=. dbt test --select source:raw` | Source-layer tests only |
| `cd dbt_project && DBT_PROFILES_DIR=. dbt test --select recon_control_account` | Tests on a single mart |

When you add a new model or test, expect both `pytest` and `dbt build` to be green before opening a PR.

---

## Linting

We use `ruff` for Python (config in `pyproject.toml`):

```bash
make lint           # check
make fmt            # auto-format
ruff check . --fix  # auto-fix what's safe
```

The `B008` rule is disabled because Typer's idiomatic API uses function calls in argument defaults — that's not a real bug.

There is no SQL linter wired in; the `dbt_project_evaluator` package gives us model-structure linting at `dbt build` time, which is enough for now. If we need column-level SQL formatting, [`sqlfluff`](https://sqlfluff.com/) is the right next addition.

---

## Conventions

- **Type hints everywhere in Python.** No exceptions in new code; `mypy` config is in `pyproject.toml`.
- **Pydantic v2 for any structured config.** Sub-models for grouping; environment variables override defaults via the `GLRECON_*` prefix.
- **Structured logging only.** No bare `print()`; use the `structlog` logger from `data_generator/logging_setup.py`.
- **Deterministic data wherever possible.** Pass the seeded `numpy.random.Generator` through; do not call `np.random.<x>()` from module scope.
- **Comments explain WHY, not WHAT.** Every recon model has a header comment block describing what business question it answers.
- **One PR, one concern.** A new recon check, a tolerance tweak, and a new staging column are three different PRs.

---

## Cookbook: adding a new reconciliation check

Suppose you want to add a check that flags duplicate vendor invoices (same vendor, same amount, same invoice date, different invoice IDs). Here is the end-to-end recipe.

### 1. Decide what the check produces

A check is a dbt mart whose rows are *exceptions*, with one column called `status` whose value is `PASS`, `WARN`, or `FAIL`. So the new mart will be `recon_duplicate_invoices` with one row per suspected duplicate.

### 2. Write the SQL

Create `dbt_project/models/marts/recon/recon_duplicate_invoices.sql`:

```jinja
/*
    recon_duplicate_invoices
    ------------------------
    Flags pairs of AP invoices with the same vendor, amount, and invoice
    date but different invoice IDs. A high-confidence duplicate-payment
    risk indicator.
*/

with candidates as (
    select
        vendor_id,
        invoice_date,
        amount_usd,
        array_agg(invoice_id order by invoice_id) as invoice_ids,
        count(*)                                  as duplicate_count
    from {{ ref('stg_ap_invoices') }}
    where status not in ('VOID', 'WRITTEN_OFF')
    group by vendor_id, invoice_date, amount_usd
    having count(*) > 1
)

select
    vendor_id,
    invoice_date,
    amount_usd,
    invoice_ids,
    duplicate_count,
    case when duplicate_count > 2 then 'FAIL' else 'WARN' end as status
from candidates
```

### 3. Document and test it in `_recon.yml`

```yaml
- name: recon_duplicate_invoices
  description: |
    Pairs of AP invoices with the same (vendor, date, amount) but different
    invoice IDs. High-confidence duplicate-payment risk.
  columns:
    - name: vendor_id
      data_tests: [not_null]
    - name: status
      data_tests:
        - accepted_values: { values: ['WARN', 'FAIL'] }
```

### 4. Add it to the scorecard

Append a CTE in `recon_summary.sql`:

```jinja
duplicates as (
    select
        'duplicate_invoices'                                as check_name,
        max(invoice_date)                                   as as_of_date,
        0                                                   as pass_count,
        sum(case when status = 'WARN' then 1 else 0 end)    as warn_count,
        sum(case when status = 'FAIL' then 1 else 0 end)    as fail_count,
        sum(case when status <> 'PASS' then amount_usd * (duplicate_count - 1) else 0 end) as breaks_value_usd
    from {{ ref('recon_duplicate_invoices') }}
)
```

…and add it to the final `union all`.

### 5. Update `_recon.yml`

Add `'duplicate_invoices'` to the `accepted_values` list on `recon_summary.check_name`.

### 6. (Optional) Update the data generator

If you want the check to reliably find something on a fresh seed, make `data_generator/subledgers.py` emit a few duplicates intentionally — `inject_breaks.py` is the right home for that mutation.

### 7. Run, test, commit

```bash
make run            # confirms the new mart builds and tests pass
make test           # confirms the data generator still ties out
git add dbt_project/models/marts/recon/recon_duplicate_invoices.sql \
        dbt_project/models/marts/recon/recon_summary.sql \
        dbt_project/models/marts/recon/_recon.yml
git commit -m "feat: add recon_duplicate_invoices check"
```

That's the whole loop. Most new checks are 30-80 lines of SQL plus a YAML stanza.

---

## Database access during development

| Action | Command |
|---|---|
| Open a `psql` shell on the running container | `docker compose exec postgres psql -U glrecon -d glrecon` |
| Tail the Postgres logs                       | `docker compose logs -f postgres` |
| Reset the database from scratch              | `docker compose down -v && make up && make seed && make run` |
| Inspect a compiled dbt model                 | `cat dbt_project/target/compiled/glrecon/models/.../<model>.sql` |
| Run a single dbt model                       | `cd dbt_project && DBT_PROFILES_DIR=. dbt run --select <model_name>` |

---

## Project structure cheat sheet

If you forget where to find something, this map should help:

| What you want to change | Where to look |
|---|---|
| Synthetic data shape           | `data_generator/subledgers.py`, `data_generator/gl.py` |
| What breaks get injected       | `data_generator/inject_breaks.py` |
| Postgres bronze schema         | `db/init/*.sql` |
| dbt staging                    | `dbt_project/models/staging/` |
| Recon logic                    | `dbt_project/models/marts/recon/` |
| Tolerance / materiality config | `dbt_project/seeds/` |
| Reusable SQL macros            | `dbt_project/macros/` |
| Singular SQL tests             | `dbt_project/tests/` |
| Smoke tests on the generator   | `tests/test_pipeline_smoke.py` |
| This documentation             | `docs/` |

---

## Continuous integration (planned)

A GitHub Actions workflow would lint, run the pytest smoke suite, run `dbt parse`, and (against a CI Postgres service) run `dbt build` against the seed dataset. The badge on the README links to the latest run. See the Roadmap section in the project README for the broader plan.
