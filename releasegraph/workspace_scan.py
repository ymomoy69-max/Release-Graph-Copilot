"""Discover microservices and their connections in any workspace folder."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from releasegraph.models import Project, Repository, Service, ServiceDependency

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    "dist",
    "build",
    ".cursor",
    "egg-info",
    "coverage",
}

COMPOSE_NAMES = (
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    "docker-compose.demo.yml",
    "docker-compose.demo.yaml",
)

ENV_URL_RE = re.compile(r"\b([A-Z][A-Z0-9_]*(?:SERVICE)?_URL)\b")
HOST_RE = re.compile(r"https?://([a-zA-Z0-9][a-zA-Z0-9._-]*)")
FASTAPI_TITLE_RE = re.compile(r'FastAPI\(\s*title\s*=\s*["\']([^"\']+)')
SERVICE_NAME_ASSIGN_RE = re.compile(r'SERVICE_NAME\s*=\s*["\']([^"\']+)')
SECRET_RE = re.compile(
    r"""(?:password|secret|api_key|apikey|token)\s*=\s*['"][^'"]{6,}['"]""",
    re.IGNORECASE,
)
BARE_EXCEPT_RE = re.compile(r"except(\s+\w+)?\s*:\s*(pass|continue)\b")
HTTPX_NO_TIMEOUT_RE = re.compile(r"httpx\.Client\(\s*\)")
REQUESTS_NO_TIMEOUT_RE = re.compile(r"requests\.(get|post|put|delete|patch)\([^)]*\)")
SQL_FSTRING_RE = re.compile(r"""(?:execute|executemany)\(\s*f['"]""")

HIGH_HINTS = ("payment", "billing", "auth", "gateway", "checkout", "order", "identity")
LOW_HINTS = ("notification", "email", "worker", "job", "cron", "mail")

CODE_SUFFIXES = {".py", ".ts", ".js", ".go", ".java", ".rb"}


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "workspace"


def _env_to_service(var: str) -> str:
    base = var
    if base.endswith("_SERVICE_URL"):
        base = base[: -len("_SERVICE_URL")]
        return base.lower().replace("_", "-") + "-service"
    if base.endswith("_URL"):
        base = base[: -len("_URL")]
        return base.lower().replace("_", "-")
    return base.lower().replace("_", "-")


def _criticality(name: str) -> str:
    n = name.lower()
    if any(h in n for h in HIGH_HINTS):
        return "high"
    if any(h in n for h in LOW_HINTS):
        return "low"
    return "medium"


def _iter_code_files(root: Path, limit: int = 400) -> list[Path]:
    out: list[Path] = []
    for path in root.rglob("*"):
        if len(out) >= limit:
            break
        if not path.is_file() or path.suffix not in CODE_SUFFIXES:
            continue
        if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in path.parts):
            continue
        out.append(path)
    return out


def _parse_compose(path: Path) -> tuple[dict[str, dict[str, Any]], list[tuple[str, str, str]]]:
    services: dict[str, dict[str, Any]] = {}
    edges: list[tuple[str, str, str]] = []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return services, edges
    raw = data.get("services") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return services, edges
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            spec = {}
        services[name] = {
            "name": name,
            "path": str(path.parent),
            "source": "compose",
            "compose_file": str(path),
            "criticality": _criticality(name),
        }
        depends = spec.get("depends_on") or []
        if isinstance(depends, dict):
            depends = list(depends.keys())
        for dep in depends:
            if isinstance(dep, str):
                edges.append((name, dep, f"{path.name}:depends_on"))
        env = spec.get("environment") or {}
        if isinstance(env, list):
            parsed: dict[str, str] = {}
            for item in env:
                if isinstance(item, str) and "=" in item:
                    k, v = item.split("=", 1)
                    parsed[k] = v
            env = parsed
        if isinstance(env, dict):
            for key, val in env.items():
                if not isinstance(key, str):
                    continue
                if key.endswith("_URL") or key.endswith("_SERVICE_URL"):
                    target = _env_to_service(key)
                    if isinstance(val, str):
                        host = HOST_RE.search(val)
                        if host:
                            target = host.group(1).split(".")[0]
                    if target and target != name:
                        edges.append((name, target, f"{key}={val}"))
    return services, edges


def _discover_app_dirs(root: Path) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for app in list(root.rglob("app.py")) + list(root.rglob("main.py")):
        if any(part in SKIP_DIRS for part in app.parts):
            continue
        try:
            text = app.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "FastAPI(" not in text and "Flask(" not in text:
            continue
        name = None
        m = FASTAPI_TITLE_RE.search(text) or SERVICE_NAME_ASSIGN_RE.search(text)
        if m:
            name = m.group(1)
        if not name:
            name = app.parent.name
            if name in {"services", "src", "app"}:
                name = app.parent.parent.name
        found[name] = {
            "name": name,
            "path": str(app.parent),
            "source": "fastapi",
            "entry": str(app),
            "criticality": _criticality(name),
        }
    return found


def _edges_from_code(root: Path, services: dict[str, dict[str, Any]]) -> list[tuple[str, str, str]]:
    edges: list[tuple[str, str, str]] = []
    known_l = {k.lower(): k for k in services}
    for path in _iter_code_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        owner = None
        path_s = str(path)
        for name, meta in services.items():
            loc = str(meta.get("path") or meta.get("entry") or "")
            if loc and (path_s.startswith(loc) or loc in path_s):
                owner = name
                break
        if not owner:
            for part in path.parts[::-1]:
                cand = part.lower().replace("_", "-")
                if cand in known_l:
                    owner = known_l[cand]
                    break
                for k, orig in known_l.items():
                    stem = k.replace("-service", "")
                    if cand == stem:
                        owner = orig
                        break
                if owner:
                    break
        if not owner:
            continue
        for var in ENV_URL_RE.findall(text):
            target = _env_to_service(var)
            if target in known_l and known_l[target] != owner:
                edges.append((owner, known_l[target], f"{path.name}:{var}"))
        for host in HOST_RE.findall(text):
            h = host.split(".")[0].lower()
            if h in known_l and known_l[h] != owner:
                edges.append((owner, known_l[h], f"{path.name}:http://{host}"))
    return edges


def scan_code_issues(root: Path, services: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Lightweight static issues used by the analysis layer."""
    by_path = {s["name"]: s.get("path") or s.get("entry") for s in services}
    issues: list[dict[str, Any]] = []
    for path in _iter_code_files(root, limit=250):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(path)
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            pass
        service = None
        for name, sp in by_path.items():
            if sp and str(sp) in str(path):
                service = name
                break
        lines = text.splitlines()
        for i, line in enumerate(lines, 1):
            if SECRET_RE.search(line) and "getenv" not in line and "os.environ" not in line:
                issues.append(_issue(rel, i, service, line, "hardcoded_secret"))
            if BARE_EXCEPT_RE.search(line):
                issues.append(_issue(rel, i, service, line, "swallowed_exception"))
            if HTTPX_NO_TIMEOUT_RE.search(line):
                issues.append(_issue(rel, i, service, line, "http_no_timeout"))
            if SQL_FSTRING_RE.search(line):
                issues.append(_issue(rel, i, service, line, "sql_fstring"))
        for m in REQUESTS_NO_TIMEOUT_RE.finditer(text):
            snippet = m.group(0)
            if "timeout" in snippet:
                continue
            line_no = text[: m.start()].count("\n") + 1
            issues.append(_issue(rel, line_no, service, snippet, "http_no_timeout"))
    return issues


def _issue(file: str, line: int, service: str | None, snippet: str, code: str) -> dict[str, Any]:
    return {
        "file": file,
        "line": line,
        "service": service,
        "code": code,
        "snippet": snippet.strip()[:240],
    }


def discover_repo_folders(workspace: str) -> list[str]:
    root = Path(workspace)
    if not root.is_dir():
        return []
    names: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith(".") or child.name in SKIP_DIRS:
            continue
        names.append(child.name)
    return names


def scan_workspace(workspace: str) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        return {
            "workspace": str(root),
            "name": root.name,
            "error": "workspace_not_found",
            "services": [],
            "dependencies": [],
            "issues": [],
            "repo_folders": [],
        }

    services: dict[str, dict[str, Any]] = {}
    edges: list[tuple[str, str, str]] = []

    compose_files: list[Path] = []
    for name in COMPOSE_NAMES:
        p = root / name
        if p.is_file():
            compose_files.append(p)
    for p in root.glob("docker-compose*.yml"):
        if p not in compose_files:
            compose_files.append(p)
    parent_demo = root.parent / "docker-compose.demo.yml"
    if not compose_files and parent_demo.is_file():
        compose_files.append(parent_demo)

    for cf in compose_files:
        svc, ed = _parse_compose(cf)
        services.update(svc)
        edges.extend(ed)

    for name, meta in _discover_app_dirs(root).items():
        if name not in services:
            services[name] = meta
        else:
            services[name].setdefault("entry", meta.get("entry"))
            services[name].setdefault("path", meta.get("path"))

    edges.extend(_edges_from_code(root, services))

    # Keep only edges whose endpoints exist (or create stub services for compose deps)
    for frm, to, _ev in edges:
        if to not in services and to not in {"db", "redis", "postgres", "cache", "mongo"}:
            services[to] = {
                "name": to,
                "path": str(root),
                "source": "inferred",
                "criticality": _criticality(to),
            }

    skip_infra = {"db", "redis", "postgres", "cache", "mongo", "zookeeper"}
    uniq_edges: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for frm, to, ev in edges:
        if frm in skip_infra or to in skip_infra or frm == to:
            continue
        if frm not in services or to not in services:
            continue
        key = (frm, to)
        if key in seen:
            continue
        seen.add(key)
        uniq_edges.append({"from": frm, "to": to, "evidence": ev})

    svc_list = [
        {
            "name": s["name"],
            "path": s.get("path") or s.get("entry") or str(root),
            "source": s.get("source", "scan"),
            "criticality": s.get("criticality", _criticality(s["name"])),
            "entry": s.get("entry"),
        }
        for s in services.values()
        if s["name"] not in skip_infra
    ]
    svc_list.sort(key=lambda s: s["name"])
    issues = scan_code_issues(root, svc_list)

    return {
        "workspace": str(root),
        "name": root.name,
        "services": svc_list,
        "dependencies": uniq_edges,
        "issues": issues,
        "repo_folders": discover_repo_folders(str(root)),
        "compose_files": [str(p) for p in compose_files],
    }


def persist_scan(db: Session, project: Project, scan: dict[str, Any]) -> dict[str, Any]:
    """Upsert services and replace dependency edges for a project."""
    project.workspace_path = scan.get("workspace") or project.workspace_path
    if scan.get("name") and (not project.description or project.description.startswith("Scanned")):
        project.description = f"Scanned workspace {scan['name']}"

    existing = {
        s.name: s
        for s in db.scalars(select(Service).where(Service.project_id == project.id)).all()
    }
    for meta in scan.get("services") or []:
        name = meta["name"]
        repo = db.scalar(
            select(Repository).where(Repository.project_id == project.id, Repository.name == name)
        )
        if not repo:
            repo = Repository(project_id=project.id, name=name, url=meta.get("path") or "")
            db.add(repo)
            db.flush()
        svc = existing.get(name)
        if not svc:
            svc = Service(
                project_id=project.id,
                name=name,
                criticality=meta.get("criticality") or "medium",
                repository_id=repo.id,
                source_path=meta.get("path") or "",
            )
            db.add(svc)
            db.flush()
            existing[name] = svc
        else:
            svc.criticality = meta.get("criticality") or svc.criticality
            svc.source_path = meta.get("path") or svc.source_path or ""
            svc.repository_id = svc.repository_id or repo.id

    deps = db.scalars(
        select(ServiceDependency).where(ServiceDependency.project_id == project.id)
    ).all()
    for d in deps:
        db.delete(d)
    db.flush()

    by_name = {
        s.name: s
        for s in db.scalars(select(Service).where(Service.project_id == project.id)).all()
    }
    created = 0
    for edge in scan.get("dependencies") or []:
        src = by_name.get(edge["from"])
        dst = by_name.get(edge["to"])
        if not src or not dst:
            continue
        db.add(
            ServiceDependency(
                project_id=project.id,
                from_service_id=src.id,
                to_service_id=dst.id,
            )
        )
        created += 1
    db.flush()
    return {
        "project_id": project.id,
        "services": len(by_name),
        "dependencies": created,
    }
