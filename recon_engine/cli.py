"""Manual reconciliation CLI.

Lets operators run the full recon pipeline (data load + dbt build +
audit + Slack alert) from a plain shell, without Dagster. Handy for
cron, CI, ad-hoc backfills, and one-shot demos.

Examples:
    python -m recon_engine.cli run-recon
    python -m recon_engine.cli run-recon --skip-data-load
    python -m recon_engine.cli list-runs --limit 10
    python -m recon_engine.cli show-run <run_id>
"""

from __future__ import annotations

import os
import subprocess
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import structlog
import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import create_engine, text

from .alerts import CheckOutcome, SlackAlerter
from .audit import (
    AuditTrailWriter,
    load_check_results_from_marts,
    load_source_row_counts,
    read_dbt_manifest_hash,
)

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)
console = Console()
log = structlog.get_logger(__name__)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DBT_PROJECT_DIR = PROJECT_ROOT / "dbt_project"


def _build_engine():
    user = os.environ.get("POSTGRES_USER", "glrecon")
    password = os.environ.get("POSTGRES_PASSWORD", "glrecon")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "glrecon")
    dsn = f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"
    return create_engine(dsn, future=True)


def _run_command(cmd: list[str], cwd: Path | None = None, env_extra: dict | None = None) -> int:
    """Stream a subprocess to stdout and return the exit code."""
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(cmd, cwd=cwd, env=env, check=False)
    return proc.returncode


@app.command("run-recon")
def run_recon(
    skip_data_load: bool = typer.Option(False, help="Skip the synthetic data generation + load step."),
    skip_dbt: bool = typer.Option(False, help="Skip the dbt build step (use existing marts)."),
    triggered_by: str = typer.Option("manual:cli", help="Recorded in audit.recon_runs."),
) -> None:
    """End-to-end reconciliation: data load -> dbt build -> audit -> Slack."""
    engine = _build_engine()
    writer = AuditTrailWriter(engine)
    business_date = date.today()
    run_id = writer.start_run(business_date=business_date, triggered_by=triggered_by)
    console.print(f"[blue]Recon run started[/blue]: run_id={run_id}")

    try:
        if not skip_data_load:
            console.print("[blue]Step 1/3: synthetic data load[/blue]")
            rc = _run_command(
                ["python", "-m", "data_generator.cli", "seed"],
                cwd=PROJECT_ROOT,
            )
            if rc != 0:
                raise RuntimeError(f"data load failed (exit code {rc})")

        if not skip_dbt:
            console.print("[blue]Step 2/3: dbt build[/blue]")
            rc = _run_command(
                ["dbt", "build", "--no-version-check"],
                cwd=DBT_PROJECT_DIR,
                env_extra={"DBT_PROFILES_DIR": str(DBT_PROJECT_DIR)},
            )
            # dbt returns 0 for full pass, 1 for warnings/test failures, 2 for hard error.
            # We treat 0 and 1 as "ran"; 2 fails the run.
            if rc >= 2:
                raise RuntimeError(f"dbt build hard-errored (exit code {rc})")

        console.print("[blue]Step 3/3: writing audit trail + Slack alert[/blue]")
        checks = load_check_results_from_marts(engine)
        source_counts = load_source_row_counts(engine, schema="raw")
        manifest_hash = read_dbt_manifest_hash(DBT_PROJECT_DIR)

        summary = writer.finalize(
            run_id=run_id,
            checks=checks,
            source_row_counts=source_counts,
            dbt_manifest_hash=manifest_hash,
        )

        threshold = Decimal(os.environ.get("MATERIALITY_THRESHOLD_USD", "10000"))
        alerter = SlackAlerter(
            webhook_url=os.environ.get("SLACK_WEBHOOK_URL"),
            materiality_threshold_usd=threshold,
        )
        alerter.alert(
            business_date=str(summary.business_date),
            overall_status=summary.status,
            checks=[
                CheckOutcome(
                    check_name=c.check_name,
                    status=c.status,
                    breaks_count=c.breaks_count,
                    breaks_value_usd=c.breaks_value_usd,
                )
                for c in summary.checks
            ],
        )

        _render_summary(summary)
        console.print(f"[green]✓ Recon run {summary.run_id} complete: {summary.status}[/green]")

    except Exception as exc:
        writer.mark_error(run_id, str(exc))
        console.print(f"[red]✗ Recon run {run_id} errored: {exc}[/red]")
        raise typer.Exit(code=1) from exc


