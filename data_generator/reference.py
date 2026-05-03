"""Reference data: chart of accounts, legal entities, and FX rates.

The chart of accounts is intentionally small but realistic: it includes
control accounts for AP/AR/Inventory, COGS, revenue, expense, cash, an
FX revaluation account, and a suspense account series (the recon engine
monitors these).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Chart of accounts (single source of truth for the rest of the generator)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AccountSpec:
    code: str
    name: str
    account_type: str  # ASSET | LIABILITY | EQUITY | REVENUE | EXPENSE
    parent: str | None = None
    is_control: bool = False
    subledger: str | None = None  # AP | AR | INV | None


CHART_OF_ACCOUNTS: list[AccountSpec] = [
    # Assets
    AccountSpec("1000", "Cash - Operating",            "ASSET",     parent=None),
    AccountSpec("1100", "Cash - Payroll",              "ASSET",     parent="1000"),
    AccountSpec("1200", "Accounts Receivable",         "ASSET",     parent=None, is_control=True, subledger="AR"),
    AccountSpec("1300", "Inventory",                   "ASSET",     parent=None, is_control=True, subledger="INV"),
    AccountSpec("1400", "Prepaid Expenses",            "ASSET",     parent=None),
    AccountSpec("1500", "Fixed Assets",                "ASSET",     parent=None),
    # Liabilities
    AccountSpec("2000", "Accounts Payable",            "LIABILITY", parent=None, is_control=True, subledger="AP"),
    AccountSpec("2100", "Accrued Expenses",            "LIABILITY", parent=None),
    AccountSpec("2200", "Sales Tax Payable",           "LIABILITY", parent=None),
    # Equity
    AccountSpec("3000", "Retained Earnings",           "EQUITY",    parent=None),
    # Revenue
    AccountSpec("4000", "Product Revenue",             "REVENUE",   parent=None),
    AccountSpec("4100", "Service Revenue",             "REVENUE",   parent=None),
    AccountSpec("4200", "Other Revenue",               "REVENUE",   parent=None),
    # Expenses
    AccountSpec("5000", "Cost of Goods Sold",          "EXPENSE",   parent=None),
    AccountSpec("6000", "Salaries & Wages",            "EXPENSE",   parent=None),
    AccountSpec("6100", "Rent",                        "EXPENSE",   parent=None),
    AccountSpec("6200", "Utilities",                   "EXPENSE",   parent=None),
    AccountSpec("6300", "Software & Subscriptions",    "EXPENSE",   parent=None),
    AccountSpec("6400", "Travel",                      "EXPENSE",   parent=None),
    AccountSpec("6500", "Professional Services",       "EXPENSE",   parent=None),
    AccountSpec("6600", "Marketing",                   "EXPENSE",   parent=None),
    AccountSpec("6900", "Other Operating Expenses",    "EXPENSE",   parent=None),
    AccountSpec("7900", "FX Revaluation Gain/Loss",    "EXPENSE",   parent=None),
    # Suspense series — should always net to zero. Recon engine monitors.
    AccountSpec("9999", "Suspense - Unmapped",         "ASSET",     parent=None),
]


def chart_of_accounts_df(effective_from: date) -> pd.DataFrame:
    rows = [
        {
            "account_id": idx + 1,
            "account_code": a.code,
            "account_name": a.name,
            "account_type": a.account_type,
            "parent_account_code": a.parent,
            "is_control_account": a.is_control,
            "subledger_source": a.subledger,
            "effective_from": effective_from,
            "effective_to": None,
        }
        for idx, a in enumerate(CHART_OF_ACCOUNTS)
    ]
    return pd.DataFrame(rows)


# Convenience lookups used elsewhere in the generator.
EXPENSE_ACCOUNTS_FOR_AP = ["6000", "6100", "6200", "6300", "6400", "6500", "6600", "6900"]
REVENUE_ACCOUNTS_FOR_AR = ["4000", "4100", "4200"]
AP_CONTROL = "2000"
AR_CONTROL = "1200"
INV_CONTROL = "1300"
COGS_ACCOUNT = "5000"
CASH_ACCOUNT = "1000"
FX_REVAL_ACCOUNT = "7900"
SUSPENSE_ACCOUNT = "9999"


# ---------------------------------------------------------------------------
# Legal entities
# ---------------------------------------------------------------------------

ENTITIES: list[dict[str, object]] = [
    {"entity_id": 1, "entity_code": "US01", "entity_name": "Acme US Inc.",        "functional_currency": "USD", "country": "United States"},
    {"entity_id": 2, "entity_code": "EU01", "entity_name": "Acme Europe GmbH",    "functional_currency": "EUR", "country": "Germany"},
    {"entity_id": 3, "entity_code": "IN01", "entity_name": "Acme India Pvt Ltd.", "functional_currency": "INR", "country": "India"},
]


def entities_df() -> pd.DataFrame:
    return pd.DataFrame(ENTITIES)


# ---------------------------------------------------------------------------
# FX rates (deterministic random-walk around realistic central rates)
# ---------------------------------------------------------------------------

# Central rates (1 unit of from_currency = X USD) as of project start.
_CENTRAL_RATES_TO_USD: dict[str, float] = {
    "USD": 1.0,
    "EUR": 1.08,    # 1 EUR ~ 1.08 USD
    "INR": 0.012,   # 1 INR ~ 0.012 USD
}


def fx_rates_df(start: date, end: date, rng: np.random.Generator) -> pd.DataFrame:
    """Generate daily FX rates as a small random walk around central rates.

    Realistic enough to drive translation differences without being so noisy
    that recon becomes statistically impossible.
    """
    rows = []
    n_days = (end - start).days + 1
    currencies = [c for c in _CENTRAL_RATES_TO_USD if c != "USD"]

    walks = {
        c: _CENTRAL_RATES_TO_USD[c] * (1 + np.cumsum(rng.normal(0, 0.0015, n_days)))
        for c in currencies
    }

    for i in range(n_days):
        d = start + timedelta(days=i)
        # USD -> USD always 1
        rows.append({"rate_date": d, "from_currency": "USD", "to_currency": "USD", "rate": 1.0})
        for c in currencies:
            r = max(walks[c][i], 0.0001)  # guard against pathological negatives
            rows.append({"rate_date": d, "from_currency": c, "to_currency": "USD", "rate": float(r)})
    return pd.DataFrame(rows)


def fx_lookup(fx_df: pd.DataFrame) -> dict[tuple[date, str], float]:
    """O(1) lookup of (date, currency) -> rate-to-USD."""
    return {
        (row.rate_date, row.from_currency): float(row.rate)
        for row in fx_df.itertuples(index=False)
    }
