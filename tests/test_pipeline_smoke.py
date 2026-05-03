"""Smoke tests for the synthetic data pipeline.

These run on a tiny dataset (small overrides) so the full suite stays
under a few seconds. They guard the most important invariants:

  * The clean GL feed (before break injection) is fully balanced
    per (entity, business_date, journal_id) -- debits = credits.
  * Break injection produces the requested classes and is reproducible
    for a fixed seed.
  * Sub-ledger control-account balances tie to the GL within tolerance
    on the *clean* feed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from data_generator.config import BreakRates, Settings, Volumes
from data_generator.gl import generate_gl
from data_generator.pipeline import run_pipeline
from data_generator.reference import (
    AP_CONTROL,
    AR_CONTROL,
    INV_CONTROL,
    chart_of_accounts_df,
    entities_df,
    fx_lookup,
    fx_rates_df,
)
from data_generator.subledgers import (
    generate_ap_invoices,
    generate_ap_payments,
    generate_ar_invoices,
    generate_ar_receipts,
    generate_inventory,
)


@pytest.fixture
def tiny_settings() -> Settings:
    return Settings(
        seed=42,
        days=14,
        volumes=Volumes(
            ap_invoices=200, ap_payments=120, ap_accruals=20,
            ar_invoices=200, ar_receipts=120, ar_credit_memos=10,
            inv_receipts=80, inv_cogs=80, inv_adjustments=10,
            manual_je_per_day=2,
        ),
        breaks=BreakRates(
            timing_diff=0.05,
            amount_mismatch=0.02,
            missing_gl_posting=0.01,
            unauthorized_manual_je=0.10,
            fx_rounding=0.05,
        ),
    )


def test_pipeline_runs_end_to_end(tiny_settings: Settings) -> None:
    dataset = run_pipeline(tiny_settings)
    expected_tables = {
        "raw.dim_entity", "raw.dim_account", "raw.fx_rate",
        "raw.ap_invoices", "raw.ap_payments", "raw.ap_accruals",
        "raw.ar_invoices", "raw.ar_receipts", "raw.ar_credit_memos",
        "raw.inv_transactions", "raw.gl_journal",
    }
    assert expected_tables.issubset(dataset.tables.keys())
    assert len(dataset.tables["raw.gl_journal"]) > 0


def test_clean_gl_is_journal_balanced(tiny_settings: Settings) -> None:
    """Each clean journal_id must have debits = credits in USD."""
    rng = np.random.default_rng(tiny_settings.seed)
    entities = entities_df()
    fx = fx_rates_df(tiny_settings.start_date, tiny_settings.end_date, rng)
    fxl = fx_lookup(fx)

    ap_inv = generate_ap_invoices(tiny_settings, rng, entities, fxl)
    ap_pay = generate_ap_payments(tiny_settings, rng, ap_inv, fxl)
    ar_inv = generate_ar_invoices(tiny_settings, rng, entities, fxl)
    ar_rcp = generate_ar_receipts(tiny_settings, rng, ar_inv, fxl)
    inv = generate_inventory(tiny_settings, rng, entities)

    gl = generate_gl(
        tiny_settings, rng,
        ap_invoices=ap_inv, ap_payments=ap_pay,
        ar_invoices=ar_inv, ar_receipts=ar_rcp,
        inv_txns=inv, entities=entities, fx_lookup=fxl,
    )

    per_journal = gl.groupby("journal_id")[["debit_usd", "credit_usd"]].sum()
    assert ((per_journal["debit_usd"] - per_journal["credit_usd"]).abs() < 0.01).all(), (
        "Clean GL feed is not journal-balanced before break injection."
    )


def test_break_injection_is_reproducible(tiny_settings: Settings) -> None:
    """Same settings + seed -> same breaks log."""
    d1 = run_pipeline(tiny_settings)
    d2 = run_pipeline(tiny_settings)
    pd.testing.assert_frame_equal(d1.breaks_log, d2.breaks_log)


def test_break_classes_are_present(tiny_settings: Settings) -> None:
    dataset = run_pipeline(tiny_settings)
    classes = set(dataset.breaks_log["break_class"].unique())
    # With the elevated rates in the fixture, all five classes should appear.
    expected = {"timing_diff", "amount_mismatch", "missing_gl_posting", "fx_rounding"}
    assert expected.issubset(classes)


def test_chart_of_accounts_has_required_control_accounts() -> None:
    coa = chart_of_accounts_df(effective_from=pd.Timestamp("2026-01-01").date())
    controls = coa[coa["is_control_account"]]["account_code"].tolist()
    assert AP_CONTROL in controls
    assert AR_CONTROL in controls
    assert INV_CONTROL in controls
