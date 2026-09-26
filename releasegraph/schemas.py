"""Pydantic DTOs."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str

    class Config:
        from_attributes = True


class ProjectOut(BaseModel):
    id: int
    slug: str
    name: str
    description: str
    workspace_path: str = ""

    class Config:
        from_attributes = True


class DashboardOut(BaseModel):
    active_releases: int
    recent_releases: list[dict[str, Any]]
    deployment_status: dict[str, int]
    open_incidents: int
    failed_builds: int
    services_count: int
    open_fix_prs: int = 0
    copilot_insight: str


class ReleaseOut(BaseModel):
    id: int
    version: str
    status: str
    risk_level: str
    risk_score: float
    summary: str
    created_at: datetime
    rollback_available: bool
    services: list[str] = []
    commits_count: int = 0
    prs_count: int = 0

    class Config:
        from_attributes = True


class ReleaseDetailOut(ReleaseOut):
    commits: list[dict[str, Any]]
    pull_requests: list[dict[str, Any]]
    builds: list[dict[str, Any]]
    tests: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    deployments: list[dict[str, Any]]
    risk_factors: list[dict[str, Any]]
    environment: str | None = None


class GraphOut(BaseModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    summary: str = ""
    broken_links: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    broken_services: list[str] = []
    affected_services: list[str] = []
    workspace: str | None = None


class CopilotAskRequest(BaseModel):
    project_id: int
    question: str = Field(min_length=1, max_length=4000)


class CopilotAskResponse(BaseModel):
    answer: str
    tool_calls: list[dict[str, Any]]


class IncidentOut(BaseModel):
    id: int
    title: str
    status: str
    severity: str
    service_name: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class IncidentCreate(BaseModel):
    title: str
    service_id: int | None = None
    severity: str = "high"


class RollbackRequest(BaseModel):
    confirm: bool = False


class ConfirmAction(BaseModel):
    confirm: bool = False


class AssignFixPrRequest(BaseModel):
    assignee_user_id: int


class SimulateDeployRequest(BaseModel):
    release_id: int
    environment_slug: str = "production"


class ReadinessPresetOut(BaseModel):
    id: str
    label: str
    kind: str


class ReadinessCheckRequest(BaseModel):
    """Point at cloned repos (workspace) + optional org YAML, or use a preset / release manifest."""

    preset: str | None = None
    workspace: str | None = None
    config: str | None = None
    repos: list[str] | None = None
    ci_dir: str | None = None
    changed_paths: list[str] | None = None
    release_file: str | None = None
    project_id: int | None = None
    persist: bool = True


class ReadinessCheckResponse(BaseModel):
    checklist: dict
    ready_to_release: bool
    question: str = "Is this deploy safe?"
    analysis: dict | None = None
    scan: dict | None = None


class WorkspaceScanRequest(BaseModel):
    workspace: str
    project_id: int | None = None
    persist: bool = True


class AnalysisRequest(BaseModel):
    project_id: int
    workspace: str | None = None
    incident_id: int | None = None
    checklist: dict | None = None


class AuditEventOut(BaseModel):
    id: int
    timestamp: datetime
    action: str
    entity_type: str
    entity_id: str
    ai_generated: bool
    user_email: str | None

    class Config:
        from_attributes = True
