"""
Checker registry.
"""
from __future__ import annotations

from rgc.checkers import ci_status, db_migration, config_change, secret_scan, changeset_size


def default_checkers():
    """Return the five production checkers in required order (matches CHECK_ORDER)."""
    return [
        ci_status.run,
        db_migration.run,
        config_change.run,
        secret_scan.run,
        changeset_size.run,
    ]
