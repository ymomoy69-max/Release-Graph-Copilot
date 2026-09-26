"""Copilot data tools — all answers must come from these queries."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from releasegraph.models import (
    Commit,
    Deployment,
    Incident,
    IncidentEvent,
    Project,
    PullRequest,
    Release,
    ReleaseCommit,
    ReleasePullRequest,
    ReleaseService,
    ReleaseStatus,
    Service,
    ServiceDependency,
)
from releasegraph.risk_engine import blast_radius, calculate_release_risk


class CopilotTools:
    def __init__(self, db: Session, project_id: int):
        self.db = db
        self.project_id = project_id

    def get_project(self) -> dict[str, Any]:
        p = self.db.get(Project, self.project_id)
        if not p:
            return {"error": "project_not_found"}
        return {"id": p.id, "slug": p.slug, "name": p.name, "description": p.description}

    def get_release(self, release_id: int) -> dict[str, Any]:
        r = self.db.get(Release, release_id)
        if not r or r.project_id != self.project_id:
            return {"error": "release_not_found"}
        return self._release_detail(r)

    def get_latest_release(self) -> dict[str, Any]:
        project = self.db.get(Project, self.project_id)
        r = None
        if project and project.production_release_id:
            r = self.db.get(Release, project.production_release_id)
        if not r:
            r = self.db.scalars(
                select(Release)
                .where(Release.project_id == self.project_id, Release.status == ReleaseStatus.DEPLOYED)
                .order_by(Release.created_at.desc())
                .limit(1)
            ).first()
        if not r:
            return {"error": "no_releases"}
        return self._release_detail(r)

    def _release_detail(self, r: Release) -> dict[str, Any]:
        commits = self.db.scalars(
            select(Commit)
            .join(ReleaseCommit, ReleaseCommit.commit_id == Commit.id)
            .where(ReleaseCommit.release_id == r.id)
        ).all()
        prs = self.db.scalars(
            select(PullRequest)
            .join(ReleasePullRequest, ReleasePullRequest.pull_request_id == PullRequest.id)
            .where(ReleasePullRequest.release_id == r.id)
        ).all()
        svcs = self.db.scalars(
            select(Service)
            .join(ReleaseService, ReleaseService.service_id == Service.id)
            .where(ReleaseService.release_id == r.id)
        ).all()
        deps = self.db.scalars(
            select(Deployment).where(Deployment.release_id == r.id).order_by(Deployment.started_at.desc())
        ).all()
        return {
            "id": r.id,
            "version": r.version,
            "status": r.status.value,
            "risk_level": r.risk_level,
            "risk_score": r.risk_score,
            "summary": r.summary,
            "commits": [{"sha": c.sha[:7], "message": c.message, "author": c.author} for c in commits],
            "pull_requests": [{"number": pr.number, "title": pr.title} for pr in prs],
            "services": [s.name for s in svcs],
            "deployments": [
                {"id": d.id, "status": d.status.value, "started_at": d.started_at.isoformat()}
                for d in deps
            ],
        }

    def get_service_dependencies(self, service_name: str | None = None) -> dict[str, Any]:
        svcs = self.db.scalars(
            select(Service).where(Service.project_id == self.project_id)
        ).all()
        by_id = {s.id: s for s in svcs}
        deps = self.db.scalars(
            select(ServiceDependency).where(ServiceDependency.project_id == self.project_id)
        ).all()
        edges = [
            {"from": by_id[d.from_service_id].name, "to": by_id[d.to_service_id].name}
            for d in deps
            if d.from_service_id in by_id and d.to_service_id in by_id
        ]
        if service_name:
            target = next((s for s in svcs if s.name == service_name), None)
            if not target:
                return {"error": "service_not_found", "edges": edges}
            dep_pairs = [(d.from_service_id, d.to_service_id) for d in deps]
            affected = blast_radius({target.id}, dep_pairs)
            return {
                "service": service_name,
                "dependents": [by_id[i].name for i in affected if i != target.id],
                "edges": edges,
            }
        return {"edges": edges}

    def calculate_blast_radius(self, service_names: list[str]) -> dict[str, Any]:
        svcs = self.db.scalars(
            select(Service).where(Service.project_id == self.project_id)
        ).all()
        by_name = {s.name: s.id for s in svcs}
        ids = {by_name[n] for n in service_names if n in by_name}
        if not ids:
            return {"error": "no_matching_services"}
        deps = self.db.scalars(
            select(ServiceDependency).where(ServiceDependency.project_id == self.project_id)
        ).all()
        dep_pairs = [(d.from_service_id, d.to_service_id) for d in deps]
        affected_ids = blast_radius(ids, dep_pairs)
        return {
            "seed_services": service_names,
            "affected_services": [s.name for s in svcs if s.id in affected_ids],
        }

    def get_incidents(self, incident_id: int | None = None) -> dict[str, Any]:
        if incident_id:
            inc = self.db.get(Incident, incident_id)
            if not inc or inc.project_id != self.project_id:
                return {"error": "incident_not_found"}
            events = self.db.scalars(
                select(IncidentEvent)
                .where(IncidentEvent.incident_id == inc.id)
                .order_by(IncidentEvent.timestamp)
            ).all()
            svc = self.db.get(Service, inc.service_id) if inc.service_id else None
            return {
                "id": inc.id,
                "title": inc.title,
                "status": inc.status.value,
                "service": svc.name if svc else None,
                "release_id": inc.release_id,
                "timeline": [
                    {"time": e.timestamp.isoformat(), "type": e.event_type, "message": e.message}
                    for e in events
                ],
            }
        incs = self.db.scalars(
            select(Incident)
            .where(Incident.project_id == self.project_id)
            .order_by(Incident.created_at.desc())
            .limit(20)
        ).all()
        return {
            "incidents": [
                {"id": i.id, "title": i.title, "status": i.status.value, "severity": i.severity}
                for i in incs
            ]
        }

    def get_release_graph(self) -> dict[str, Any]:
        from releasegraph.graph_insight import build_project_graph

        return build_project_graph(self.db, self.project_id)

    def analyze_errors(self, incident_id: int | None = None, workspace: str | None = None) -> dict[str, Any]:
        from releasegraph.analysis import analyze_project

        return analyze_project(
            self.db,
            self.project_id,
            workspace=workspace,
            incident_id=incident_id,
            use_llm=False,
        )

    def list_fix_prs(self) -> dict[str, Any]:
        from releasegraph.models import FixProposal
        from releasegraph.proposals import serialize_proposal

        rows = self.db.scalars(
            select(FixProposal).where(FixProposal.project_id == self.project_id).order_by(FixProposal.number.desc())
        ).all()
        return {"in_app": True, "count": len(rows), "pull_requests": [serialize_proposal(self.db, p) for p in rows]}

    def run_tool(self, name: str, arguments: dict[str, Any]) -> str:
        mapping = {
            "get_project": self.get_project,
            "get_release": self.get_release,
            "get_latest_release": self.get_latest_release,
            "get_service_dependencies": self.get_service_dependencies,
            "calculate_blast_radius": self.calculate_blast_radius,
            "get_incidents": self.get_incidents,
            "get_release_graph": self.get_release_graph,
            "analyze_errors": self.analyze_errors,
            "list_fix_prs": self.list_fix_prs,
        }
        fn = mapping.get(name)
        if fn is None:
            return json.dumps({"error": f"unknown_tool:{name}"})
        return json.dumps(fn(**arguments), default=str)
