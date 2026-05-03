# Data Model

The reconciliation system models a small but realistic finance data warehouse: a multi-entity, multi-currency General Ledger fed by three sub-ledgers (AP, AR, Inventory). This page is the canonical reference for every table and the conventions that bind them together.

---

## Conventions

A few rules apply across the entire schema:

- **All amounts are stored in both transaction currency and USD.** USD is the reporting currency. The pre-computed `*_usd` columns are what the recon engine uses; `amount_currency` and `fx_rate` are kept for traceability.
- **Two date columns:** `business_date` is the *accounting* date (the period the transaction belongs to). `posting_date` is the *operational* date (when the row actually hit the system). They normally match; when they do not, the difference is a timing break.
- **Source-system attribution:** every GL line carries a `source_system` (`AP`, `AR`, `INV`, `MANUAL`, or `FX_REVAL`) and a `source_doc_id` pointing back to the originating sub-ledger row. This is what enables transaction-level matching.
- **Append-only audit tables.** `audit.recon_runs` and `audit.recon_check_results` are never updated — a re-run is a new row.

---

## Schemas at a glance

| Schema | Layer | Owner | Purpose |
|---|---|---|---|
| `raw`                  | Bronze   | Loader         | Untouched landings from source systems. |
| `glrecon_staging`      | Silver   | dbt            | Cleaned, conformed `stg_` views. |
| `glrecon_intermediate` | Silver   | dbt            | Joined / enriched `int_` views (trial balances, hierarchies). |
| `glrecon_marts`        | Gold     | dbt            | Recon marts consumed by the cockpit and the auditor. |
| `glrecon_seeds`        | Config   | dbt            | Tolerance and materiality CSV-as-code. |
| `snapshots`            | History  | dbt            | SCD2 history (currently chart of accounts). |
| `audit`                | Evidence | Pipeline       | Immutable run log + per-check results. |

---

## Reference data

### `raw.dim_entity`

Legal entities. One row per ledger-bearing entity.

| Column | Type | Notes |
|---|---|---|
| `entity_id`           | integer    | PK   |
| `entity_code`         | text       | UK (e.g., `US01`, `EU01`, `IN01`)   |
| `entity_name`         | text       |   |
| `functional_currency` | char(3)    | One of `USD`, `EUR`, `INR`   |
| `country`             | text       |   |
| `ingested_at`         | timestamptz |   |

### `raw.dim_account`

The chart of accounts. Single source of truth for account metadata, hierarchy, and control-account flags.

| Column | Type | Notes |
|---|---|---|
| `account_id`           | integer    | PK   |
| `account_code`         | text       | UK (e.g., `2000` for AP control)   |
| `account_name`         | text       |   |
| `account_type`         | text       | One of `ASSET`, `LIABILITY`, `EQUITY`, `REVENUE`, `EXPENSE`   |
| `parent_account_code`  | text       | Self-reference for the hierarchy   |
| `is_control_account`   | boolean    | True for `2000` (AP), `1200` (AR), `1300` (Inventory)   |
| `subledger_source`     | text       | `AP`, `AR`, `INV`, or NULL   |
| `effective_from`       | date       | For SCD2 reconstruction   |
| `effective_to`         | date       | NULL for current rows   |

The hierarchy is walked by `int_dim_account_hierarchy` using a recursive CTE.

### `raw.fx_rate`

Daily FX rates to USD. Used by `recon_fx_revaluation`.

| Column | Type | Notes |
|---|---|---|
| `rate_date`     | date         | PK part   |
| `from_currency` | char(3)      | PK part   |
| `to_currency`   | char(3)      | PK part (always `USD` in this project)   |
| `rate`          | numeric(18,8) | 1 unit of `from_currency` = `rate` USD   |

---

## Accounts Payable

### `raw.ap_invoices`

Vendor invoices. Posts `Dr expense, Cr 2000 (AP control)` to the GL.

| Column | Type | Notes |
|---|---|---|
| `invoice_id`           | text         | PK (e.g., `AP-INV-0000123`)   |
| `vendor_id`            | text         |   |
| `entity_id`            | integer      | FK → `raw.dim_entity`   |
| `invoice_date`         | date         | Becomes the GL `business_date`   |
| `posting_date`         | date         | Becomes the GL `posting_date` (perturbed by timing breaks)   |
| `due_date`             | date         |   |
| `currency`             | char(3)      |   |
| `amount_currency`      | numeric(18,2) |   |
| `amount_usd`           | numeric(18,2) | Reporting currency   |
| `fx_rate`              | numeric(18,8) | Captured at invoice date for traceability   |
| `expense_account_code` | text         | Where the debit lands   |
| `control_account_code` | text         | Always `2000`   |
| `status`               | text         | `OPEN`, `PAID`, `VOID`, `HOLD`   |

### `raw.ap_payments`

Payments against vendor invoices. Posts `Dr 2000, Cr 1000 (Cash)`.

| Column | Type | Notes |
|---|---|---|
| `payment_id`        | text          | PK   |
| `invoice_id`        | text          | FK → `raw.ap_invoices` (nullable for payments-on-account)   |
| `entity_id`         | integer       | FK → `raw.dim_entity`   |
| `payment_date`      | date          |   |
| `posting_date`      | date          |   |
| `amount_usd`        | numeric(18,2) |   |
| `cash_account_code` | text          | Always `1000`   |
| `control_account_code` | text       | Always `2000`   |
| `method`            | text          | `ACH`, `WIRE`, `CHECK`, `CARD`   |

