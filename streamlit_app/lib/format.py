"""Formatting helpers for currency, status badges, and dates."""

from __future__ import annotations

from decimal import Decimal


def money(value: float | Decimal | int | None, prefix: str = "$") -> str:
    """Render a USD value with thousands separators."""
    if value is None:
        return "—"
    return f"{prefix}{float(value):,.2f}"


_STATUS_COLORS = {
    "PASS":    ("#0F5132", "#D1E7DD"),
    "WARN":    ("#664D03", "#FFF3CD"),
    "FAIL":    ("#842029", "#F8D7DA"),
    "ERROR":   ("#FFFFFF", "#A02736"),
    "RUNNING": ("#055160", "#CFF4FC"),
    "MATCHED": ("#0F5132", "#D1E7DD"),
    "BREAK":   ("#842029", "#F8D7DA"),
}


def status_badge(status: str) -> str:
    """Render a coloured pill for a status string. Returns an HTML snippet."""
    fg, bg = _STATUS_COLORS.get(status, ("#41464B", "#E9ECEF"))
    return (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:12px;'
        f'background-color:{bg};color:{fg};font-weight:600;font-size:0.85em;">{status}</span>'
    )
