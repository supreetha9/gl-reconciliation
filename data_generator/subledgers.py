"""Sub-ledger generators: AP, AR, Inventory.

Each generator returns a tidy pandas DataFrame whose columns match the
``raw.*`` Postgres tables one-to-one. The generators are pure functions
of (settings, rng, reference data) -- no global state, no I/O.

Currency mix mirrors entity functional currency, with a small fraction of
cross-currency invoices to drive the FX revaluation check.
"""

from __future__ import annotations

from datetime import timedelta

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
    REVENUE_ACCOUNTS_FOR_AR,
)
from .utils import business_days, mint_ids, sample_dates, to_usd


def _sample_currencies(
    rng: np.random.Generator, entity_ids: np.ndarray, entities: pd.DataFrame
) -> np.ndarray:
    """80% functional currency, 20% cross-currency (to exercise FX recon)."""
    fc_lookup = dict(zip(entities["entity_id"], entities["functional_currency"], strict=True))
    out = []
    pool = ["USD", "EUR", "INR"]
    for e in entity_ids:
        if rng.random() < 0.8:
            out.append(fc_lookup[int(e)])
        else:
            out.append(rng.choice(pool))
    return np.array(out)


def _resolve_fx(
    dates: np.ndarray, currencies: np.ndarray, fx_lookup: dict[tuple, float]
) -> np.ndarray:
    return np.array([fx_lookup[(d, c)] for d, c in zip(dates, currencies, strict=True)])


# ---------------------------------------------------------------------------
# Accounts Payable
# ---------------------------------------------------------------------------

def generate_ap_invoices(
    settings: Settings,
    rng: np.random.Generator,
    entities: pd.DataFrame,
    fx_lookup: dict[tuple, float],
) -> pd.DataFrame:
    n = settings.volumes.ap_invoices
    days = business_days(settings.start_date, settings.end_date)

    ids = mint_ids("AP-INV", n)
    vendor_ids = [f"V-{i:05d}" for i in rng.integers(1, 800, size=n)]
    entity_ids = rng.choice(entities["entity_id"].to_numpy(), size=n)
    invoice_dates = sample_dates(rng, days, n)
    posting_dates = invoice_dates  # same-day post in the happy path; break injector will perturb
    due_dates = np.array([d + timedelta(days=int(rng.integers(15, 60))) for d in invoice_dates])
    currencies = _sample_currencies(rng, entity_ids, entities)
    fx = _resolve_fx(invoice_dates, currencies, fx_lookup)

    # Log-normal amount distribution gives a realistic long tail of large invoices.
    amounts_usd = np.round(rng.lognormal(mean=6.5, sigma=1.0, size=n), 2)
    amounts_currency = np.round(amounts_usd / fx, 2)

    expense_accounts = rng.choice(EXPENSE_ACCOUNTS_FOR_AP, size=n)
    statuses = rng.choice(["OPEN", "PAID", "VOID", "HOLD"], size=n, p=[0.30, 0.65, 0.02, 0.03])

    return pd.DataFrame({
        "invoice_id": ids,
        "vendor_id": vendor_ids,
        "entity_id": entity_ids,
        "invoice_date": invoice_dates,
        "posting_date": posting_dates,
        "due_date": due_dates,
        "currency": currencies,
        "amount_currency": amounts_currency,
        "amount_usd": amounts_usd,
        "fx_rate": fx,
        "expense_account_code": expense_accounts,
        "control_account_code": AP_CONTROL,
        "status": statuses,
        "description": [f"Vendor invoice from {v}" for v in vendor_ids],
    })


def generate_ap_payments(
    settings: Settings,
    rng: np.random.Generator,
    ap_invoices: pd.DataFrame,
    fx_lookup: dict[tuple, float],
) -> pd.DataFrame:
    paid = ap_invoices[ap_invoices["status"] == "PAID"]
    n = min(settings.volumes.ap_payments, len(paid))
    sample = paid.sample(n=n, random_state=int(rng.integers(0, 2**31 - 1))).reset_index(drop=True)

    payment_dates = np.array([
        d + timedelta(days=int(rng.integers(5, 45))) for d in sample["invoice_date"]
    ])
    payment_dates = np.minimum(payment_dates, settings.end_date)
    fx = _resolve_fx(payment_dates, sample["currency"].to_numpy(), fx_lookup)

    return pd.DataFrame({
        "payment_id": mint_ids("AP-PAY", n),
        "invoice_id": sample["invoice_id"],
        "entity_id": sample["entity_id"],
        "payment_date": payment_dates,
        "posting_date": payment_dates,
        "currency": sample["currency"],
        "amount_currency": sample["amount_currency"],
        "amount_usd": [to_usd(a, c, r) for a, c, r in zip(sample["amount_currency"], sample["currency"], fx, strict=True)],
        "fx_rate": fx,
        "cash_account_code": CASH_ACCOUNT,
        "control_account_code": AP_CONTROL,
        "method": rng.choice(["ACH", "WIRE", "CHECK", "CARD"], size=n, p=[0.55, 0.25, 0.10, 0.10]),
    })


