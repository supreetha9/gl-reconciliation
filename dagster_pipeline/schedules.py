"""Daily reconciliation schedule.

Runs the full pipeline (raw load → dbt build → audit + Slack) every
business morning at 08:00 America/Los_Angeles. Real teams typically
schedule this to fire just after the source ERPs publish their nightly
extracts, so the controller has a fresh recon scorecard waiting when
they log in.
"""

from __future__ import annotations

from dagster import (
    AssetSelection,
    DefaultScheduleStatus,
    ScheduleDefinition,
    define_asset_job,
)

# The job that materialises the full asset graph in dependency order:
#   raw_synthetic_data → dbt assets → audit_recon_run
daily_recon_job = define_asset_job(
    name="daily_recon_job",
    description="Full daily recon: raw load + dbt build + audit + Slack alert.",
    selection=AssetSelection.all(),
)


daily_recon_schedule = ScheduleDefinition(
    name="daily_recon_schedule",
    job=daily_recon_job,
    cron_schedule="0 8 * * 1-5",      # 08:00 every weekday
    execution_timezone="America/Los_Angeles",
    default_status=DefaultScheduleStatus.STOPPED,  # off in dev; flip to RUNNING in prod
)


SCHEDULES = [daily_recon_schedule]
JOBS = [daily_recon_job]
