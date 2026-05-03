"""Shared helpers: deterministic ID minting, date sampling, currency conversion."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np


def business_days(start: date, end: date) -> list[date]:
    """All weekdays in [start, end]. Mirrors how a real GL is posted."""
    out: list[date] = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def sample_dates(rng: np.random.Generator, days: list[date], n: int) -> np.ndarray:
    idx = rng.integers(0, len(days), size=n)
    return np.array([days[i] for i in idx])


def to_usd(amount_currency: float, currency: str, rate: float) -> float:
    """Convert transaction-currency amount to USD using the supplied rate-to-USD."""
    return round(amount_currency * rate, 2)


def mint_ids(prefix: str, n: int, start: int = 1) -> list[str]:
    """Stable, zero-padded IDs (e.g., AP-INV-0000001) so test snapshots are diff-friendly."""
    width = max(7, len(str(start + n - 1)))
    return [f"{prefix}-{i:0{width}d}" for i in range(start, start + n)]
