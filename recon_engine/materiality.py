"""Materiality classifier.

Loads `seeds/materiality.csv` and classifies each per-account break value
as LOW / MEDIUM / HIGH severity. Mirrors the logic that the dbt
`recon_control_account` mart applies in SQL, but exposed as a plain
Python helper so the Slack alerter and the audit-trail writer can use
the same definition.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class MaterialityRule:
    account_code: str
    materiality_usd: Decimal
    severity: str  # LOW | MEDIUM | HIGH

    @classmethod
    def from_row(cls, row: dict[str, str]) -> MaterialityRule:
        return cls(
            account_code=row["account_code"].strip(),
            materiality_usd=Decimal(str(row["materiality_usd"])),
            severity=row["severity"].strip().upper(),
        )


_DEFAULT_KEY = "DEFAULT"


class MaterialityClassifier:
    """Per-account materiality lookup with a `DEFAULT` fallback row."""

    def __init__(self, rules: Iterable[MaterialityRule]) -> None:
        self._by_account: dict[str, MaterialityRule] = {}
        self._default: MaterialityRule | None = None
        for rule in rules:
            if rule.account_code == _DEFAULT_KEY:
                self._default = rule
            else:
                self._by_account[rule.account_code] = rule
        if self._default is None:
            raise ValueError(
                "materiality config must contain a 'DEFAULT' row for fallback"
            )

    @classmethod
    def from_csv(cls, path: str | Path) -> MaterialityClassifier:
        path = Path(path)
        with path.open(newline="") as fh:
            reader = csv.DictReader(fh)
            rules = [MaterialityRule.from_row(row) for row in reader]
        return cls(rules)

    def rule_for(self, account_code: str) -> MaterialityRule:
        return self._by_account.get(account_code, self._default)  # type: ignore[return-value]

    def classify(self, account_code: str, breaks_value_usd: Decimal | float) -> str:
        """Return PASS / WARN / FAIL based on the per-account threshold."""
        rule = self.rule_for(account_code)
        value = Decimal(str(breaks_value_usd))
        if value == 0:
            return "PASS"
        if value >= rule.materiality_usd:
            return "FAIL"
        return "WARN"
