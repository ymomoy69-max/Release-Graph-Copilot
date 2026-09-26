"""Audit logging helper."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from releasegraph.models import AuditEvent, User


def log_audit(
    db: Session,
    organization_id: int,
    action: str,
    entity_type: str,
    entity_id: str | int,
    user: User | None = None,
    previous_state: dict[str, Any] | None = None,
    new_state: dict[str, Any] | None = None,
    ai_generated: bool = False,
    metadata: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            organization_id=organization_id,
            user_id=user.id if user else None,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            previous_state=json.dumps(previous_state or {}),
            new_state=json.dumps(new_state or {}),
            ai_generated=ai_generated,
            metadata_json=json.dumps(metadata or {}),
        )
    )
