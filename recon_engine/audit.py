"""SOX-style audit trail writer.

Emits one row per reconciliation run to ``audit.recon_runs`` and one row
per dbt-built recon mart to ``audit.recon_check_results``. The pattern
is `start_run() -> ... pipeline runs ... -> finalize()` so we capture
the in-flight `RUNNING` state and only stamp `finished_at` and the
overall status once the dbt build has produced the marts.

Designed to be DB-agnostic via SQLAlchemy. The expected schema is
defined in ``db/init/05_audit.sql``.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import Engine, text

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """Per-check outcome written to ``audit.recon_check_results``."""

    check_name: str
    status: str  # PASS | WARN | FAIL
    breaks_count: int = 0
    breaks_value_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    materiality_usd: Decimal | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunSummary:
    """The complete picture of one reconciliation run.

    Returned by ``AuditTrailWriter.finalize()`` so callers (the Slack
    alerter, the evidence-pack exporter) can use it without re-querying
    the database.
    """

    run_id: uuid.UUID
    business_date: date
    triggered_by: str
    started_at: datetime
    finished_at: datetime
    status: str
    checks: list[CheckResult]
    git_commit_sha: str | None = None
    dbt_manifest_hash: str | None = None
    source_row_counts: dict[str, int] = field(default_factory=dict)
    evidence_url: str | None = None

    @property
    def total_breaks_value_usd(self) -> Decimal:
        return sum(
            (c.breaks_value_usd for c in self.checks),
            Decimal("0"),
        )

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "FAIL")

    @property
    def warn_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "WARN")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git_commit_sha() -> str | None:
    """Best-effort capture of the current git HEAD SHA. Returns None outside a repo."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _derive_overall_status(checks: list[CheckResult]) -> str:
    """Roll up per-check status into a single run-level status."""
    if any(c.status == "FAIL" for c in checks):
        return "FAIL"
    if any(c.status == "WARN" for c in checks):
        return "WARN"
    return "PASS"


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

