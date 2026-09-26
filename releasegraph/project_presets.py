"""Readiness workspace presets stored per project (paths on disk, not canned UI buttons)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from releasegraph.models import Project

_REPO_ROOT = Path(__file__).resolve().parent.parent


def repo_root() -> Path:
    return _REPO_ROOT


def default_streaming_presets(streaming_path: Path) -> list[dict[str, Any]]:
    root = str(streaming_path.resolve())
    return [
        {
            "id": "streaming",
            "label": "Streaming microservices (demo/streaming)",
            "workspace": root,
            "org_config": "",
            "ci_dir": "",
            "repos": [],
            "hint": "8-service OTT stack: content, entitlement, billing, session, notification, recommendation, gateway, frontend.",
        },
        *rgc_fixture_presets(),
    ]


def default_ecommerce_presets(ecommerce_path: Path) -> list[dict[str, Any]]:
    root = str(ecommerce_path.resolve())
    return [
        {
            "id": "ecommerce",
            "label": "E-commerce microservices (demo/ecommerce)",
            "workspace": root,
            "org_config": "",
            "ci_dir": "",
            "repos": [],
            "hint": "Workspace scanner only unless you add org.yaml under this tree.",
        }
    ]


def rgc_fixture_presets() -> list[dict[str, Any]]:
    root = repo_root()
    return [
        {
            "id": "acme-fixtures",
            "label": "Acme fixtures workspace (org.yaml + green CI)",
            "workspace": str((root / "fixtures" / "workspace").resolve()),
            "org_config": str((root / "fixtures" / "org.yaml").resolve()),
            "ci_dir": str((root / "fixtures" / "ci-status" / "green").resolve()),
            "repos": ["app-backend", "data-pipeline", "gateway", "frontend", "infra", "rules-engine"],
            "hint": "Full rgc checker suite from fixtures/org.yaml.",
        },
        {
            "id": "other-org",
            "label": "Other-org fixtures workspace",
            "workspace": str((root / "fixtures" / "other-org" / "workspace").resolve()),
            "org_config": str((root / "fixtures" / "other-org" / "org.yaml").resolve()),
            "ci_dir": str((root / "fixtures" / "other-org" / "ci").resolve()),
            "repos": ["api", "web", "jobs"],
            "hint": "Second org fixture tree for GO/NO-GO comparisons.",
        },
    ]


def presets_for_project(project: Project) -> list[dict[str, Any]]:
    raw = (project.readiness_presets_json or "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list) and data:
                return data
        except json.JSONDecodeError:
            pass
    if (project.workspace_path or "").strip():
        return [
            {
                "id": "default",
                "label": Path(project.workspace_path).name or "Workspace",
                "workspace": project.workspace_path,
                "org_config": project.org_config_path or "",
                "ci_dir": "",
                "repos": [],
                "hint": "",
            }
        ]
    return []


def serialize_presets_json(presets: list[dict[str, Any]]) -> str:
    return json.dumps(presets)