def generate_ap_accruals(
    settings: Settings,
    rng: np.random.Generator,
    entities: pd.DataFrame,
    fx_lookup: dict[tuple, float],
) -> pd.DataFrame:
    n = settings.volumes.ap_accruals
    days = business_days(settings.start_date, settings.end_date)

    accrual_dates = sample_dates(rng, days, n)
    entity_ids = rng.choice(entities["entity_id"].to_numpy(), size=n)
    currencies = _sample_currencies(rng, entity_ids, entities)
    fx = _resolve_fx(accrual_dates, currencies, fx_lookup)
    amounts_usd = np.round(rng.lognormal(mean=7.0, sigma=0.7, size=n), 2)
    amounts_currency = np.round(amounts_usd / fx, 2)

    return pd.DataFrame({
        "accrual_id": mint_ids("AP-ACC", n),
        "entity_id": entity_ids,
        "accrual_date": accrual_dates,
        "posting_date": accrual_dates,
        "reversal_date": [d + timedelta(days=int(rng.integers(15, 35))) for d in accrual_dates],
        "currency": currencies,
        "amount_currency": amounts_currency,
        "amount_usd": amounts_usd,
        "fx_rate": fx,
        "expense_account_code": rng.choice(EXPENSE_ACCOUNTS_FOR_AP, size=n),
        "control_account_code": AP_CONTROL,
        "description": ["Month-end accrual"] * n,
    })


# ---------------------------------------------------------------------------
# Accounts Receivable
# ---------------------------------------------------------------------------

def generate_ar_invoices(
    settings: Settings,
    rng: np.random.Generator,
    entities: pd.DataFrame,
    fx_lookup: dict[tuple, float],
) -> pd.DataFrame:
    n = settings.volumes.ar_invoices
    days = business_days(settings.start_date, settings.end_date)

    ids = mint_ids("AR-INV", n)
    customer_ids = [f"C-{i:05d}" for i in rng.integers(1, 1500, size=n)]
    entity_ids = rng.choice(entities["entity_id"].to_numpy(), size=n)
    invoice_dates = sample_dates(rng, days, n)
    due_dates = np.array([d + timedelta(days=int(rng.integers(15, 60))) for d in invoice_dates])
    currencies = _sample_currencies(rng, entity_ids, entities)
    fx = _resolve_fx(invoice_dates, currencies, fx_lookup)
    amounts_usd = np.round(rng.lognormal(mean=7.0, sigma=1.1, size=n), 2)
    amounts_currency = np.round(amounts_usd / fx, 2)

    return pd.DataFrame({
        "invoice_id": ids,
        "customer_id": customer_ids,
        "entity_id": entity_ids,
        "invoice_date": invoice_dates,
        "posting_date": invoice_dates,
        "due_date": due_dates,
        "currency": currencies,
        "amount_currency": amounts_currency,
        "amount_usd": amounts_usd,
        "fx_rate": fx,
        "revenue_account_code": rng.choice(REVENUE_ACCOUNTS_FOR_AR, size=n),
        "control_account_code": AR_CONTROL,
        "status": rng.choice(["OPEN", "PAID", "VOID", "WRITTEN_OFF"], size=n, p=[0.28, 0.68, 0.01, 0.03]),
        "description": [f"Customer invoice for {c}" for c in customer_ids],
    })


def generate_ar_receipts(
    settings: Settings,
    rng: np.random.Generator,
    ar_invoices: pd.DataFrame,
    fx_lookup: dict[tuple, float],
) -> pd.DataFrame:
    paid = ar_invoices[ar_invoices["status"] == "PAID"]
    n = min(settings.volumes.ar_receipts, len(paid))
    sample = paid.sample(n=n, random_state=int(rng.integers(0, 2**31 - 1))).reset_index(drop=True)

    receipt_dates = np.array([
        d + timedelta(days=int(rng.integers(5, 50))) for d in sample["invoice_date"]
    ])
    receipt_dates = np.minimum(receipt_dates, settings.end_date)
    fx = _resolve_fx(receipt_dates, sample["currency"].to_numpy(), fx_lookup)

    return pd.DataFrame({
        "receipt_id": mint_ids("AR-RCP", n),
        "invoice_id": sample["invoice_id"],
        "entity_id": sample["entity_id"],
        "receipt_date": receipt_dates,
        "posting_date": receipt_dates,
        "currency": sample["currency"],
        "amount_currency": sample["amount_currency"],
        "amount_usd": [to_usd(a, c, r) for a, c, r in zip(sample["amount_currency"], sample["currency"], fx, strict=True)],
        "fx_rate": fx,
        "cash_account_code": CASH_ACCOUNT,
        "control_account_code": AR_CONTROL,
        "method": rng.choice(["ACH", "WIRE", "CHECK", "CARD"], size=n, p=[0.50, 0.30, 0.05, 0.15]),
    })


