# Recon Cockpit

The Recon Cockpit is the controller's daily landing page. A four-page Streamlit app that surfaces the latest reconciliation run, lets the user filter and drill into individual breaks, exposes the aged-break triage queue, and exports the SOX-style auditor evidence pack as a single Excel download.

The app lives at [`streamlit_app/`](https://github.com/supreetha9/gl-reconciliation/tree/main/streamlit_app) and reads directly from the recon marts and the audit trail in Postgres.

---

## Pages

### Home

Lands on the most recent reconciliation run. Shows:

- Headline metrics: business date, status pill, triggered_by, run_id
- Per-check scorecard tiles (top 4) with break count and dollar value
- Full per-check table
- Source row counts snapshot from the audit trail

### Recon Scorecard

Trends across the last 30 runs (or 60 days, whichever is shorter):

- Run history table (audit.recon_runs)
- Per-check break-value line chart over time
- Pass / warn / fail composition stacked bar chart

The line chart is the right view for "how is the recon engine performing over the period" — flat near zero is healthy, sustained climbs above materiality are not.

### Break Detail

The most heavily filtered page. Drives off `recon_transaction_level` with multi-select filters on:

- Source system (AP / AR / INV)
- Status (BREAK / MATCHED)
- Account code
- Break class (TIMING_DIFF / AMOUNT_MISMATCH / MISSING_GL_POSTING / MISSING_SL_POSTING / FX_ROUNDING)
- Minimum absolute USD delta (slider)

Returns the top 1,000 rows by absolute delta. Below the table sits the **drill-through**: pick any `source_doc_id` and the page renders the matching sub-ledger postings (from `int_subledger_postings`) and GL postings (from `stg_gl_journal`) side-by-side. This is the view a controller sends to a vendor or customer when reconciling a disputed invoice.

### Aging Report

The triage queue. Reads `recon_aging` and surfaces:

- Headline metrics by triage priority (LOW / MEDIUM / HIGH / CRITICAL) with break count and value
- A heatmap of break value by `(account_code, age_bucket)` with the reds colour scheme — accounts with persistent unresolved breaks pop visually
- A filtered table of the HIGH + CRITICAL queue ranked by absolute delta

This is what the controller works through every morning starting with the largest CRITICAL items.

### Auditor Evidence

A run picker dropdown listing the last 50 runs from `audit.recon_runs`. Pick a run, optionally adjust the "top N breaks per sheet" slider, click **Build evidence pack**, and the page generates the Excel workbook in-memory and serves it via `st.download_button`.

The button only appears after the workbook is built so the user knows it's ready. Filename format: `GLRecon_Evidence_<business_date>_<run_id_prefix>.xlsx`.

---

## Auditor evidence pack

The Excel workbook is the single artifact an external auditor would request during a quarterly SOX walkthrough. It is fully reproducible from the contents of `audit.*` plus the recon marts on the run date — re-running the export later yields the same file as long as the underlying tables haven't been mutated (and they shouldn't be: `audit.*` is append-only).

### Six sheets

| # | Sheet | Contents |
|---|---|---|
| 1 | **Run Summary**       | One block per audit field: run_id, business_date, status, started/finished_at, git_commit_sha, dbt_manifest_hash, source row counts (table-by-table). |
| 2 | **Check Results**     | One row per check: check_name, status, breaks_count, breaks_value_usd, materiality_usd. Status cells are colour-coded green / yellow / red. |
| 3 | **Control Account**   | Top N control-account-level breaks ranked by absolute variance: entity, account, posting_date, SL balance, GL balance, variance, status. |
| 4 | **Transaction Level** | Top N matching-engine breaks ranked by absolute delta: source, source_doc_id, account, entity, SL amount, GL amount, delta, break_class, status. |
| 5 | **Manual JE Flags**   | All manual journal entries hitting control accounts (the SOX red flags). |
| 6 | **Sign-Off**          | Blank template the controller fills in: Reviewed by / Approved by / Title / Date / Signature. |

`top_n_breaks` defaults to 100 per sheet but the Streamlit slider lets you go up to 500.

### How auditors use it

A typical SOX walkthrough goes:

1. Auditor: "Show me the recon for May 14th."
2. Controller: opens the Recon Cockpit → Auditor Evidence page → picks the run → downloads the pack → forwards the .xlsx.
3. Auditor: opens the workbook, reads Sheet 1 to confirm the control was performed, scans Sheets 2-5 for material breaks, checks Sheet 6 for the controller's sign-off.

The pack is **the** control evidence. Not the dashboards, not the dbt logs — the workbook.

### Building it programmatically

The Streamlit page is just a thin wrapper over [`recon_engine.evidence.build_evidence_pack`](https://github.com/supreetha9/gl-reconciliation/blob/main/recon_engine/evidence.py). You can call it directly from a Python script or notebook:

```python
from recon_engine.evidence import build_evidence_pack, evidence_filename
import uuid
from sqlalchemy import create_engine

engine = create_engine("postgresql+psycopg://glrecon:glrecon@localhost:5432/glrecon")
data = build_evidence_pack(engine, run_id=uuid.UUID("..."), top_n_breaks=200)

with open(evidence_filename(date(2026, 5, 14), run_id), "wb") as fh:
    fh.write(data)
```

This is what an automated nightly job would do to push the pack to S3 / SharePoint / wherever the audit team archives evidence.

---

## Caching strategy

Every cross-page query is wrapped in `@st.cache_data(ttl=60)` so a controller flipping between pages doesn't hammer the database. The SQLAlchemy engine itself is wrapped in `@st.cache_resource` so pool reuse works correctly across reruns.

Cache TTL is intentionally short (60 seconds) — recon runs can land while the cockpit is open, and a controller would expect a refresh to show the new run within a minute.

---

## Running locally

```bash
make streamlit    # starts the app on http://localhost:8501
```

Both Postgres and a recent recon run (via `make recon-run` or the Dagster UI) need to exist for the pages to populate. If you open the Home page and see "No recon runs found yet", that's the fix.

---

## Production considerations

The current setup is built for local development. For a production deployment:

- **Hosting**: [Streamlit Community Cloud](https://streamlit.io/cloud) is the simplest path. For heavier control, deploy as a Docker container behind a reverse proxy.
- **Auth**: the cockpit currently has no auth layer — anyone reaching the URL can see breaks and download evidence. Wrap the deployment in OAuth (Auth0, Okta) or put it behind your VPN.
- **Read-only DB user**: in production, give the Streamlit app a Postgres role with `SELECT` on `glrecon_marts.*` and `audit.*` only. The cockpit never needs to write.
- **Caching**: the 60-second TTL is fine for a single user. For a busy team, switch to Redis-backed caching via `st.connection`.
- **Evidence retention**: the in-memory build is ephemeral. Production should write each generated pack to S3 (or similar) and store the URL in `audit.recon_runs.evidence_url`.

---

## Where to extend

| Goal | What to change |
|---|---|
| Add a new page                                | Drop a `pages/N_<Title>.py` file under `streamlit_app/pages/`. Streamlit picks it up on next reload. |
| Add a new chart on an existing page           | Either build it inline with Altair, or extract into `lib/charts.py` for reuse. |
| Add a new sheet to the evidence pack          | Add a `_build_<name>_sheet()` helper in `recon_engine/evidence.py` and wire it into `build_evidence_pack()`. |
| Switch from xlsx to PDF for the evidence pack | Add a [`reportlab`](https://www.reportlab.com/dev/) variant of `build_evidence_pack()` and let the Streamlit page offer both download buttons. |
