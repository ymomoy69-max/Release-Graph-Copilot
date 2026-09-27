"""JSON-backed zero-dependency in-memory persistence for ReleaseGraph.

Replaces the entire SQLAlchemy + DB session layer. All reads come from an
in-memory dict of lists of dicts; every write flushes the whole structure to
disk atomically via ``os.replace``. Password hashes in the seeded store are
``sha256(plaintext)`` hex digests *not* bcrypt — that is intentional and a
documented trade-off to keep the boot path free of third-party deps.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import uuid as _uuid
from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from releasegraph.models import (
    DeploymentStatus,
    FixProposalStatus,
    IncidentStatus,
    ReleaseStatus,
    UserRole,
)

_log = logging.getLogger(__name__)

_LOCK = threading.RLock()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


DEFAULT_STORE_PATH = "./data/releasegraph-store.json"


def _store_path_from_env() -> Path:
    raw = os.getenv("RELEASEGRAPH_STORE_PATH") or DEFAULT_STORE_PATH
    return Path(raw).expanduser().resolve()


class Store:
    """JSON-file-backed dict store.

    The in-memory layout::

        _state = {
            "organizations": [Organization dict, ...],
            "users": [User dict, ...],
            "projects": [Project dict, ...],
            "repositories": [..],
            "services": [..],
            "service_dependencies": [..],
            "environments": [..],
            "commits": [..],
            "pull_requests": [..],
            "builds": [..],
            "test_runs": [..],
            "artifacts": [..],
            "releases": [..],
            "release_commits": [..],
            "release_pull_requests": [..],
            "release_services": [..],
            "deployments": [..],
            "risk_factors": [..],
            "incidents": [..],
            "incident_events": [..],
            "audit_events": [..],
            "fix_proposals": [..],
            "analyses": [..],
        }

    Foreign keys in the ORM layer (``organization_id``, ``project_id``, etc.)
    remain in the dict shape so API response code continues to work with the
    same fields.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _store_path_from_env()
        self._state: dict[str, list[dict[str, Any]]] = {}
        self._loaded = False
        self._seeding = False
        self._ensure_parent_dir()

    # ------------------------------------------------------------------
    # Persistence primitives
    # ------------------------------------------------------------------
    def _ensure_parent_dir(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    def ensure_seeded(self) -> None:
        """Idempotent: load from disk or seed fresh state + persist."""
        with _LOCK:
            if self._loaded or self._seeding:
                return
            if self.path.exists() and self.path.stat().st_size > 0:
                try:
                    self._state = json.loads(self.path.read_text(encoding="utf-8"))
                    self._loaded = True
                    _log.info("Store loaded from disk: %s (users=%d, projects=%d, releases=%d)",
                              self.path,
                              len(self._state.get("users", [])),
                              len(self._state.get("projects", [])),
                              len(self._state.get("releases", [])))
                    return
                except (OSError, json.JSONDecodeError) as exc:
                    _log.warning("Could not read store file %s, re-seeding: %s", self.path, exc)
            self._seeding = True
            try:
                self._seed_defaults()
                self._save_locked()
            finally:
                self._seeding = False
            self._loaded = True
            _log.info("Fresh store seeded at %s (users=%d, projects=%d, releases=%d)",
                      self.path,
                      len(self._state["users"]),
                      len(self._state["projects"]),
                      len(self._state["releases"]))

    def _save_locked(self) -> None:
        self._ensure_parent_dir()
        fd, tmpname = tempfile.mkstemp(prefix=".rgc-store-", dir=str(self.path.parent), suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._state, fh, indent=2, sort_keys=True, default=str)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmpname, self.path)
        except Exception:
            try:
                os.unlink(tmpname)
            except OSError:
                pass
            raise

    def save(self) -> None:
        with _LOCK:
            self._save_locked()

    # ------------------------------------------------------------------
    # Basic CRUD helpers
    # ------------------------------------------------------------------
    def _collection(self, name: str) -> list[dict[str, Any]]:
        self.ensure_seeded()
        if name not in self._state:
            self._state[name] = []
        return self._state[name]

    def _next_id(self, name: str) -> int:
        col = self._state.get(name, [])
        return 1 if not col else max(int(r.get("id") or 0) for r in col) + 1

    def find_all(self, name: str, **filters: Any) -> list[dict[str, Any]]:
        col = self._collection(name)
        if not filters:
            return list(col)
        out: list[dict[str, Any]] = []
        for row in col:
            if all(row.get(k) == v for k, v in filters.items()):
                out.append(row)
        return out

    def find_one(self, name: str, **filters: Any) -> dict[str, Any] | None:
        col = self._collection(name)
        for row in col:
            if all(row.get(k) == v for k, v in filters.items()):
                return row
        return None

    def get(self, name: str, row_id: int) -> dict[str, Any] | None:
        return self.find_one(name, id=int(row_id))

    def insert(self, name: str, row: dict[str, Any], *, persist: bool = True) -> dict[str, Any]:
        with _LOCK:
            if not self._seeding:
                self.ensure_seeded()
            if "id" not in row or not row["id"]:
                row["id"] = self._next_id(name)
            self._state.setdefault(name, []).append(row)
            if persist and not self._seeding:
                self._save_locked()
            return row

    def update(self, name: str, row_id: int, changes: dict[str, Any], *, persist: bool = True) -> dict[str, Any] | None:
        with _LOCK:
            if not self._seeding:
                self.ensure_seeded()
            row = self.get(name, row_id)
            if row is None:
                return None
            row.update({k: v for k, v in changes.items() if v is not None or k in changes})
            if persist and not self._seeding:
                self._save_locked()
            return row

    def delete(self, name: str, row_id: int, *, persist: bool = True) -> bool:
        with _LOCK:
            if not self._seeding:
                self.ensure_seeded()
            col = self._collection(name)
            before = len(col)
            self._state[name] = [r for r in col if int(r.get("id") or 0) != int(row_id)]
            if persist and not self._seeding:
                self._save_locked()
            return len(self._state[name]) < before

    # ------------------------------------------------------------------
    # Seed data: roughly match old fixtures/demo for UX richness
    # ------------------------------------------------------------------
    def _seed_defaults(self) -> None:
        now = _utcnow_iso()
        self._state = {k: [] for k in [
            "organizations", "users", "projects", "repositories", "services",
            "service_dependencies", "environments", "commits", "pull_requests",
            "builds", "test_runs", "artifacts", "releases", "release_commits",
            "release_pull_requests", "release_services", "deployments",
            "risk_factors", "incidents", "incident_events", "audit_events",
            "fix_proposals", "analyses",
        ]}

        # ---- Organization 1: Acme Corp -------------------------------------------------
        org = {"id": 1, "slug": "acme", "name": "Acme Corp", "created_at": now}
        self._state["organizations"].append(org)

        # ---- 5 demo users ------------------------------------------------------------
        demo_users_raw: list[tuple[int, str, str, str, UserRole]] = [
            (1, "admin@acme.demo", "Ada Lovelace", "admin123!", UserRole.ADMIN),
            (2, "rm@acme.demo", "Grace Hopper", "release123", UserRole.RELEASE_MANAGER),
            (3, "eng@acme.demo", "Linus Torvalds", "engineer123", UserRole.ENGINEER),
            (4, "qa@acme.demo", "Margaret Hamilton", "qa12345", UserRole.ENGINEER),
            (5, "viewer@acme.demo", "Alan Turing", "viewer123", UserRole.VIEWER),
        ]
        for uid, email, full, pwd, role in demo_users_raw:
            self._state["users"].append({
                "id": uid,
                "email": email,
                "full_name": full,
                "hashed_password": _sha256hex(pwd),
                "role": role.value,
                "organization_id": org["id"],
                "created_at": now,
            })

        # ---- Environments ------------------------------------------------------------
        for env_id, slug, name in [(1, "staging", "Staging"), (2, "production", "Production")]:
            self._state["environments"].append({"id": env_id, "project_id": 1, "slug": slug, "name": name})
            self._state["environments"].append({"id": env_id + 2, "project_id": 2, "slug": slug, "name": name})

        # ---- 2 seeded projects -------------------------------------------------------
        p1 = {
            "id": 1,
            "organization_id": org["id"],
            "slug": "ecommerce",
            "name": "E-commerce Platform",
            "description": "Multi-tenant storefront, payment, and order management. "
                           "High-criticality release path with gated readiness checks.",
            "workspace_path": "",
            "org_config_path": "",
            "readiness_presets_json": json.dumps([
                {"name": "Smoke suite", "type": "tests", "blocking": True, "description": "Must have >95% pass rate"},
                {"name": "Deployment readiness", "type": "manual", "blocking": True, "description": "Release Manager sign-off"},
                {"name": "Security scan", "type": "security", "blocking": True, "description": "Zero critical vulnerabilities"},
                {"name": "Performance baseline", "type": "perf", "blocking": False, "description": "<5% latency regression"},
            ]),
            "production_release_id": 3,
            "workspace_synced_at": now,
            "created_at": now,
        }
        p2 = {
            "id": 2,
            "organization_id": org["id"],
            "slug": "streaming",
            "name": "Video Streaming Platform",
            "description": "Low-latency HLS streaming + viewer analytics services.",
            "workspace_path": "",
            "org_config_path": "",
            "readiness_presets_json": json.dumps([
                {"name": "Playback smoke", "type": "tests", "blocking": True, "description": "End-to-end playback successful"},
                {"name": "Ingest capacity", "type": "perf", "blocking": False, "description": "10% headroom on encoder fleet"},
            ]),
            "production_release_id": None,
            "workspace_synced_at": None,
            "created_at": now,
        }
        self._state["projects"].extend([p1, p2])

        # ---- Per-project: repositories, services, service dependencies (graph) --------
        def _seed_project_entities(pid: int, svc_names: list[str], deps: list[tuple[str, str]]) -> None:
            repo_id = self._next_id("repositories")
            self.insert("repositories", {
                "id": repo_id, "project_id": pid,
                "name": f"{('ecommerce' if pid == 1 else 'streaming')}-mono",
                "default_branch": "main", "url": "",
            }, persist=False)
            svc_ids: dict[str, int] = {}
            for idx, s in enumerate(svc_names, start=1):
                criticality = "high" if idx <= 3 else "medium" if idx <= 7 else "low"
                sid = self._next_id("services")
                svc_ids[s] = sid
                self.insert("services", {
                    "id": sid, "project_id": pid, "name": s,
                    "criticality": criticality,
                    "repository_id": repo_id,
                    "source_path": f"services/{s}",
                }, persist=False)
            for a, b in deps:
                self.insert("service_dependencies", {
                    "id": self._next_id("service_dependencies"),
                    "project_id": pid,
                    "from_service_id": svc_ids[a],
                    "to_service_id": svc_ids[b],
                }, persist=False)

        ecom_services = [
            "api-gateway", "auth-service", "checkout-service",
            "order-service", "payment-service", "catalog-service",
            "search-service", "user-profile-service", "notifications",
            "recommendations", "inventory-service",
        ]
        ecom_deps = [
            ("api-gateway", "auth-service"),
            ("api-gateway", "checkout-service"),
            ("api-gateway", "catalog-service"),
            ("api-gateway", "search-service"),
            ("checkout-service", "order-service"),
            ("checkout-service", "payment-service"),
            ("checkout-service", "inventory-service"),
            ("order-service", "notifications"),
            ("order-service", "user-profile-service"),
            ("catalog-service", "recommendations"),
            ("search-service", "catalog-service"),
            ("payment-service", "notifications"),
            ("recommendations", "user-profile-service"),
            ("inventory-service", "catalog-service"),
            ("api-gateway", "user-profile-service"),
        ]
        _seed_project_entities(p1["id"], ecom_services, ecom_deps)

        stream_services = [
            "edge-cdn", "ingest-service", "transcoder-fleet",
            "manifest-service", "drm-license", "viewer-analytics",
            "ad-insertion", "stream-gateway", "playback-sessions",
            "live-monitor",
        ]
        stream_deps = [
            ("stream-gateway", "ingest-service"),
            ("stream-gateway", "manifest-service"),
            ("stream-gateway", "drm-license"),
            ("stream-gateway", "edge-cdn"),
            ("ingest-service", "transcoder-fleet"),
            ("transcoder-fleet", "edge-cdn"),
            ("manifest-service", "drm-license"),
            ("manifest-service", "transcoder-fleet"),
            ("playback-sessions", "drm-license"),
            ("playback-sessions", "viewer-analytics"),
            ("playback-sessions", "ad-insertion"),
            ("viewer-analytics", "live-monitor"),
            ("ad-insertion", "viewer-analytics"),
            ("edge-cdn", "playback-sessions"),
            ("stream-gateway", "viewer-analytics"),
        ]
        _seed_project_entities(p2["id"], stream_services, stream_deps)

        # ---- Commits, PRs, builds ----------------------------------------------------
        authors = ["Ada <ada@acme.demo>", "Grace <grace@acme.demo>",
                   "Linus <linus@acme.demo>", "Margaret <margaret@acme.demo>"]
        for pid in (p1["id"], p2["id"]):
            repo = self.find_one("repositories", project_id=pid)
            rid = repo["id"] if repo else 1
            for ci in range(12):
                cid = self._next_id("commits")
                sha = hashlib.sha1(f"{pid}-{ci}-seed".encode()).hexdigest()[:40]
                self.insert("commits", {
                    "id": cid, "repository_id": rid,
                    "sha": sha,
                    "author": authors[ci % len(authors)],
                    "message": f"feat(svc-{pid}-{ci}): seed change #{ci}",
                    "committed_at": now,
                }, persist=False)
                if ci % 2 == 0:
                    prid = self._next_id("pull_requests")
                    self.insert("pull_requests", {
                        "id": prid, "repository_id": rid,
                        "number": 100 + ci,
                        "title": f"PR for service-{pid}-{ci} change",
                        "author": authors[(ci + 1) % len(authors)],
                        "state": "merged",
                        "merged_at": now,
                    }, persist=False)
                    # tie half the PRs to commits via release_commits tie-in later

            # Builds & test runs & artifacts
            for bi in range(3):
                bid = self._next_id("builds")
                self.insert("builds", {
                    "id": bid, "project_id": pid, "release_id": None,
                    "status": "success" if bi < 2 else "failed",
                    "started_at": now,
                    "completed_at": now,
                    "duration_seconds": 142.7 + bi,
                }, persist=False)
                self.insert("test_runs", {
                    "id": self._next_id("test_runs"), "build_id": bid,
                    "suite": "integration", "status": "passed" if bi < 2 else "failed",
                    "passed": 318, "failed": 0 if bi < 2 else 2,
                }, persist=False)
                self.insert("artifacts", {
                    "id": self._next_id("artifacts"), "build_id": bid,
                    "name": "app-image", "version": f"1.0.{bi}",
                    "uri": f"oci://registry.local/{('ecom' if pid == 1 else 'stream')}:1.0.{bi}",
                }, persist=False)

        # ---- Releases (per project: 4 each, progressive lifecycle) --------------------
        def _seed_releases(pid: int, env_prod: int, env_stg: int, prod_rel_ver: str | None) -> None:
            services = self.find_all("services", project_id=pid)
            svc_ids = [s["id"] for s in services]
            commits = self.find_all("commits")[:8]
            prs = self.find_all("pull_requests")[:6]

            lifecycle = [
                ("1.0.0", ReleaseStatus.DEPLOYED, "Initial production release", "HIGH", 6.5, True),
                ("1.1.0", ReleaseStatus.DEPLOYED, "Bug fixes and catalog indexing improvements", "MEDIUM", 3.4, True),
                ("1.2.0", ReleaseStatus.DEPLOYED, "Inventory service v2 rollout", "LOW", 1.2, True),
                ("1.3.0", ReleaseStatus.READY, "Checkout SCA auth flow + performance tuning", "MEDIUM", 3.9, True),
            ]
            for idx, (ver, st, summ, risk_l, risk_s, rb) in enumerate(lifecycle):
                is_prod = (prod_rel_ver == ver)
                relid = self._next_id("releases")
                basel = None if idx == 0 else max(r["id"] for r in self._state["releases"] if r["project_id"] == pid)
                self.insert("releases", {
                    "id": relid, "project_id": pid, "version": ver,
                    "status": st.value, "environment_id": env_prod if is_prod else env_stg,
                    "summary": summ, "created_at": now,
                    "risk_level": risk_l, "risk_score": risk_s,
                    "rollback_available": rb,
                    "baseline_release_id": basel,
                }, persist=False)
                if is_prod:
                    # update project.production_release_id
                    for proj in self._state["projects"]:
                        if proj["id"] == pid:
                            proj["production_release_id"] = relid
                            break
                # Attach services
                pick_count = min(5 + idx, len(svc_ids))
                for sid in svc_ids[:pick_count]:
                    self.insert("release_services", {
                        "id": self._next_id("release_services"),
                        "release_id": relid, "service_id": sid,
                    }, persist=False)
                # Attach commits
                for i, c in enumerate(commits[:2 + idx]):
                    self.insert("release_commits", {
                        "id": self._next_id("release_commits"),
                        "release_id": relid, "commit_id": c["id"],
                    }, persist=False)
                # Attach PRs
                for pr in prs[:1 + (idx // 2)]:
                    self.insert("release_pull_requests", {
                        "id": self._next_id("release_pull_requests"),
                        "release_id": relid, "pull_request_id": pr["id"],
                    }, persist=False)
                # Risk factors
                for rfi, (fac, wt, det) in enumerate([
                    ("database_migration", 2.0, "Index rebuild on orders table"),
                    ("core_service_change", 1.5, "Checkout service touched"),
                    ("cross_service_dependency", 1.0, "Blast radius: 4 services"),
                ]):
                    self.insert("risk_factors", {
                        "id": self._next_id("risk_factors"),
                        "release_id": relid,
                        "factor": fac, "weight": wt, "detail": det,
                    }, persist=False)
                # Deployment records
                dep_st = DeploymentStatus.SUCCESS if st in {ReleaseStatus.DEPLOYED, ReleaseStatus.FAILED, ReleaseStatus.ROLLED_BACK} else DeploymentStatus.PENDING
                if st in {ReleaseStatus.DEPLOYED, ReleaseStatus.FAILED, ReleaseStatus.ROLLED_BACK}:
                    self.insert("deployments", {
                        "id": self._next_id("deployments"),
                        "release_id": relid,
                        "environment_id": env_prod if is_prod else env_stg,
                        "status": dep_st.value,
                        "started_at": now,
                        "completed_at": now,
                        "duration_seconds": 215.3 + idx * 12,
                        "initiated_by_user_id": 2,
                    }, persist=False)

        # Environments per project already created with ids 1,2 for pid=1; 3,4 for pid=2
        _seed_releases(p1["id"], env_prod=2, env_stg=1, prod_rel_ver="1.2.0")
        _seed_releases(p2["id"], env_prod=4, env_stg=3, prod_rel_ver=None)

        # ---- Incidents per project ---------------------------------------------------
        def _seed_incidents(pid: int, titles: list[tuple[str, IncidentStatus, str, int]]) -> None:
            services = self.find_all("services", project_id=pid)
            for title, st, sev, service_idx in titles:
                iid = self._next_id("incidents")
                sid = services[service_idx % len(services)]["id"]
                self.insert("incidents", {
                    "id": iid, "project_id": pid,
                    "title": title,
                    "status": st.value,
                    "severity": sev,
                    "service_id": sid,
                    "release_id": None,
                    "deployment_id": None,
                    "created_at": now,
                    "resolved_at": now if st == IncidentStatus.RESOLVED else None,
                    "resolution_notes": (
                        "Rolled back catalog indexer to v1.1.4."
                        if st == IncidentStatus.RESOLVED else ""
                    ),
                }, persist=False)
                # Add event timeline
                for evtype, msg in [
                    ("created", f"Incident opened: {title}"),
                    ("acknowledged", "On-call engineer acknowledged pager"),
                    ("investigating", "Correlated with recent checkout-service deploy"),
                ]:
                    self.insert("incident_events", {
                        "id": self._next_id("incident_events"),
                        "incident_id": iid,
                        "timestamp": now,
                        "event_type": evtype,
                        "message": msg,
                        "actor": "system",
                    }, persist=False)
                if st == IncidentStatus.RESOLVED:
                    self.insert("incident_events", {
                        "id": self._next_id("incident_events"),
                        "incident_id": iid,
                        "timestamp": now,
                        "event_type": "resolved",
                        "message": "Rollback applied, error rate back to baseline",
                        "actor": "Grace <grace@acme.demo>",
                    }, persist=False)

        _seed_incidents(p1["id"], [
            ("502 spike on checkout during EU peak — payment provider timeouts", IncidentStatus.OPEN, "high", 2),
            ("Catalog search returning stale results — indexer lag", IncidentStatus.RESOLVED, "medium", 6),
            ("Inventory count drift in EU-West region", IncidentStatus.INVESTIGATING, "medium", 10),
        ])
        _seed_incidents(p2["id"], [
            ("Transcoder encoder stalls on 4K live ingest", IncidentStatus.INVESTIGATING, "high", 2),
            ("Viewer analytics pipeline lag > 30m", IncidentStatus.MITIGATED, "medium", 5),
        ])

        # ---- Audit events ------------------------------------------------------------
        for action, et, eid, actor in [
            ("release.deployed", "release", "3", 2),
            ("release.ready_marked", "release", "4", 2),
            ("incident.created", "incident", "1", 3),
            ("incident.resolved", "incident", "2", 2),
            ("project.created", "project", "1", 1),
            ("project.created", "project", "2", 1),
            ("user.logged_in", "user", "1", 1),
            ("user.logged_in", "user", "2", 2),
            ("copilot.asked", "project", "1", 2),
        ]:
            self.insert("audit_events", {
                "id": self._next_id("audit_events"),
                "organization_id": org["id"],
                "user_id": actor,
                "timestamp": now,
                "action": action,
                "entity_type": et,
                "entity_id": str(eid),
                "previous_state": "",
                "new_state": "",
                "ai_generated": False,
            }, persist=False)

        # ---- Fix proposals -----------------------------------------------------------
        self.insert("fix_proposals", {
            "id": self._next_id("fix_proposals"),
            "incident_id": self._state["incidents"][0]["id"],
            "status": FixProposalStatus.OPEN.value,
            "title": "Add payment-provider circuit breaker + fallback to async queue",
            "description": "Prevent 502 spike by wrapping calls to the PSP in a circuit breaker and queueing retry.",
            "ai_generated": False,
            "pr_url": "",
            "created_at": now,
            "closed_at": None,
        }, persist=False)

        # Persist once (already wrapped by caller under lock + save_locked)

    # ------------------------------------------------------------------
    # Helpers for endpoints used frequently
    # ------------------------------------------------------------------
    def project_for_user(self, user: dict[str, Any], project_id: int) -> dict[str, Any]:
        p = self.get("projects", project_id)
        if not p or int(p.get("organization_id") or 0) != int(user.get("organization_id") or 0):
            raise ValueError("project_not_found")
        return p

    def release_services(self, release_id: int) -> list[str]:
        svc_links = self.find_all("release_services", release_id=int(release_id))
        names: list[str] = []
        for lnk in svc_links:
            # Seed writes service_id; tolerate old to_service_id shape if any present
            sid = lnk.get("service_id") or lnk.get("to_service_id")
            if not sid:
                continue
            svc = self.get("services", int(sid))
            if svc:
                names.append(svc["name"])
        return names


# Module-level singleton, same idea as the old engine/SessionLocal pattern
_DEFAULT_STORE: Store | None = None


def get_default_store() -> Store:
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = Store()
        _DEFAULT_STORE.ensure_seeded()
    return _DEFAULT_STORE


def get_store() -> Generator[Store, None, None]:
    """FastAPI Depends-compatible generator yielding the singleton store.

    Unlike DB sessions there is nothing to open/close — writes go through
    atomic json save whenever a mutation occurs.
    """
    yield get_default_store()
