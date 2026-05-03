"""Unit tests for ``recon_engine.alerts``.

These tests do NOT require a Slack webhook -- they patch ``requests.post``
and assert on the payload that would be sent.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from recon_engine.alerts import (
    CheckOutcome,
    SlackAlerter,
    build_alert_message,
)


@pytest.fixture
def sample_checks() -> list[CheckOutcome]:
    return [
        CheckOutcome("control_account",   "FAIL", breaks_count=12, breaks_value_usd=Decimal("123456.78")),
        CheckOutcome("transaction_level", "WARN", breaks_count=200, breaks_value_usd=Decimal("4567.89")),
        CheckOutcome("roll_forward",      "PASS", breaks_count=0,   breaks_value_usd=Decimal("0")),
    ]


# ---------------------------------------------------------------------------
# build_alert_message
# ---------------------------------------------------------------------------

def test_message_separates_above_and_below_threshold(sample_checks):
    payload = build_alert_message(
        business_date="2026-05-03",
        overall_status="FAIL",
        checks=sample_checks,
        materiality_threshold_usd=Decimal("10000"),
    )
    body = payload["blocks"][0]["text"]["text"]
    # control_account is above $10K -> appears in the body
    assert "control_account" in body
    assert "$123,456.78" in body
    # transaction_level + roll_forward are below -> footer line
    assert "2 check(s) below the $10,000 threshold" in body


def test_message_uses_appropriate_emoji_per_status(sample_checks):
    for status, expected in [
        ("PASS", ":white_check_mark:"),
        ("WARN", ":warning:"),
        ("FAIL", ":rotating_light:"),
        ("ERROR", ":x:"),
    ]:
        body = build_alert_message(
            "2026-05-03", status, sample_checks, Decimal("10000")
        )["blocks"][0]["text"]["text"]
        assert expected in body, f"missing {expected} for status {status}"


def test_message_when_nothing_above_threshold(sample_checks):
    # Very high threshold means nothing material today -- the body should say so.
    payload = build_alert_message(
        "2026-05-03", "WARN", sample_checks, Decimal("1000000")
    )
    body = payload["blocks"][0]["text"]["text"]
    assert "No checks above the materiality threshold" in body


# ---------------------------------------------------------------------------
# SlackAlerter
# ---------------------------------------------------------------------------

def test_alerter_is_no_op_when_webhook_unset(sample_checks, caplog):
    alerter = SlackAlerter(webhook_url=None)
    assert alerter.enabled is False
    sent = alerter.alert("2026-05-03", "FAIL", sample_checks)
    assert sent is False


def test_alerter_posts_to_webhook_on_success(sample_checks):
    fake_response = MagicMock(status_code=200)
    with patch("requests.post", return_value=fake_response) as mock_post:
        alerter = SlackAlerter(
            webhook_url="https://hooks.slack.com/services/FAKE",
            materiality_threshold_usd=Decimal("10000"),
        )
        sent = alerter.alert("2026-05-03", "FAIL", sample_checks)

    assert sent is True
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["timeout"] == 5.0
    payload = kwargs["json"]
    assert payload["text"].startswith("GL Recon 2026-05-03")
    assert "blocks" in payload


def test_alerter_returns_false_on_non_200(sample_checks):
    fake_response = MagicMock(status_code=500)
    with patch("requests.post", return_value=fake_response):
        alerter = SlackAlerter(webhook_url="https://example.com/hook")
        assert alerter.alert("2026-05-03", "FAIL", sample_checks) is False


def test_alerter_swallows_exceptions(sample_checks):
    with patch("requests.post", side_effect=Exception("network down")):
        alerter = SlackAlerter(webhook_url="https://example.com/hook")
        # The pipeline must NEVER crash because Slack is down.
        assert alerter.alert("2026-05-03", "FAIL", sample_checks) is False
