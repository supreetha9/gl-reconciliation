"""Slack alerter.

Posts a materiality-thresholded summary of the latest reconciliation run
to a Slack incoming webhook. No-op (logs a warning, returns False) when
``SLACK_WEBHOOK_URL`` is unset, so the rest of the pipeline never blocks
on alert delivery.

Designed to be Dagster-agnostic: it accepts a plain ``RunSummary`` from
``recon_engine.audit`` and a webhook URL, and uses ``requests`` to POST.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CheckOutcome:
    check_name: str
    status: str  # PASS | WARN | FAIL
    breaks_count: int
    breaks_value_usd: Decimal


def build_alert_message(
    business_date: str,
    overall_status: str,
    checks: Sequence[CheckOutcome],
    materiality_threshold_usd: Decimal,
) -> dict:
    """Construct the Slack Block Kit payload (works with the simple webhook API too).

    Only checks whose ``breaks_value_usd`` clears the threshold are
    listed in the body; the count of below-threshold checks is summarised
    in a footer line so the message stays scannable.
    """
    headline_emoji = {
        "PASS": ":white_check_mark:",
        "WARN": ":warning:",
        "FAIL": ":rotating_light:",
        "ERROR": ":x:",
    }.get(overall_status, ":grey_question:")

    above = [c for c in checks if c.breaks_value_usd >= materiality_threshold_usd]
    below = [c for c in checks if c.breaks_value_usd < materiality_threshold_usd]

    lines: list[str] = [
        f"{headline_emoji}  *Daily GL Reconciliation — {business_date}*  →  *{overall_status}*",
        "",
    ]
    if above:
        lines.append("*Material breaks (above threshold):*")
        for c in above:
            lines.append(
                f"  • `{c.check_name}` — {c.breaks_count:,} breaks, "
                f"${c.breaks_value_usd:,.2f} ({c.status})"
            )
    else:
        lines.append("_No checks above the materiality threshold._")
    if below:
        lines.append("")
        lines.append(
            f"_({len(below)} check(s) below the ${materiality_threshold_usd:,.0f} threshold; "
            "see the Recon Cockpit for detail.)_"
        )

    return {
        "text": f"GL Recon {business_date}: {overall_status}",  # plain-text fallback
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(lines)},
            }
        ],
    }


class SlackAlerter:
    """Thin wrapper around ``requests.post`` to a Slack incoming webhook."""

    def __init__(
        self,
        webhook_url: str | None,
        materiality_threshold_usd: Decimal | float = Decimal("10000"),
        timeout_seconds: float = 5.0,
    ) -> None:
        self.webhook_url = webhook_url or None
        self.materiality_threshold_usd = Decimal(str(materiality_threshold_usd))
        self.timeout_seconds = timeout_seconds

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def alert(
        self,
        business_date: str,
        overall_status: str,
        checks: Sequence[CheckOutcome],
    ) -> bool:
        """Send the alert. Returns True iff the webhook accepted the post."""
        if not self.enabled:
            log.warning(
                "slack.alert.skipped",
                reason="SLACK_WEBHOOK_URL not configured",
                overall_status=overall_status,
            )
            return False

        payload = build_alert_message(
            business_date=business_date,
            overall_status=overall_status,
            checks=checks,
            materiality_threshold_usd=self.materiality_threshold_usd,
        )

        # Lazy import so unit tests can run without the requests dep installed
        # (we mock requests in the tests).
        import requests

        try:
            resp = requests.post(
                self.webhook_url,  # type: ignore[arg-type]
                json=payload,
                timeout=self.timeout_seconds,
            )
            ok = resp.status_code == 200
            log.info(
                "slack.alert.sent" if ok else "slack.alert.failed",
                status_code=resp.status_code,
                overall_status=overall_status,
            )
            return ok
        except Exception as exc:
            log.error("slack.alert.exception", error=str(exc))
            return False
