# Reconciliation Engine

The reconciliation engine is the heart of the project. It is implemented as a set of dbt models under [`dbt_project/models/marts/recon/`](https://github.com/supreetha9/gl-reconciliation/tree/main/dbt_project/models/marts/recon) and produces nine reconciliation marts. This page explains each check, the matching methodology, and the configuration model that drives them.

---

## Methodology

A reconciliation in this system is defined as: **"comparing two ledgers (or two views of the same ledger) and surfacing any disagreement above a configured tolerance."**

We always express this comparison in three steps:

1. **Project both sides into the same shape.** For control-account checks the shape is `(entity, account, posting_date, balance)`; for transaction-level matching it is `(source_doc_id, account, debit/credit_direction, amount)`.
2. **Anti-join.** A `FULL OUTER JOIN` between the two projections, keyed on the join columns, with a tolerance comparison on the value columns. Anything that doesn't match within tolerance is a break.
3. **Categorize the break.** The `categorize_break` macro classifies the failure mode (timing, amount, missing posting, etc.) so the controller's daily triage view can group the queue.

The shape projection lives in `int_subledger_postings`. The anti-join lives in `recon_transaction_level`. The categorization lives in `categorize_break.sql`.

---

## Tolerance and materiality

Two declarative configuration files drive the engine:

### `seeds/tolerance_rules.csv`

Per-control-account tolerances. The `DEFAULT` row is the fallback when an account isn't explicitly listed.

| account_code | amount_tolerance_usd | timing_tolerance_days | fx_tolerance_pct |
|---|---|---|---|
| `2000`    | 0.05  | 1 | 0.001 |
| `1200`    | 0.05  | 1 | 0.001 |
| `1300`    | 0.10  | 1 | 0.001 |
| `DEFAULT` | 0.01  | 0 | 0.0000 |

A break is anything where `abs(sl_amount - gl_amount) > amount_tolerance_usd` OR `abs(gl_posting_date - sl_posting_date) > timing_tolerance_days`.

### `seeds/materiality.csv`

Per-account materiality thresholds and severity classifications. Drives the WARN / FAIL classification in the control-account check and the alerting policy.

| account_code | materiality_usd | severity |
|---|---|---|
| `2000`    | 500   | HIGH   |
| `1200`    | 500   | HIGH   |
| `1300`    | 1000  | MEDIUM |
| `5000`    | 2000  | MEDIUM |
| `4000`    | 1000  | MEDIUM |
| `9999`    | 0     | HIGH   |
| `DEFAULT` | 1000  | LOW    |

These are real CSVs in the repo; they live with the project, get reviewed in PRs, and are loaded by `dbt seed` like any other reference data.

---

## The nine checks

### 1. `recon_control_account` — the headline

For each control account (AP=`2000`, AR=`1200`, INV=`1300`):
**sub-ledger ending balance must equal GL control-account balance per `(entity, account, posting_date)`, within tolerance.**

A break here is the highest-impact recon failure: it means the sub-ledger and the GL disagree about the company's outstanding payables / receivables / inventory on a given day. **This model has an enforced dbt model contract** (typed columns, not-null constraints).

Status field:

- `PASS` — variance below tolerance
- `WARN` — variance above tolerance but below materiality
- `FAIL` — variance at or above materiality

### 2. `recon_transaction_level` — the matching engine

The most algorithmically interesting model. Performs a `FULL OUTER JOIN` between `int_subledger_postings` and `stg_gl_journal` on `(source_system, source_doc_id, account_code, debit/credit direction)`, then applies the tolerance window. Unmatched rows on either side become breaks; matched rows with deltas above tolerance are categorized via the `categorize_break` macro.

This is the model that produces the Break Detail page in the cockpit. It is **incremental** with `merge` strategy, a 14-day overlap window for late-arriving rows, and an enforced model contract.

Categorized break classes (kept in lockstep with the data generator's break injection):

- `MISSING_GL_POSTING` — sub-ledger row exists, no GL counterpart
- `MISSING_SL_POSTING` — GL row claims a sub-ledger source but the sub-ledger has no record
- `AMOUNT_MISMATCH` — both sides exist, USD delta exceeds tolerance
- `TIMING_DIFF` — both sides exist, posting-date delta exceeds tolerance
- `FX_ROUNDING` — sub-cent delta on a non-USD currency posting
- `UNKNOWN` — categorization fell through; a non-zero count here is itself an alert

### 3. `recon_roll_forward` — the arithmetic invariant

Validates `opening_balance + period_activity = closing_balance` in **both** ledgers, independently. Catches silent restatements, missing opening balances after a backfill, and any other arithmetic drift that wouldn't surface in a side-by-side comparison.

### 4. `recon_variance_analysis` — the controller's morning view

Slices the control-account variance by entity, account, and currency. Filters to non-PASS rows only and ranks each day by absolute variance. Flags rows above materiality with `is_material = true`.

### 5. `recon_aging` — the triage queue

Buckets each unmatched item from `recon_transaction_level` by age (`current_date - business_date`):

| Bucket | Triage priority |
|---|---|
| `0-1d`  | LOW |
| `2-7d`  | MEDIUM |
| `8-30d` | HIGH |
| `30+d`  | CRITICAL |

The HIGH and CRITICAL buckets are what the controller works through every morning.

### 6. `recon_fx_revaluation` — the multi-currency check

For every non-USD GL posting, recomputes the USD value at the period-end FX rate and compares to what's actually in the ledger. Differences represent uncaptured translation gain/loss that should have been booked to account `7900` (FX Revaluation Gain/Loss). Status thresholds:

- `PASS` if `abs(variance) <= $0.05`
- `WARN` if `abs(variance) <= $5.00`
- `FAIL` otherwise

### 7. `recon_suspense_monitor` — the catch-all

The `9999` suspense series should always net to zero — anything sitting in suspense is by definition unmapped and needs a controller to investigate. Even `$1` in suspense is a HIGH-severity exception.

### 8. `recon_manual_je_flag` — the SOX red flag

Manual journal entries posted directly to a control account (`2000` AP, `1200` AR, `1300` Inventory) are an audit risk: those accounts should only be touched by their respective sub-ledger feeds. Every flagged row gets surfaced in the auditor evidence pack and triggers a Slack alert.

### 9. `recon_summary` — the scorecard

Aggregate of `pass / warn / fail` counts and total break value per check. This is what the Streamlit Recon Cockpit reads first, and what gets persisted to `audit.recon_check_results` for the SOX evidence pack.

Sample query:

```sql
SELECT check_name,
       sum(pass_count) AS pass,
       sum(warn_count) AS warn,
       sum(fail_count) AS fail,
       round(sum(breaks_value_usd)::numeric, 2) AS breaks_value_usd
FROM glrecon_marts.recon_summary
GROUP BY check_name
ORDER BY check_name;
```

Live output on the seed dataset:

```
    check_name     | pass  | warn | fail | breaks_value_usd
-------------------+-------+------+------+------------------
 control_account   |     0 |    8 |  268 |      58247962.94
 roll_forward      |  2322 |    0 |    0 |             0.00
 transaction_level | 97955 |    0 | 2479 |        896855.37
```

---

## Reusable macros

Three macros under `dbt_project/macros/` keep the recon SQL DRY:

### `assert_balanced(model, group_by, debit_col, credit_col, tolerance)`

Returns one row per unbalanced group. Used by every singular SQL test that needs to prove a debit/credit invariant — for example, `assert_gl_journal_balanced.sql` proves every `journal_id` nets to zero, and `assert_subledger_postings_balanced.sql` proves every `(source_system, source_doc_id)` projection balances.

### `tolerance_for(account_code_col)` + `coalesce_tolerance(field)`

Two-step macro pair that resolves the per-account tolerance with fallback to the `DEFAULT` row in `tolerance_rules`. Used in `recon_control_account` and `recon_transaction_level`:

```jinja
select ...,
       {{ coalesce_tolerance('amount_tolerance_usd') }} as amount_tolerance_usd,
       ...
from joined j
{{ tolerance_for('j.account_code') }}
```

### `categorize_break(...)`

Maps the structural shape of a break to one of the five named classes. Kept aligned with `data_generator/inject_breaks.py` so the engine's labels match the generator's labels.

---

## Tests

| Layer | What it asserts |
|---|---|
| Source generic tests       | `not_null`, `unique`, `accepted_values`, `relationships` on every column that should not be null and every FK |
| Source freshness           | `gl_journal` warns at 12h stale, errors at 24h |
| Singular SQL tests         | `assert_gl_journal_balanced`, `assert_subledger_postings_balanced`, `assert_no_orphan_breaks` |
| dbt unit tests             | `control_account_passes_when_balances_tie`, `control_account_fails_when_material_break` (synthetic input rows; no Postgres dependency) |
| Model-level tests          | `unique_combination_of_columns` on every mart, `accepted_values` on every status enum |
| `dbt_project_evaluator`    | Lints the dbt project for fanout, missing PK tests, hard-coded refs, etc. (informational warnings) |

Total: **138 dbt tests** + **3 unit tests** + **5 pytest smoke tests on the data generator**.
