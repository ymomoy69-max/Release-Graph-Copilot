"""SQLAlchemy domain models."""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from releasegraph.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    ENGINEER = "ENGINEER"
    RELEASE_MANAGER = "RELEASE_MANAGER"
    VIEWER = "VIEWER"


class ReleaseStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    BUILDING = "BUILDING"
    TESTING = "TESTING"
    READY = "READY"
    DEPLOYING = "DEPLOYING"
    DEPLOYED = "DEPLOYED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class DeploymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class IncidentStatus(str, enum.Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    MITIGATED = "MITIGATED"
    RESOLVED = "RESOLVED"


class FixProposalStatus(str, enum.Enum):
    OPEN = "OPEN"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MERGED = "MERGED"


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.ENGINEER)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    organization: Mapped["Organization"] = relationship(back_populates="users")


Organization.users = relationship("User", back_populates="organization")  # noqa: E402


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    slug: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    workspace_path: Mapped[str] = mapped_column(String(1024), default="")
    org_config_path: Mapped[str] = mapped_column(String(1024), default="")
    readiness_presets_json: Mapped[str] = mapped_column(Text, default="[]")
    production_release_id: Mapped[int | None] = mapped_column(
        ForeignKey("releases.id", use_alter=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_project_org_slug"),)


class Repository(Base):
    __tablename__ = "repositories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    default_branch: Mapped[str] = mapped_column(String(64), default="main")
    url: Mapped[str] = mapped_column(String(512), default="")


class Service(Base):
    __tablename__ = "services"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    criticality: Mapped[str] = mapped_column(String(32), default="medium")  # low|medium|high
    repository_id: Mapped[int | None] = mapped_column(ForeignKey("repositories.id"), nullable=True)
    source_path: Mapped[str] = mapped_column(String(1024), default="")


class ServiceDependency(Base):
    __tablename__ = "service_dependencies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    from_service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    to_service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    __table_args__ = (
        UniqueConstraint("from_service_id", "to_service_id", name="uq_service_dep"),
    )


class Environment(Base):
    __tablename__ = "environments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    slug: Mapped[str] = mapped_column(String(64))


class Commit(Base):
    __tablename__ = "commits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    sha: Mapped[str] = mapped_column(String(40), index=True)
    author: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PullRequest(Base):
    __tablename__ = "pull_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(512))
    author: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(32), default="merged")
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Build(Base):
    __tablename__ = "builds"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    release_id: Mapped[int | None] = mapped_column(ForeignKey("releases.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)


class TestRun(Base):
    __tablename__ = "test_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    build_id: Mapped[int] = mapped_column(ForeignKey("builds.id"), index=True)
    suite: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32))
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    build_id: Mapped[int] = mapped_column(ForeignKey("builds.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    version: Mapped[str] = mapped_column(String(64))
    uri: Mapped[str] = mapped_column(String(512), default="")


class Release(Base):
    __tablename__ = "releases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    version: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[ReleaseStatus] = mapped_column(Enum(ReleaseStatus), default=ReleaseStatus.DRAFT)
    environment_id: Mapped[int | None] = mapped_column(ForeignKey("environments.id"), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    risk_level: Mapped[str] = mapped_column(String(16), default="LOW")
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    rollback_available: Mapped[bool] = mapped_column(Boolean, default=True)
    baseline_release_id: Mapped[int | None] = mapped_column(
        ForeignKey("releases.id"), nullable=True, index=True
    )


class ReleaseCommit(Base):
    __tablename__ = "release_commits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id"), index=True)
    commit_id: Mapped[int] = mapped_column(ForeignKey("commits.id"))


class ReleasePullRequest(Base):
    __tablename__ = "release_pull_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id"), index=True)
    pull_request_id: Mapped[int] = mapped_column(ForeignKey("pull_requests.id"))


class ReleaseService(Base):
    __tablename__ = "release_services"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id"), index=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))


class Deployment(Base):
    __tablename__ = "deployments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id"), index=True)
    environment_id: Mapped[int] = mapped_column(ForeignKey("environments.id"))
    status: Mapped[DeploymentStatus] = mapped_column(
        Enum(DeploymentStatus), default=DeploymentStatus.PENDING
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    initiated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class RiskFactor(Base):
    __tablename__ = "risk_factors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id"), index=True)
    factor: Mapped[str] = mapped_column(String(255))
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    detail: Mapped[str] = mapped_column(Text, default="")


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(512))
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus), default=IncidentStatus.OPEN
    )
    severity: Mapped[str] = mapped_column(String(32), default="high")
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id"), nullable=True)
    release_id: Mapped[int | None] = mapped_column(ForeignKey("releases.id"), nullable=True)
    deployment_id: Mapped[int | None] = mapped_column(ForeignKey("deployments.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_notes: Mapped[str] = mapped_column(Text, default="")


class IncidentEvent(Base):
    __tablename__ = "incident_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    event_type: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(128), default="system")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    action: Mapped[str] = mapped_column(String(128))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(64))
    previous_state: Mapped[str] = mapped_column(Text, default="")
    new_state: Mapped[str] = mapped_column(Text, default="")
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")


class CopilotConversation(Base):
    __tablename__ = "copilot_conversations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(255), default="Copilot chat")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class CopilotMessage(Base):
    __tablename__ = "copilot_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("copilot_conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(32))  # user | assistant | tool
    content: Mapped[str] = mapped_column(Text)
    tool_calls_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class FixProposal(Base):
    """In-app fix ticket from workspace scan — human review before close."""

    __tablename__ = "fix_proposals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[FixProposalStatus] = mapped_column(
        Enum(FixProposalStatus), default=FixProposalStatus.NEEDS_HUMAN
    )
    assignee_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    file_path: Mapped[str] = mapped_column(String(1024), default="")
    line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    service_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    severity: Mapped[str] = mapped_column(String(32), default="medium")
    code: Mapped[str] = mapped_column(String(64), default="")
    engine_fix: Mapped[str] = mapped_column(Text, default="")
    llm_suggestion: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    affects_json: Mapped[str] = mapped_column(Text, default="[]")
    confidence: Mapped[str] = mapped_column(String(32), default="high")
    llm_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    human_required: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verify_message: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (UniqueConstraint("project_id", "number", name="uq_fix_proposal_number"),)
