"""Dagster orchestration for the daily GL reconciliation.

The package is intentionally thin: it wires the synthetic data generator,
the dbt project, the audit-trail writer, and the Slack alerter into
software-defined assets and a daily schedule. All the actual recon logic
lives in ``dbt_project/`` and ``recon_engine/``.

Entry point for the Dagster CLI:
    DAGSTER_HOME=$PWD/.dagster_home  dagster dev -m dagster_pipeline.definitions
"""

__version__ = "0.1.0"