def generate_ar_credit_memos(
    settings: Settings,
    rng: np.random.Generator,
    ar_invoices: pd.DataFrame,
    fx_lookup: dict[tuple, float],
) -> pd.DataFrame:
    n = settings.volumes.ar_credit_memos
    sample = ar_invoices.sample(n=n, random_state=int(rng.integers(0, 2**31 - 1))).reset_index(drop=True)

    memo_dates = np.array([
        d + timedelta(days=int(rng.integers(1, 30))) for d in sample["invoice_date"]
    ])
    memo_dates = np.minimum(memo_dates, settings.end_date)
    fx = _resolve_fx(memo_dates, sample["currency"].to_numpy(), fx_lookup)
    fraction = rng.uniform(0.05, 0.5, size=n)
    amounts_currency = np.round(sample["amount_currency"].to_numpy() * fraction, 2)
    amounts_usd = np.round(amounts_currency * fx, 2)

    return pd.DataFrame({
        "memo_id": mint_ids("AR-CM", n),
        "invoice_id": sample["invoice_id"],
        "entity_id": sample["entity_id"],
        "memo_date": memo_dates,
        "posting_date": memo_dates,
        "currency": sample["currency"],
        "amount_currency": amounts_currency,
        "amount_usd": amounts_usd,
        "fx_rate": fx,
        "reason": rng.choice(["RETURN", "PRICE_ADJ", "WRITE_OFF"], size=n, p=[0.55, 0.35, 0.10]),
        "revenue_account_code": sample["revenue_account_code"],
        "control_account_code": AR_CONTROL,
    })


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

def generate_inventory(
    settings: Settings,
    rng: np.random.Generator,
    entities: pd.DataFrame,
) -> pd.DataFrame:
    """Generate inventory receipts, COGS postings, and adjustments in one pass.

    Returns a single tidy DataFrame matching `raw.inv_transactions` so the
    loader doesn't need to know about the sub-types.
    """
    n_recv = settings.volumes.inv_receipts
    n_cogs = settings.volumes.inv_cogs
    n_adj = settings.volumes.inv_adjustments
    days = business_days(settings.start_date, settings.end_date)

    def _block(prefix: str, n: int, txn_type: str, mean_qty: float, sigma_qty: float, mean_cost: float) -> pd.DataFrame:
        item_ids = [f"SKU-{i:05d}" for i in rng.integers(1, 600, size=n)]
        entity_ids = rng.choice(entities["entity_id"].to_numpy(), size=n)
        txn_dates = sample_dates(rng, days, n)
        qty = np.round(np.abs(rng.normal(mean_qty, sigma_qty, size=n)), 4)
        unit_cost = np.round(np.abs(rng.normal(mean_cost, mean_cost * 0.2, size=n)), 4)
        if txn_type == "ADJUSTMENT":
            qty = qty * rng.choice([-1, 1], size=n, p=[0.4, 0.6])
        amount_usd = np.round(qty * unit_cost, 2)

        if txn_type == "RECEIPT":
            inv_acc, off_acc = INV_CONTROL, AP_CONTROL  # GR/IR pattern: Dr Inventory, Cr AP
        elif txn_type == "COGS":
            inv_acc, off_acc = COGS_ACCOUNT, INV_CONTROL  # Dr COGS, Cr Inventory
        else:
            inv_acc, off_acc = INV_CONTROL, "6900"  # Dr/Cr Inventory, Cr/Dr Other Op Ex

        return pd.DataFrame({
            "txn_id": mint_ids(prefix, n),
            "item_id": item_ids,
            "entity_id": entity_ids,
            "txn_date": txn_dates,
            "posting_date": txn_dates,
            "txn_type": txn_type,
            "quantity": qty,
            "unit_cost_usd": unit_cost,
            "amount_usd": amount_usd,
            "inventory_account_code": inv_acc,
            "offset_account_code": off_acc,
            "description": [f"{txn_type} for {i}" for i in item_ids],
        })

    return pd.concat(
        [
            _block("INV-RCV", n_recv, "RECEIPT", mean_qty=50, sigma_qty=20, mean_cost=25.0),
            _block("INV-CGS", n_cogs, "COGS",    mean_qty=10, sigma_qty=8,  mean_cost=25.0),
            _block("INV-ADJ", n_adj,  "ADJUSTMENT", mean_qty=5, sigma_qty=4, mean_cost=25.0),
        ],
        ignore_index=True,
    )
