"""Centralized, typed configuration for the data generator.

All knobs live here. Defaults match `.env.example`. Environment variables
prefixed with ``GLRECON_`` override defaults; a local ``.env`` file is
loaded automatically.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BreakRates(BaseModel):
    """Probability of each break class being injected per eligible row.

    These are the four classes every controller cares about, plus FX noise.
    Rates are intentionally low so the recon still mostly ties — the goal
    is realism, not chaos.
    """

    timing_diff: float = Field(0.02, ge=0, le=1, description="Sub-ledger posted T, GL posted T+1.")
    amount_mismatch: float = Field(0.005, ge=0, le=1, description="Penny-level rounding/FX deltas.")
    missing_gl_posting: float = Field(0.003, ge=0, le=1, description="Sub-ledger entry never reaches GL.")
    unauthorized_manual_je: float = Field(0.002, ge=0, le=1, description="Manual JE hits a control account (SOX red flag).")
    fx_rounding: float = Field(0.01, ge=0, le=1, description="FX rounding noise on EUR/INR translation.")


class Volumes(BaseModel):
    """Approximate row counts over the full generation window."""

    ap_invoices: int = 10_000
    ap_payments: int = 8_000
    ap_accruals: int = 500
    ar_invoices: int = 15_000
    ar_receipts: int = 12_000
    ar_credit_memos: int = 300
    inv_receipts: int = 4_000
    inv_cogs: int = 4_000
    inv_adjustments: int = 400
    manual_je_per_day: int = 5


class Settings(BaseSettings):
    """Top-level config. Loaded from environment + ``.env``."""

    model_config = SettingsConfigDict(
        env_prefix="GLRECON_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    seed: int = 42
    days: int = 90
    end_date: date = Field(default_factory=date.today)
    output_dir: Path = Path("./data/raw")

    reporting_currency: str = "USD"
    transaction_currencies: list[str] = ["USD", "EUR", "INR"]

    # Composition is the idiomatic pydantic v2 pattern for nested config.
    volumes: Volumes = Field(default_factory=Volumes)
    breaks: BreakRates = Field(default_factory=BreakRates)

    # Postgres connection (also read by the loader).
    postgres_user: str = "glrecon"
    postgres_password: str = "glrecon"
    postgres_db: str = "glrecon"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    @property
    def start_date(self) -> date:
        return self.end_date - timedelta(days=self.days - 1)

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


def load_settings(**overrides: object) -> Settings:
    """Build a Settings instance, applying explicit overrides on top of env."""
    return Settings(**overrides)  # type: ignore[arg-type]
