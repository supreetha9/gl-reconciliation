"""Asset checks and sensors.

Right now this is intentionally minimal: a single freshness asset check
on ``raw_synthetic_data`` that warns if the bronze layer is older than
30 hours. In a real deployment this would be expanded with sensors for
upstream ERP file arrivals (S3 events, SQS notifications, etc.).
"""

from __future__ import annotations

from datetime import UTC, datetime

from dagster import (
    AssetCheckExecutionContext,
    AssetCheckResult,
    AssetCheckSeverity,
    AssetKey,
    asset_check,
)
from sqlalchemy import text

from .resources import PostgresResource


@asset_check(
    asset=AssetKey(["raw_synthetic_data"]),
    name="raw_gl_journal_freshness",
    description=(
        "Warn if the most recent ingestion into raw.gl_journal is more "
        "than 30 hours old. Mirrors the dbt source freshness check."
    ),
)
def raw_gl_journal_freshness(
    context: AssetCheckExecutionContext,
    postgres: PostgresResource,
) -> AssetCheckResult:
    engine = postgres.get_engine()
    with engine.connect() as conn:
        latest = conn.execute(
            text("SELECT max(ingested_at) FROM raw.gl_journal")
        ).scalar_one_or_none()

    if latest is None:
        return AssetCheckResult(
            passed=False,
            severity=AssetCheckSeverity.ERROR,
            description="raw.gl_journal is empty",
        )

    age_hours = (datetime.now(UTC) - latest).total_seconds() / 3600.0
    passed = age_hours <= 30.0
    severity = (
        AssetCheckSeverity.WARN if age_hours <= 48 else AssetCheckSeverity.ERROR
    )
    return AssetCheckResult(
        passed=passed,
        severity=severity if not passed else AssetCheckSeverity.WARN,
        description=f"raw.gl_journal latest ingested_at is {age_hours:.1f}h old",
        metadata={"age_hours": age_hours, "latest_ingested_at": str(latest)},
    )


ASSET_CHECKS = [raw_gl_journal_freshness]
