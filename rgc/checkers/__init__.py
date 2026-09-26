"""
Checker registry.
"""
from __future__ import annotations

from rgc.checkers import pipeline, workflow_config, fc_etl, flyway, playwright_map


def default_checkers():
    """Return the five production checkers in required order."""
    return [
        pipeline.run,
        workflow_config.run,
        fc_etl.run,
        flyway.run,
        playwright_map.run,
    ]
