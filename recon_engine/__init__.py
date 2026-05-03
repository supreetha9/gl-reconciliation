"""Reusable, Dagster-agnostic recon-engine helpers.

This package holds the orchestrator-independent pieces of the reconciliation
control: the SOX-style audit trail writer, the Slack alerter, and the
materiality classifier. All three are designed to be importable from
Dagster, Airflow, a plain cron job, or a unit test without dragging in any
orchestration framework.
"""

__version__ = "0.1.0"

from .alerts import SlackAlerter, build_alert_message
from .audit import AuditTrailWriter, RunSummary
from .evidence import build_evidence_pack, evidence_filename
from .materiality import MaterialityClassifier, MaterialityRule

__all__ = [
    "AuditTrailWriter",
    "MaterialityClassifier",
    "MaterialityRule",
    "RunSummary",
    "SlackAlerter",
    "build_alert_message",
    "build_evidence_pack",
    "evidence_filename",
]