### `raw.ap_accruals`

Month-end accruals; reverse on the configured `reversal_date`.

| Column | Type | Notes |
|---|---|---|
| `accrual_id`        | text         | PK   |
| `accrual_date`      | date         |   |
| `reversal_date`     | date         |   |
| `amount_usd`        | numeric(18,2) |   |

---

## Accounts Receivable

### `raw.ar_invoices`

Customer invoices. Posts `Dr 1200 (AR control), Cr revenue`.

Mirror of `ap_invoices` with the directional flip and a `revenue_account_code` instead of an expense account.

### `raw.ar_receipts`

Cash receipts against AR invoices. Posts `Dr 1000, Cr 1200`.

Mirror of `ap_payments` with the directional flip.

### `raw.ar_credit_memos`

Returns, price adjustments, and write-offs.

| Column | Type | Notes |
|---|---|---|
| `memo_id`         | text          | PK   |
| `invoice_id`      | text          | FK → `raw.ar_invoices`   |
| `reason`          | text          | `RETURN`, `PRICE_ADJ`, `WRITE_OFF`   |
| `amount_usd`      | numeric(18,2) |   |

---

## Inventory

### `raw.inv_transactions`

Inventory receipts, COGS postings, and adjustments. The `txn_type` and the sign of `amount_usd` together determine the posting direction:

| `txn_type` | sign | Posting |
|---|---|---|
| `RECEIPT`     | always positive | Dr `1300` (Inventory), Cr `2000` (AP — GR/IR) |
| `COGS`        | always positive | Dr `5000` (COGS), Cr `1300` (Inventory) |
| `ADJUSTMENT`  | positive        | Dr `1300`, Cr `6900` (Other Op Ex) |
| `ADJUSTMENT`  | negative        | Dr `6900`, Cr `1300` |

| Column | Type | Notes |
|---|---|---|
| `txn_id`                  | text         | PK   |
| `item_id`                 | text         | SKU   |
| `txn_type`                | text         | `RECEIPT`, `COGS`, `ADJUSTMENT`   |
| `quantity`                | numeric(18,4) | Signed for ADJUSTMENT   |
| `unit_cost_usd`           | numeric(18,4) |   |
| `amount_usd`              | numeric(18,2) | `quantity * unit_cost_usd`, signed   |
| `inventory_account_code`  | text         | Debit account in the happy path   |
| `offset_account_code`     | text         | Credit account in the happy path   |

---

## General Ledger

### `raw.gl_journal`

The General Ledger. **One row per journal LINE.** A journal entry is the set of lines sharing a `journal_id`; the lines must always sum to zero in USD (debits = credits). This invariant is enforced by `assert_gl_journal_balanced.sql` and is the most fundamental ledger check.

| Column | Type | Notes |
|---|---|---|
| `journal_id`        | text         | PK part   |
| `journal_line_id`   | integer      | PK part   |
| `entity_id`         | integer      | FK → `raw.dim_entity`   |
| `business_date`     | date         | Accounting period date   |
| `posting_date`      | date         | Operational date (perturbed by timing breaks)   |
| `account_code`      | text         |   |
| `debit_usd`         | numeric(18,2) | A line is debit OR credit, not both   |
| `credit_usd`        | numeric(18,2) |   |
| `currency`          | char(3)      |   |
| `amount_currency`   | numeric(18,2) |   |
| `fx_rate`           | numeric(18,8) |   |
| `source_system`     | text         | `AP`, `AR`, `INV`, `MANUAL`, `FX_REVAL`   |
| `source_doc_id`     | text         | FK back to the originating sub-ledger row   |
| `description`       | text         |   |
| `created_by`        | text         |   |

Indexes: `(business_date, entity_id, account_code)`, `(posting_date, entity_id)`, `(source_system, source_doc_id)`.

---

## Audit

### `audit.recon_runs`

Append-only run log. Every `dbt build` (or future Dagster execution) inserts exactly one row.

| Column | Type | Notes |
|---|---|---|
| `run_id`            | uuid        | PK   |
| `business_date`     | date        | The accounting date the run covers   |
| `triggered_by`      | text        | `'schedule'`, `'manual:<user>'`, `'backfill'`   |
| `started_at`        | timestamptz |   |
| `finished_at`       | timestamptz |   |
| `status`            | text        | `RUNNING`, `PASS`, `FAIL`, `WARN`, `ERROR`   |
| `git_commit_sha`    | text        | Provenance for the SOX evidence pack   |
| `dbt_manifest_hash` | text        | Identifies the exact dbt project state   |
| `source_row_counts` | jsonb       | Keyed by `raw.<table>` → integer count   |
| `evidence_url`      | text        | Pointer to the exported PDF/Excel pack   |

### `audit.recon_check_results`

Per-check outcome for each run. Drives the Streamlit scorecard and is what the auditor reads first.

| Column | Type | Notes |
|---|---|---|
| `run_id`           | uuid          | FK → `audit.recon_runs`   |
| `check_name`       | text          | One of the 9 mart names   |
| `status`           | text          | `PASS`, `FAIL`, `WARN`   |
| `breaks_count`     | integer       |   |
| `breaks_value_usd` | numeric(18,2) |   |
| `materiality_usd`  | numeric(18,2) |   |
| `details`          | jsonb         | Free-form per-check payload   |
