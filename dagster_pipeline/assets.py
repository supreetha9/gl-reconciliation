"""Dagster assets for the daily GL reconciliation.

Three asset groups:

  1. ``raw_synthetic_data``  -- runs the Faker-based generator + COPYs
                                CSVs into Postgres ``raw.*``. Upstream of
                                everything dbt does.
  2. ``dbt_assets``           -- one Dagster asset per dbt model, derived
                                from the parsed dbt manifest.
  3. ``audit_recon_run``      -- terminal asset that records the run in
                                ``audit.*`` and fires the Slack alert.
"""

from __future__ import annotations

from datetime import date

from dagster import (
    AssetExecutionContext,
    AssetKey,
    AssetSpec,
    Output,
    asset,
)
from dagster_dbt import DbtCliResource, dbt_assets

from data_generator.config import load_settings
from data_generator.loader import load_dataframes
from data_generator.pipeline import run_pipeline
from recon_engine.alerts import CheckOutcome
from recon_engine.audit import (
    AuditTrailWriter,
    load_check_results_from_marts,
    load_source_row_counts,
    read_dbt_manifest_hash,
)

from .resources import PostgresResource, SlackResource, dbt_project

# ---------------------------------------------------------------------------
# 1. Synthetic data load
# ---------------------------------------------------------------------------

@asset(
    name="raw_synthetic_data",
    group_name="ingestion",
    description=(
        "Generates ~50K AP/AR/Inventory/GL postings with realistic break "
        "injection and COPYs them into the Postgres `raw.*` tables. In "
        "production this asset would be replaced by the actual ERP feed."
    ),
    compute_kind="python",
)
def raw_synthetic_data(context: AssetExecutionContext) -> Output[dict[str, int]]:
    settings = load_settings()
    context.log.info("running pipeline with seed=%d days=%d", settings.seed, settings.days)
    dataset = run_pipeline(settings)
    counts = load_dataframes(settings, dataset.tables)
    return Output(
        value=counts,
        metadata={
            "rows_loaded": sum(counts.values()),
            "tables": list(counts.keys()),
            "breaks_injected": len(dataset.breaks_log),
        },
    )


# ---------------------------------------------------------------------------
# 2. dbt models -- auto-generated assets via dagster-dbt
# ---------------------------------------------------------------------------

@dbt_assets(manifest=dbt_project.manifest_path)
def glrecon_dbt_assets(context: AssetExecutionContext, dbt: DbtCliResource):
    """Every dbt model becomes a software-defined asset with full lineage."""
    yield from dbt.cli(["build", "--no-version-check"], context=context).stream()


# ---------------------------------------------------------------------------
# 3. Audit trail + Slack alert
# ---------------------------------------------------------------------------

@asset(
    name="audit_recon_run",
    group_name="audit",
    deps=[AssetKey(["recon_summary"])],   # downstream of the dbt summary mart
    description=(
        "Writes one row to `audit.recon_runs` plus per-check rows to "
        "`audit.recon_check_results`, then fires a Slack alert if any "
        "check has breaks above the materiality threshold."
    ),
    compute_kind="python",
)
def audit_recon_run(
    context: AssetExecutionContext,
    postgres: PostgresResource,
    slack: SlackResource,
) -> Output[dict]:
    engine = postgres.get_engine()
    writer = AuditTrailWriter(engine)
    business_date = date.today()

    run_id = writer.start_run(business_date=business_date, triggered_by="schedule")

    try:
        checks = load_check_results_from_marts(engine)
        source_counts = load_source_row_counts(engine, schema="raw")
        manifest_hash = read_dbt_manifest_hash(dbt_project.project_dir)

        summary = writer.finalize(
            run_id=run_id,
            checks=checks,
            source_row_counts=source_counts,
            dbt_manifest_hash=manifest_hash,
        )
    except Exception as exc:
        writer.mark_error(run_id, str(exc))
        raise

    # Alert.
    alerter = slack.get_alerter()
    outcomes = [
        CheckOutcome(
            check_name=c.check_name,
            status=c.status,
            breaks_count=c.breaks_count,
            breaks_value_usd=c.breaks_value_usd,
        )
        for c in summary.checks
    ]
    alerter.alert(
        business_date=str(summary.business_date),
        overall_status=summary.status,
        checks=outcomes,
    )

    context.log.info(
        "recon run %s finalized: status=%s, %d checks, $%s total breaks",
        summary.run_id, summary.status, len(summary.checks), summary.total_breaks_value_usd,
    )

    return Output(
        value={
            "run_id": str(summary.run_id),
            "status": summary.status,
            "fail_count": summary.fail_count,
            "warn_count": summary.warn_count,
            "total_breaks_value_usd": float(summary.total_breaks_value_usd),
        },
        metadata={
            "run_id": str(summary.run_id),
            "status": summary.status,
            "checks": len(summary.checks),
            "fail_count": summary.fail_count,
            "warn_count": summary.warn_count,
        },
    )


# Convenience: the full asset list (consumed by Definitions).
ASSETS = [raw_synthetic_data, glrecon_dbt_assets, audit_recon_run]


# Suppress unused-import warning -- AssetSpec is re-exported for downstream
# convenience even though we don't use it in this module.
_ = AssetSpec
