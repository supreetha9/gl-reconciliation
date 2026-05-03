"""Unit + integration tests for ``recon_engine.audit``.

The integration tests require a live Postgres on the project DSN; they
are skipped if the connection fails so the suite still passes on a
laptop that hasn't run ``make up``.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

from recon_engine.audit import (
    AuditTrailWriter,
    CheckResult,
    _derive_overall_status,
)

# ---------------------------------------------------------------------------
# Pure unit tests (no DB)
# ---------------------------------------------------------------------------

def test_derive_overall_status_fail_wins():
    checks = [
        CheckResult("a", "PASS"),
        CheckResult("b", "WARN"),
        CheckResult("c", "FAIL"),
    ]
    assert _derive_overall_status(checks) == "FAIL"


def test_derive_overall_status_warn_when_no_fail():
    checks = [CheckResult("a", "PASS"), CheckResult("b", "WARN")]
    assert _derive_overall_status(checks) == "WARN"


def test_derive_overall_status_pass_when_all_pass():
    checks = [CheckResult("a", "PASS"), CheckResult("b", "PASS")]
    assert _derive_overall_status(checks) == "PASS"


def test_run_summary_aggregates():
    from datetime import datetime

    from recon_engine.audit import RunSummary

    s = RunSummary(
        run_id=uuid.uuid4(),
        business_date=date(2026, 5, 3),
        triggered_by="manual:test",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        status="WARN",
        checks=[
            CheckResult("a", "FAIL", breaks_value_usd=Decimal("100")),
            CheckResult("b", "WARN", breaks_value_usd=Decimal("50")),
            CheckResult("c", "PASS"),
        ],
    )
    assert s.fail_count == 1
    assert s.warn_count == 1
    assert s.total_breaks_value_usd == Decimal("150")


# ---------------------------------------------------------------------------
# Integration tests (require local Postgres)
# ---------------------------------------------------------------------------

def _live_engine():
    user = os.environ.get("POSTGRES_USER", "glrecon")
    password = os.environ.get("POSTGRES_PASSWORD", "glrecon")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "glrecon")
    dsn = f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"
    eng = create_engine(dsn, future=True)
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Postgres not reachable ({exc.__class__.__name__})")
    return eng


@pytest.fixture
def engine():
    return _live_engine()


def test_start_and_finalize_round_trip(engine):
    writer = AuditTrailWriter(engine)
    business_date = date(2026, 5, 3)
    run_id = writer.start_run(business_date=business_date, triggered_by="manual:test")

    # Verify the RUNNING row landed.
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, business_date FROM audit.recon_runs WHERE run_id = :r"),
            {"r": run_id},
        ).one()
    assert row.status == "RUNNING"
    assert row.business_date == business_date

    # Finalize.
    checks = [
        CheckResult("control_account", "FAIL", breaks_count=12, breaks_value_usd=Decimal("123.45")),
        CheckResult("transaction_level", "WARN", breaks_count=3,  breaks_value_usd=Decimal("9.99")),
        CheckResult("roll_forward",      "PASS"),
    ]
    summary = writer.finalize(
        run_id=run_id,
        checks=checks,
        source_row_counts={"raw.gl_journal": 100050},
        dbt_manifest_hash="abc123",
    )

    assert summary.status == "FAIL"
    assert summary.total_breaks_value_usd == Decimal("133.44")
    assert summary.fail_count == 1
    assert summary.warn_count == 1

    # Verify rows landed.
    with engine.connect() as conn:
        run_row = conn.execute(
            text("""
                SELECT status, finished_at, dbt_manifest_hash, source_row_counts
                FROM audit.recon_runs WHERE run_id = :r
            """),
            {"r": run_id},
        ).one()
        assert run_row.status == "FAIL"
        assert run_row.finished_at is not None
        assert run_row.dbt_manifest_hash == "abc123"
        assert run_row.source_row_counts["raw.gl_journal"] == 100050

        check_rows = conn.execute(
            text("SELECT check_name, status FROM audit.recon_check_results WHERE run_id = :r"),
            {"r": run_id},
        ).fetchall()
        names = {r.check_name: r.status for r in check_rows}
    assert names == {
        "control_account": "FAIL",
        "transaction_level": "WARN",
        "roll_forward": "PASS",
    }


def test_finalize_is_idempotent_per_check(engine):
    """Re-running finalize() with the same run_id should overwrite the check rows, not duplicate."""
    writer = AuditTrailWriter(engine)
    run_id = writer.start_run(business_date=date(2026, 5, 3), triggered_by="manual:test")

    writer.finalize(
        run_id=run_id,
        checks=[CheckResult("X", "WARN", breaks_count=5, breaks_value_usd=Decimal("50"))],
    )
    # Second call mutates the same row; status should change.
    writer.finalize(
        run_id=run_id,
        checks=[CheckResult("X", "FAIL", breaks_count=10, breaks_value_usd=Decimal("100"))],
    )

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT status, breaks_count FROM audit.recon_check_results WHERE run_id = :r AND check_name = 'X'"),
            {"r": run_id},
        ).all()
    assert len(rows) == 1
    assert rows[0].status == "FAIL"
    assert rows[0].breaks_count == 10


def test_mark_error_stamps_status(engine):
    writer = AuditTrailWriter(engine)
    run_id = writer.start_run(business_date=date(2026, 5, 3), triggered_by="manual:test")
    writer.mark_error(run_id, "boom: something exploded")

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, source_row_counts FROM audit.recon_runs WHERE run_id = :r"),
            {"r": run_id},
        ).one()
    assert row.status == "ERROR"
    assert "_error" in row.source_row_counts
    assert "boom" in row.source_row_counts["_error"]