@app.command("list-runs")
def list_runs(limit: int = typer.Option(10, help="How many recent runs to show.")) -> None:
    """Show the most recent rows from audit.recon_runs."""
    engine = _build_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT run_id, business_date, status, started_at, finished_at, triggered_by
                FROM audit.recon_runs
                ORDER BY started_at DESC
                LIMIT :limit
            """),
            {"limit": limit},
        ).fetchall()

    table = Table(title=f"Recent recon runs (latest {limit})", show_header=True)
    for col in ("run_id", "business_date", "status", "started_at", "finished_at", "triggered_by"):
        table.add_column(col)
    for r in rows:
        finished = str(r.finished_at) if r.finished_at else "(running)"
        table.add_row(
            str(r.run_id)[:8] + "...",
            str(r.business_date),
            r.status,
            str(r.started_at),
            finished,
            r.triggered_by,
        )
    console.print(table)


@app.command("show-run")
def show_run(run_id: str = typer.Argument(..., help="Full or 8-char prefix of the run_id.")) -> None:
    """Detailed view of a single run's check results."""
    engine = _build_engine()
    with engine.connect() as conn:
        # Resolve a prefix to a full uuid if needed.
        if len(run_id) < 36:
            row = conn.execute(
                text("SELECT run_id FROM audit.recon_runs WHERE run_id::text LIKE :p"),
                {"p": run_id + "%"},
            ).first()
            if not row:
                console.print(f"[red]No run found matching prefix {run_id}[/red]")
                raise typer.Exit(code=1)
            run_id = str(row.run_id)

        run = conn.execute(
            text("SELECT * FROM audit.recon_runs WHERE run_id = :r"),
            {"r": uuid.UUID(run_id)},
        ).one()
        checks = conn.execute(
            text("""
                SELECT check_name, status, breaks_count, breaks_value_usd, materiality_usd
                FROM audit.recon_check_results
                WHERE run_id = :r
                ORDER BY check_name
            """),
            {"r": uuid.UUID(run_id)},
        ).fetchall()

    console.print(f"[bold]Run {run_id}[/bold]")
    console.print(f"  business_date    : {run.business_date}")
    console.print(f"  status           : {run.status}")
    console.print(f"  started_at       : {run.started_at}")
    console.print(f"  finished_at      : {run.finished_at}")
    console.print(f"  triggered_by     : {run.triggered_by}")
    console.print(f"  git_commit_sha   : {run.git_commit_sha}")
    console.print(f"  dbt_manifest_hash: {run.dbt_manifest_hash}")

    table = Table(title="Per-check results")
    for col in ("check_name", "status", "breaks_count", "breaks_value_usd", "materiality_usd"):
        table.add_column(col)
    for c in checks:
        table.add_row(
            c.check_name,
            c.status,
            f"{c.breaks_count:,}",
            f"${c.breaks_value_usd:,.2f}",
            f"${c.materiality_usd:,.2f}" if c.materiality_usd else "—",
        )
    console.print(table)


def _render_summary(summary) -> None:
    """Pretty-print a RunSummary."""
    table = Table(title=f"Recon run {summary.run_id}", show_header=True)
    for col in ("check_name", "status", "breaks_count", "breaks_value_usd"):
        table.add_column(col)
    for c in summary.checks:
        table.add_row(
            c.check_name,
            c.status,
            f"{c.breaks_count:,}",
            f"${c.breaks_value_usd:,.2f}",
        )
    console.print(table)
    console.print(
        f"Overall: [bold]{summary.status}[/bold] | "
        f"{summary.fail_count} FAIL | "
        f"{summary.warn_count} WARN | "
        f"${summary.total_breaks_value_usd:,.2f} total breaks"
    )


if __name__ == "__main__":
    app()
