"""General Ledger generator.

Builds the double-entry journal that the recon engine validates against.
Every sub-ledger row produces exactly one balanced journal entry (two
lines that net to zero in USD). Plus a small daily volume of manual JEs
to give the SOX 'unauthorized JE' check something to find.

Important: this module produces the *clean* GL feed. ``inject_breaks``
runs after this and intentionally perturbs the result.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Settings
from .reference import (
    AP_CONTROL,
    AR_CONTROL,
    CASH_ACCOUNT,
    COGS_ACCOUNT,
    EXPENSE_ACCOUNTS_FOR_AP,
    INV_CONTROL,
)
from .utils import business_days, mint_ids, sample_dates

# Lines have these columns in the order Postgres expects.
_GL_COLS = [
    "journal_id", "journal_line_id", "entity_id", "business_date", "posting_date",
    "account_code", "debit_usd", "credit_usd", "currency", "amount_currency",
    "fx_rate", "source_system", "source_doc_id", "description", "created_by",
]


def _entry(
    journal_id: str,
    entity_id: int,
    business_date,
    posting_date,
    debit_account: str,
    credit_account: str,
    amount_usd: float,
    currency: str,
    amount_currency: float,
    fx_rate: float,
    source_system: str,
    source_doc_id: str,
    description: str,
    created_by: str,
) -> list[dict]:
    """Return the two balanced journal lines for a single entry."""
    common = {
        "journal_id": journal_id,
        "entity_id": int(entity_id),
        "business_date": business_date,
        "posting_date": posting_date,
        "currency": currency,
        "amount_currency": float(amount_currency),
        "fx_rate": float(fx_rate),
        "source_system": source_system,
        "source_doc_id": source_doc_id,
        "description": description,
        "created_by": created_by,
    }
    return [
        {**common, "journal_line_id": 1, "account_code": debit_account,
         "debit_usd": float(amount_usd), "credit_usd": 0.0},
        {**common, "journal_line_id": 2, "account_code": credit_account,
         "debit_usd": 0.0,               "credit_usd": float(amount_usd)},
    ]


# ---------------------------------------------------------------------------
# Sub-ledger -> GL feed translators (the "happy path")
# ---------------------------------------------------------------------------

def _ap_invoice_to_gl(row, journal_id: str) -> list[dict]:
    # Vendor invoice: Dr Expense, Cr AP
    return _entry(
        journal_id=journal_id,
        entity_id=row.entity_id,
        business_date=row.invoice_date,
        posting_date=row.posting_date,
        debit_account=row.expense_account_code,
        credit_account=AP_CONTROL,
        amount_usd=row.amount_usd,
        currency=row.currency,
        amount_currency=row.amount_currency,
        fx_rate=row.fx_rate,
        source_system="AP",
        source_doc_id=row.invoice_id,
        description=f"AP invoice {row.invoice_id}",
        created_by="ap_subledger_feed",
    )


def _ap_payment_to_gl(row, journal_id: str) -> list[dict]:
    # Payment: Dr AP, Cr Cash
    return _entry(
        journal_id=journal_id,
        entity_id=row.entity_id,
        business_date=row.payment_date,
        posting_date=row.posting_date,
        debit_account=AP_CONTROL,
        credit_account=row.cash_account_code,
        amount_usd=row.amount_usd,
        currency=row.currency,
        amount_currency=row.amount_currency,
        fx_rate=row.fx_rate,
        source_system="AP",
        source_doc_id=row.payment_id,
        description=f"AP payment {row.payment_id}",
        created_by="ap_subledger_feed",
    )


def _ar_invoice_to_gl(row, journal_id: str) -> list[dict]:
    # Customer invoice: Dr AR, Cr Revenue
    return _entry(
        journal_id=journal_id,
        entity_id=row.entity_id,
        business_date=row.invoice_date,
        posting_date=row.posting_date,
        debit_account=AR_CONTROL,
        credit_account=row.revenue_account_code,
        amount_usd=row.amount_usd,
        currency=row.currency,
        amount_currency=row.amount_currency,
        fx_rate=row.fx_rate,
        source_system="AR",
        source_doc_id=row.invoice_id,
        description=f"AR invoice {row.invoice_id}",
        created_by="ar_subledger_feed",
    )


def _ar_receipt_to_gl(row, journal_id: str) -> list[dict]:
    # Customer payment received: Dr Cash, Cr AR
    return _entry(
        journal_id=journal_id,
        entity_id=row.entity_id,
        business_date=row.receipt_date,
        posting_date=row.posting_date,
        debit_account=row.cash_account_code,
        credit_account=AR_CONTROL,
        amount_usd=row.amount_usd,
        currency=row.currency,
        amount_currency=row.amount_currency,
        fx_rate=row.fx_rate,
        source_system="AR",
        source_doc_id=row.receipt_id,
        description=f"AR receipt {row.receipt_id}",
        created_by="ar_subledger_feed",
    )


def _inv_to_gl(row, journal_id: str) -> list[dict]:
    """Inventory postings. Direction depends on txn_type and adjustment sign."""
    if row.txn_type == "RECEIPT":
        debit, credit = INV_CONTROL, AP_CONTROL
        amount = abs(row.amount_usd)
    elif row.txn_type == "COGS":
        debit, credit = COGS_ACCOUNT, INV_CONTROL
        amount = abs(row.amount_usd)
    else:  # ADJUSTMENT
        if row.amount_usd >= 0:
            debit, credit = INV_CONTROL, "6900"
        else:
            debit, credit = "6900", INV_CONTROL
        amount = abs(row.amount_usd)

    return _entry(
        journal_id=journal_id,
        entity_id=row.entity_id,
        business_date=row.txn_date,
        posting_date=row.posting_date,
        debit_account=debit,
        credit_account=credit,
        amount_usd=amount,
        currency="USD",
        amount_currency=amount,
        fx_rate=1.0,
        source_system="INV",
        source_doc_id=row.txn_id,
        description=f"INV {row.txn_type} {row.txn_id}",
        created_by="inv_subledger_feed",
    )


# ---------------------------------------------------------------------------
# Manual JEs (the SOX-flag generator: small fraction will hit control accts)
# ---------------------------------------------------------------------------

def _generate_manual_jes(
    settings: Settings,
    rng: np.random.Generator,
    entities: pd.DataFrame,
    fx_lookup: dict[tuple, float],
) -> list[dict]:
    days = business_days(settings.start_date, settings.end_date)
    n = len(days) * settings.volumes.manual_je_per_day
    if n == 0:
        return []

    je_dates = sample_dates(rng, days, n)
    entity_ids = rng.choice(entities["entity_id"].to_numpy(), size=n)
    amounts = np.round(rng.lognormal(mean=6.0, sigma=0.8, size=n), 2)
    journal_ids = mint_ids("GL-MJE", n)
    accounts_pool = [*EXPENSE_ACCOUNTS_FOR_AP, "1400", "2100", "2200", CASH_ACCOUNT]

    rows: list[dict] = []
    for jid, d, e, amt in zip(journal_ids, je_dates, entity_ids, amounts, strict=True):
        debit_acc = str(rng.choice(accounts_pool))
        credit_acc = str(rng.choice([a for a in accounts_pool if a != debit_acc]))
        rows.extend(_entry(
            journal_id=jid,
            entity_id=e,
            business_date=d,
            posting_date=d,
            debit_account=debit_acc,
            credit_account=credit_acc,
            amount_usd=float(amt),
            currency="USD",
            amount_currency=float(amt),
            fx_rate=1.0,
            source_system="MANUAL",
            source_doc_id=jid,
            description="Manual journal entry (period-end true-up)",
            created_by=str(rng.choice(["j.controller", "k.accountant", "s.gl_lead"])),
        ))
    return rows


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_gl(
    settings: Settings,
    rng: np.random.Generator,
    *,
    ap_invoices: pd.DataFrame,
    ap_payments: pd.DataFrame,
    ar_invoices: pd.DataFrame,
    ar_receipts: pd.DataFrame,
    inv_txns: pd.DataFrame,
    entities: pd.DataFrame,
    fx_lookup: dict[tuple, float],
) -> pd.DataFrame:
    """Build the full GL feed by translating every sub-ledger row + manual JEs."""
    rows: list[dict] = []

    for prefix, df, fn in [
        ("GL-AP-INV", ap_invoices, _ap_invoice_to_gl),
        ("GL-AP-PAY", ap_payments, _ap_payment_to_gl),
        ("GL-AR-INV", ar_invoices, _ar_invoice_to_gl),
        ("GL-AR-RCP", ar_receipts, _ar_receipt_to_gl),
        ("GL-INV",    inv_txns,    _inv_to_gl),
    ]:
        jids = mint_ids(prefix, len(df))
        for jid, row in zip(jids, df.itertuples(index=False), strict=True):
            rows.extend(fn(row, jid))

    rows.extend(_generate_manual_jes(settings, rng, entities, fx_lookup))

    df = pd.DataFrame(rows, columns=_GL_COLS)
    # Stable ordering helps deterministic snapshots and human inspection.
    return df.sort_values(["business_date", "journal_id", "journal_line_id"]).reset_index(drop=True)
