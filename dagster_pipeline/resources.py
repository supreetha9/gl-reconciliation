"""Dagster resources: Postgres engine, dbt project, Slack alerter.

All resources read configuration from environment variables so the same
code runs locally, in CI, and in production without code changes.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from dagster import ConfigurableResource, EnvVar
from dagster_dbt import DbtCliResource, DbtProject
from sqlalchemy import Engine, create_engine

from recon_engine.alerts import SlackAlerter

# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------

class PostgresResource(ConfigurableResource):
    """Builds a SQLAlchemy ``Engine`` against the project Postgres."""

    user: str
    password: str
    host: str
    port: int
    database: str

    def get_engine(self) -> Engine:
        dsn = (
            f"postgresql+psycopg://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )
        return create_engine(dsn, future=True)


# ---------------------------------------------------------------------------
# dbt
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DBT_PROJECT_DIR = PROJECT_ROOT / "dbt_project"

# `DbtProject.prepare_if_dev()` regenerates the manifest at startup when
# DAGSTER_DBT_PARSE_PROJECT_ON_LOAD=1 is set (handy for local dev).
dbt_project = DbtProject(
    project_dir=str(DBT_PROJECT_DIR),
    profiles_dir=str(DBT_PROJECT_DIR),
    target="dev",
)
dbt_project.prepare_if_dev()


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

class SlackResource(ConfigurableResource):
    """Wraps the project's :class:`SlackAlerter`.

    The webhook URL is read from ``SLACK_WEBHOOK_URL``. When unset the
    alerter is a no-op, so the pipeline never depends on Slack being
    reachable.
    """

    webhook_url: str = ""
    materiality_threshold_usd: float = 10_000.0

    def get_alerter(self) -> SlackAlerter:
        return SlackAlerter(
            webhook_url=self.webhook_url or None,
            materiality_threshold_usd=Decimal(str(self.materiality_threshold_usd)),
        )


# ---------------------------------------------------------------------------
# Single source of truth for the resources dict, consumed by Definitions.
# ---------------------------------------------------------------------------

def build_resources() -> dict[str, object]:
    return {
        "postgres": PostgresResource(
            user=EnvVar("POSTGRES_USER"),
            password=EnvVar("POSTGRES_PASSWORD"),
            host=EnvVar("POSTGRES_HOST"),
            port=EnvVar.int("POSTGRES_PORT"),
            database=EnvVar("POSTGRES_DB"),
        ),
        "dbt": DbtCliResource(project_dir=dbt_project),
        "slack": SlackResource(
            webhook_url=EnvVar("SLACK_WEBHOOK_URL"),
            materiality_threshold_usd=10_000.0,
        ),
    }
