"""Top-level Dagster Definitions.

Discovered by ``dagster dev -m dagster_pipeline.definitions``. Wires
the asset graph, the daily schedule, asset checks, and the resource
bindings together.
"""

from __future__ import annotations

from dagster import Definitions

from .assets import ASSETS
from .resources import build_resources
from .schedules import JOBS, SCHEDULES
from .sensors import ASSET_CHECKS

defs = Definitions(
    assets=ASSETS,
    asset_checks=ASSET_CHECKS,
    jobs=JOBS,
    schedules=SCHEDULES,
    resources=build_resources(),
)
