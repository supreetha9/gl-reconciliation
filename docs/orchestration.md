# Orchestration

The reconciliation pipeline runs every business morning. The orchestrator is responsible for kicking off the data load, running the dbt build, recording the run in the SOX-style audit trail, and firing a Slack alert if any check breached its materiality threshold.

This project uses [Dagster](https://docs.dagster.io/) for orchestration, but every piece of the orchestration layer is decoupled from Dagster: the audit-trail writer and the Slack alerter live in [`recon_engine/`](https://github.com/supreetha9/gl-reconciliation/tree/main/recon_engine) as plain Python and can be invoked from a cron job, GitHub Actions, or any other scheduler.

---

## Asset graph

```{mermaid}
flowchart LR
  raw[raw_synthetic_data] --> stg[stg_*]
  stg --> int[int_*]
  int --> marts[recon_*]
  marts --> summary[recon_summary]
  summary --> audit[audit_recon_run]
  audit --> slack[Slack alert]
  audit --> evidence[audit.recon_runs<br/>+ audit.recon_check_results]
```

Three asset groups, all wired together via [Dagster's software-defined-asset model](https://docs.dagster.io/concepts/assets/software-defined-assets):

### 1. `raw_synthetic_data`

Group: `ingestion`. A single Python asset that wraps the synthetic data pipeline (`data_generator.cli seed`) and writes ~50K rows into the `raw.*` tables. In a production deployment this asset would be replaced by the real ERP feed (Fivetran, Airbyte, S3 events) — nothing downstream needs to change.

### 2. `glrecon_dbt_assets`

Group: `dbt`. **One Dagster asset per dbt model**, auto-generated from the dbt manifest via [`@dbt_assets`](https://docs.dagster.io/integrations/dbt/reference). Lineage flows from sources → staging → intermediate → marts in the asset graph exactly as it does in `dbt docs`.

### 3. `audit_recon_run`

Group: `audit`. Terminal asset. Reads the recon mart `recon_summary`, writes one row to [`audit.recon_runs`](data_model.md#audit) and one per check to `audit.recon_check_results`, then fires a Slack alert.

---

## Daily schedule

The schedule fires every weekday at 08:00 PT — early enough that controllers see a fresh recon scorecard when they log in, late enough that the source ERPs have published their nightly extracts.

```python
ScheduleDefinition(
    name="daily_recon_schedule",
    job=daily_recon_job,
    cron_schedule="0 8 * * 1-5",
    execution_timezone="America/Los_Angeles",
    default_status=DefaultScheduleStatus.STOPPED,  # off in dev
)
```

It defaults to `STOPPED` so local development doesn't spam runs. Flip to `RUNNING` in the Dagster UI when deploying.

---

## Asset checks

A single asset check (`raw_gl_journal_freshness`) on `raw_synthetic_data` warns if the most recent ingest into `raw.gl_journal` is more than 30 hours old; errors above 48 hours. This mirrors the dbt source freshness declaration on `gl_journal` and gives the orchestrator the same visibility through Dagster's UI.

---

## Resources

Three [`ConfigurableResource`s](https://docs.dagster.io/concepts/resources) live in [`dagster_pipeline/resources.py`](https://github.com/supreetha9/gl-reconciliation/blob/main/dagster_pipeline/resources.py):

| Resource | Backed by | Purpose |
|---|---|---|
| `PostgresResource` | SQLAlchemy `Engine` | Read recon marts, write audit trail. |
| `DbtCliResource`   | `dagster-dbt`'s `DbtProject` | Runs `dbt build --no-version-check`. |
| `SlackResource`    | [`SlackAlerter`](#slack-alerts) | Posts the Block Kit payload. |

All three read configuration from environment variables via `EnvVar` so the same code runs locally, in CI, and in production.

---

## Audit trail

Every reconciliation run, no matter how it's triggered (Dagster schedule, manual CLI, backfill), produces exactly two audit artifacts:

### `audit.recon_runs` (one row per run)

Captures the high-level run metadata that an external auditor would request during a SOX walkthrough:

- `run_id` (UUID, primary key)
- `business_date` — the accounting date the run covers
- `triggered_by` — `'schedule'`, `'manual:<user>'`, `'backfill'`
- `started_at`, `finished_at`
- `status` — one of `RUNNING`, `PASS`, `WARN`, `FAIL`, `ERROR`
- `git_commit_sha` — the project state at run time
- `dbt_manifest_hash` — the exact dbt project state
- `source_row_counts` (JSONB) — keyed by `raw.<table>` → integer count
- `evidence_url` — pointer to the exported PDF / Excel pack

### `audit.recon_check_results` (one row per (run, check))

The per-check outcome that drives the Streamlit scorecard and the auditor evidence pack:

- `run_id`, `check_name`
- `status` (`PASS` / `WARN` / `FAIL`)
- `breaks_count`, `breaks_value_usd`
- `materiality_usd` — the threshold that was applied
- `details` (JSONB) — free-form payload with the underlying counts

### Lifecycle

```python
writer = AuditTrailWriter(engine)
run_id = writer.start_run(business_date, triggered_by="schedule")

try:
    # ...orchestrator runs the data generator + dbt build...
    summary = writer.finalize(
        run_id=run_id,
        checks=load_check_results_from_marts(engine),
        source_row_counts=load_source_row_counts(engine, schema="raw"),
        dbt_manifest_hash=read_dbt_manifest_hash("dbt_project"),
    )
except Exception as exc:
    writer.mark_error(run_id, str(exc))
    raise
```

Both tables are **append-only**. A re-run is a new row, not an update — exactly what auditors expect.

---

## Slack alerts

Slack alerting is a single `requests.post` to an [incoming webhook](https://api.slack.com/messaging/webhooks) — no SDK, no Block Kit gymnastics beyond a clean `mrkdwn` block. The alerter is a **no-op when `SLACK_WEBHOOK_URL` is unset**, so the pipeline never depends on Slack being reachable.

The message separates checks above the materiality threshold (listed in the body) from those below (collapsed into a footer line) so the message stays scannable in a busy `#finance-ops` channel.

```text
:rotating_light:  *Daily GL Reconciliation — 2026-05-03*  →  *FAIL*

*Material breaks (above threshold):*
  • `control_account` — 268 breaks, $58,247,962.94 (FAIL)
  • `transaction_level` — 2,479 breaks, $896,855.37 (FAIL)

_(1 check below the $10,000 threshold; see the Recon Cockpit for detail.)_
```

The materiality threshold defaults to `$10,000` and is configurable via `MATERIALITY_THRESHOLD_USD`. See [Configuration](reference/configuration.md) for the full env var reference.

---

## Manual CLI alternative

For environments where Dagster isn't installed (CI smoke tests, cron, ad-hoc backfills), [`recon_engine.cli`](reference/cli.md#recon-engine) provides the same end-to-end recon pipeline as a plain Typer command:

```bash
python -m recon_engine.cli run-recon
python -m recon_engine.cli list-runs --limit 10
python -m recon_engine.cli show-run <run_id>
```

The CLI uses the same `AuditTrailWriter` and `SlackAlerter` classes as the Dagster assets — it's just a thinner wrapper. A run launched from the CLI is indistinguishable in `audit.recon_runs` from one launched by the schedule, except for the `triggered_by` value.

---

## Running locally

```bash
make dagster      # starts the Dagster UI on http://localhost:3000
```

The UI gives you the asset graph, manual materialisation buttons, the daily schedule (off by default), and the run history. To trigger a one-shot run without the UI:

```bash
make recon-run    # `python -m recon_engine.cli run-recon`
make recon-list   # last 10 entries from audit.recon_runs
```

---

## Where to extend

| Goal | What to change |
|---|---|
| Add a new sensor (e.g. S3-event-driven runs) | New file under `dagster_pipeline/sensors.py`, register in `definitions.py`. |
| Add a new asset check                        | Add to `dagster_pipeline/sensors.py` with `@asset_check`. |
| Swap the DB to Snowflake                     | Replace `PostgresResource` with `SnowflakeResource`; the `AuditTrailWriter` stays unchanged because it uses SQLAlchemy. |
| Replace Slack with PagerDuty                 | Swap the body of `recon_engine.alerts.SlackAlerter.alert()` — keep the `CheckOutcome` interface stable. |