class AuditTrailWriter:
    """Append-only writer for ``audit.recon_runs`` + ``audit.recon_check_results``.

    Lifecycle:
        writer = AuditTrailWriter(engine)
        run_id = writer.start_run(business_date, triggered_by="schedule")
        # ... orchestrator runs the data generator + dbt ...
        summary = writer.finalize(
            run_id=run_id,
            checks=[CheckResult(...)],
            source_row_counts={...},
            dbt_manifest_hash="...",
        )
        # `summary` is what the Slack alerter consumes.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # ----- start ----------------------------------------------------------
    def start_run(
        self,
        business_date: date,
        triggered_by: str,
        run_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        run_id = run_id or uuid.uuid4()
        started_at = _utcnow()
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO audit.recon_runs
                        (run_id, business_date, triggered_by, started_at,
                         status, git_commit_sha)
                    VALUES (:run_id, :business_date, :triggered_by, :started_at,
                            'RUNNING', :git_sha)
                """),
                {
                    "run_id": run_id,
                    "business_date": business_date,
                    "triggered_by": triggered_by,
                    "started_at": started_at,
                    "git_sha": _git_commit_sha(),
                },
            )
        log.info(
            "audit.run.started",
            run_id=str(run_id),
            business_date=str(business_date),
            triggered_by=triggered_by,
        )
        return run_id

    # ----- finalize -------------------------------------------------------
    def finalize(
        self,
        run_id: uuid.UUID,
        checks: list[CheckResult],
        source_row_counts: dict[str, int] | None = None,
        dbt_manifest_hash: str | None = None,
        evidence_url: str | None = None,
        overall_status: str | None = None,
    ) -> RunSummary:
        finished_at = _utcnow()
        status = overall_status or _derive_overall_status(checks)

        with self.engine.begin() as conn:
            # Per-check results (idempotent on (run_id, check_name)).
            for c in checks:
                conn.execute(
                    text("""
                        INSERT INTO audit.recon_check_results
                            (run_id, check_name, status, breaks_count,
                             breaks_value_usd, materiality_usd, details)
                        VALUES (:run_id, :check_name, :status, :breaks_count,
                                :breaks_value_usd, :materiality_usd,
                                CAST(:details AS jsonb))
                        ON CONFLICT (run_id, check_name) DO UPDATE SET
                            status            = EXCLUDED.status,
                            breaks_count      = EXCLUDED.breaks_count,
                            breaks_value_usd  = EXCLUDED.breaks_value_usd,
                            materiality_usd   = EXCLUDED.materiality_usd,
                            details           = EXCLUDED.details
                    """),
                    {
                        "run_id": run_id,
                        "check_name": c.check_name,
                        "status": c.status,
                        "breaks_count": c.breaks_count,
                        "breaks_value_usd": c.breaks_value_usd,
                        "materiality_usd": c.materiality_usd,
                        "details": json.dumps(c.details, default=str),
                    },
                )

            # Update the parent run row with the final state.
            conn.execute(
                text("""
                    UPDATE audit.recon_runs
                       SET finished_at        = :finished_at,
                           status             = :status,
                           dbt_manifest_hash  = :dbt_manifest_hash,
                           source_row_counts  = CAST(:source_row_counts AS jsonb),
                           evidence_url       = :evidence_url
                     WHERE run_id = :run_id
                """),
                {
                    "run_id": run_id,
                    "finished_at": finished_at,
                    "status": status,
                    "dbt_manifest_hash": dbt_manifest_hash,
                    "source_row_counts": json.dumps(source_row_counts or {}),
                    "evidence_url": evidence_url,
                },
            )

            # Read the canonical started_at + business_date back so the
            # returned summary matches what's persisted.
            row = conn.execute(
                text("""
                    SELECT business_date, triggered_by, started_at
                    FROM audit.recon_runs WHERE run_id = :run_id
                """),
                {"run_id": run_id},
            ).one()

        log.info(
            "audit.run.finalized",
            run_id=str(run_id),
            status=status,
            checks=len(checks),
            fail_count=sum(1 for c in checks if c.status == "FAIL"),
        )

        return RunSummary(
            run_id=run_id,
            business_date=row.business_date,
            triggered_by=row.triggered_by,
            started_at=row.started_at,
            finished_at=finished_at,
            status=status,
            checks=checks,
            git_commit_sha=_git_commit_sha(),
            dbt_manifest_hash=dbt_manifest_hash,
            source_row_counts=source_row_counts or {},
            evidence_url=evidence_url,
        )

    # ----- mark error -----------------------------------------------------
    def mark_error(self, run_id: uuid.UUID, error_message: str) -> None:
        """Stamp a run as ERROR if the orchestrator catches an exception."""
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE audit.recon_runs
                       SET finished_at = :finished_at,
                           status      = 'ERROR',
                           source_row_counts = COALESCE(source_row_counts, '{}'::jsonb)
                                              || CAST(:error AS jsonb)
                     WHERE run_id = :run_id
                """),
                {
                    "run_id": run_id,
                    "finished_at": _utcnow(),
                    "error": json.dumps({"_error": error_message[:500]}),
                },
            )
        log.error("audit.run.errored", run_id=str(run_id), error=error_message[:500])


# ---------------------------------------------------------------------------
# Mart loader -- queries glrecon_marts.recon_summary into CheckResult objects
# ---------------------------------------------------------------------------

def load_check_results_from_marts(
    engine: Engine,
    schema: str = "glrecon_marts",
) -> list[CheckResult]:
    """Read the recon_summary mart and convert each row into a CheckResult.

    The mart already aggregates pass/warn/fail counts and total break value
    per check; we re-derive an overall PASS/WARN/FAIL status from those.
    """
    sql = text(f"""
        SELECT check_name,
               COALESCE(sum(pass_count), 0) AS pass_count,
               COALESCE(sum(warn_count), 0) AS warn_count,
               COALESCE(sum(fail_count), 0) AS fail_count,
               COALESCE(sum(breaks_value_usd), 0)::numeric AS breaks_value_usd
        FROM {schema}.recon_summary
        GROUP BY check_name
        ORDER BY check_name
    """)
    out: list[CheckResult] = []
    with engine.connect() as conn:
        for row in conn.execute(sql):
            if row.fail_count > 0:
                status = "FAIL"
            elif row.warn_count > 0:
                status = "WARN"
            else:
                status = "PASS"
            out.append(
                CheckResult(
                    check_name=row.check_name,
                    status=status,
                    breaks_count=int(row.fail_count + row.warn_count),
                    breaks_value_usd=Decimal(str(row.breaks_value_usd)),
                    details={
                        "pass_count": int(row.pass_count),
                        "warn_count": int(row.warn_count),
                        "fail_count": int(row.fail_count),
                    },
                )
            )
    return out


def load_source_row_counts(engine: Engine, schema: str = "raw") -> dict[str, int]:
    """Snapshot row counts in the `raw` schema for the audit row's JSON column."""
    sql = text("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = :schema ORDER BY table_name
    """)
    out: dict[str, int] = {}
    with engine.connect() as conn:
        rows = conn.execute(sql, {"schema": schema}).fetchall()
        for (t,) in rows:
            n = conn.execute(text(f'SELECT count(*) FROM "{schema}"."{t}"')).scalar_one()
            out[f"{schema}.{t}"] = int(n)
    return out


def read_dbt_manifest_hash(dbt_project_dir: str | os.PathLike) -> str | None:
    """Hash of the compiled dbt manifest. Identifies the exact project state."""
    import hashlib
    from pathlib import Path

    manifest_path = Path(dbt_project_dir) / "target" / "manifest.json"
    if not manifest_path.exists():
        return None
    h = hashlib.sha256()
    with manifest_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
