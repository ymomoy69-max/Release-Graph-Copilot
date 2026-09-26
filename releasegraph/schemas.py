"""Pydantic DTOs."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

_ORM = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = _ORM

    id: int
    email: str
    full_name: str
    role: str


class ReadinessPresetOut(BaseModel):
    id: str
    label: str
    workspace: str
    org_config: str = ""
    ci_dir: str = ""
    repos: list[str] = Field(default_factory=list)
    hint: str = ""


class ProjectOut(BaseModel):
    model_config = _ORM

    id: int
    slug: str
    name: str
    description: str
    workspace_path: str = ""
    org_config_path: str = ""
    readiness_presets: list[ReadinessPresetOut] = Field(default_factory=list)


class DeployGateOut(BaseModel):
    blocked: bool = False
    message: str | None = None
    blocking_count: int = 0
    issue_count: int = 0
    findings: list[dict[str, Any]] = []


class ShopStatusOut(BaseModel):
    gateway_url: str
    storefront_url: str
    payment_failure_mode: bool | None = None
    payment_status: str


class DashboardOut(BaseModel):
    active_releases: int
    recent_releases: list[dict[str, Any]]
    deployment_status: dict[str, int]
    open_incidents: int
    failed_builds: int
    services_count: int
    open_fix_prs: int = 0
    copilot_insight: str
    workspace_path: str | None = None
    scan_issue_count: int = 0
    scan_high_count: int = 0
    broken_links: int = 0
    production_version: str | None = None
    production_release_id: int | None = None
    draft_version: str | None = None
    production_risk_level: str | None = None
    production_risk_score: float | None = None
    production_risk_factors: list[dict[str, Any]] = []
    deploy_gate: DeployGateOut | None = None
    shop_status: ShopStatusOut | None = None
    recent_audit: list[dict[str, Any]] = []


class ReleaseOut(BaseModel):
    model_config = _ORM

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
    baseline_release_id: int | None = None
    baseline_version: str | None = None
    is_production: bool = False
    can_deploy: bool = False
    can_mark_ready: bool = False
    can_start_next: bool = False
    can_rollback: bool = False
    deploy_blocked: bool = False
    deploy_block_message: str | None = None
    deploy_gate: DeployGateOut | None = None


class ReleaseTrainOut(BaseModel):
    production_release_id: int | None = None
    production_version: str | None = None
    draft_release_id: int | None = None
    draft_version: str | None = None
    draft_status: str | None = None
    draft_baseline_version: str | None = None
    can_start_next: bool = False


class CreateNextReleaseRequest(BaseModel):
    summary: str | None = None


class DeployReleaseRequest(BaseModel):
    confirm: bool = False
    environment_slug: str = "production"


class ReleaseDetailOut(ReleaseOut):
    commits: list[dict[str, Any]]
    commits_since_baseline: list[dict[str, Any]] = []
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
    model_config = _ORM

    id: int
    title: str
    status: str
    severity: str
    service_name: str | None
    created_at: datetime


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


class ReadinessCheckRequest(BaseModel):
    """Scan a workspace on disk; optional org YAML under that path for rgc checkers."""

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
    deploy_gate: DeployGateOut | None = None
    release_train: ReleaseTrainOut | None = None
    org_config_path: str | None = None


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
    model_config = _ORM

    id: int
    timestamp: datetime
    action: str
    entity_type: str
    entity_id: str
    ai_generated: bool
    user_email: str | None
