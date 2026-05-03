"""End-to-end synthetic data generation pipeline.

Runs all generators in dependency order, applies break injection, and
returns a dict of named DataFrames ready to be persisted.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import Settings
from .gl import generate_gl
from .inject_breaks import inject_breaks
from .logging_setup import get_logger
from .reference import (
    chart_of_accounts_df,
    entities_df,
    fx_lookup,
    fx_rates_df,
)
from .subledgers import (
    generate_ap_accruals,
    generate_ap_invoices,
    generate_ap_payments,
    generate_ar_credit_memos,
    generate_ar_invoices,
    generate_ar_receipts,
    generate_inventory,
)

log = get_logger(__name__)


@dataclass
class GeneratedDataset:
    """All tables produced by one pipeline run, keyed by `raw.*` table name."""

    tables: dict[str, pd.DataFrame]
    breaks_log: pd.DataFrame

    def row_counts(self) -> dict[str, int]:
        return {name: len(df) for name, df in self.tables.items()}


def run_pipeline(settings: Settings) -> GeneratedDataset:
    rng = np.random.default_rng(settings.seed)
    log.info("pipeline.start",
             seed=settings.seed,
             days=settings.days,
             start=str(settings.start_date),
             end=str(settings.end_date))

    entities = entities_df()
    coa = chart_of_accounts_df(settings.start_date)
    fx = fx_rates_df(settings.start_date, settings.end_date, rng)
    fxl = fx_lookup(fx)

    log.info("reference.generated",
             entities=len(entities), accounts=len(coa), fx_rows=len(fx))

    ap_inv = generate_ap_invoices(settings, rng, entities, fxl)
    ap_pay = generate_ap_payments(settings, rng, ap_inv, fxl)
    ap_acc = generate_ap_accruals(settings, rng, entities, fxl)
    ar_inv = generate_ar_invoices(settings, rng, entities, fxl)
    ar_rcp = generate_ar_receipts(settings, rng, ar_inv, fxl)
    ar_cm = generate_ar_credit_memos(settings, rng, ar_inv, fxl)
    inv = generate_inventory(settings, rng, entities)

    log.info("subledgers.generated",
             ap_invoices=len(ap_inv), ap_payments=len(ap_pay), ap_accruals=len(ap_acc),
             ar_invoices=len(ar_inv), ar_receipts=len(ar_rcp), ar_credit_memos=len(ar_cm),
             inv_transactions=len(inv))

    gl = generate_gl(
        settings, rng,
        ap_invoices=ap_inv, ap_payments=ap_pay,
        ar_invoices=ar_inv, ar_receipts=ar_rcp,
        inv_txns=inv, entities=entities, fx_lookup=fxl,
    )
    log.info("gl.generated", lines=len(gl))

    gl_perturbed, breaks_log = inject_breaks(settings, rng, gl)
    log.info("breaks.injected",
             total=len(breaks_log),
             by_class=breaks_log["break_class"].value_counts().to_dict() if len(breaks_log) else {})

    return GeneratedDataset(
        tables={
            "raw.dim_entity":      entities,
            "raw.dim_account":     coa,
            "raw.fx_rate":         fx,
            "raw.ap_invoices":     ap_inv,
            "raw.ap_payments":     ap_pay,
            "raw.ap_accruals":     ap_acc,
            "raw.ar_invoices":     ar_inv,
            "raw.ar_receipts":     ar_rcp,
            "raw.ar_credit_memos": ar_cm,
            "raw.inv_transactions": inv,
            "raw.gl_journal":      gl_perturbed,
        },
        breaks_log=breaks_log,
    )
