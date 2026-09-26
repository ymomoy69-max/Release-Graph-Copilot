"""
Plug-and-play SDK — scan any microservices folder. No login, no database.

    from releasegraph.sdk import analyze_workspace

    result = analyze_workspace("./checkout")
    print(result["summary"])
    for link in result["broken_links"]:
        print(f"{link['from']} → {link['to']}: {link['if_breaks']}")

Or from a shell:

    releasegraph-scan ./checkout
    releasegraph-scan ./checkout --json
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from releasegraph.insight_core import PLAIN, build_insight, plain_for
from releasegraph.workspace_scan import scan_workspace


def git_updates(workspace: str, services: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    root = Path(workspace).expanduser().resolve()
    git_root = root if (root / ".git").exists() else root.parent.parent
    if not (git_root / ".git").exists():
        # walk up
        cur = root
        git_root = None
        for _ in range(5):
            if (cur / ".git").exists():
                git_root = cur
                break
            cur = cur.parent
        if git_root is None:
            return []
    out: list[dict[str, Any]] = []
    for svc in services:
        path = svc.get("path") or ""
        rel = path
        try:
            rel = str(Path(path).resolve().relative_to(git_root))
        except (ValueError, OSError):
            rel = path
        if not rel:
            continue
        try:
            proc = subprocess.run(
                ["git", "-C", str(git_root), "log", f"-{limit}", "--pretty=%s", "--", rel],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        msgs = [m.strip() for m in proc.stdout.splitlines() if m.strip()]
        if not msgs:
            continue
        out.append({"service": svc["name"], "version": "git", "functionality": msgs[0], "also": msgs[1:]})
    return out


def analyze_workspace(workspace: str, *, use_llm: bool = False) -> dict[str, Any]:
    """Scan a folder of connected services. Returns graph, broken links, blast radius, issues."""
    scan = scan_workspace(workspace)
    if scan.get("error"):
        return {
            "error": scan["error"],
            "summary": f"Cannot scan: {scan.get('error')}",
            "nodes": [],
            "edges": [],
            "broken_links": [],
            "updates": [],
            "issues": [],
        }
    services = scan.get("services") or []
    dependencies = [{"from": d["from"], "to": d["to"]} for d in (scan.get("dependencies") or [])]
    issues = []
    for raw in scan.get("issues") or []:
        code = raw.get("code") or "scan"
        copy = plain_for(code)
        issues.append(
            {
                "file": raw.get("file"),
                "line": raw.get("line"),
                "service": raw.get("service"),
                "code": code,
                "severity": "high" if code in {"hardcoded_secret", "sql_fstring"} else "medium",
                "problem": copy["wrong"],
                "evidence": raw.get("snippet"),
            }
        )
    if use_llm and issues:
        from releasegraph.ai_layer import enrich_issues, llm_enabled
        from releasegraph.safety import apply_safety_gate

        if llm_enabled():
            engine = list(issues)
            llm = enrich_issues(engine, project_name=scan.get("name"))
            if llm is not engine:
                issues, _safety = apply_safety_gate(engine, llm)

    insight = build_insight(
        services=[{"name": s["name"], "criticality": s.get("criticality", "medium")} for s in services],
        dependencies=dependencies,
        issues=issues,
        updates=git_updates(workspace, services),
    )
    insight["workspace"] = scan.get("workspace")
    insight["issues"] = issues
    insight["engine"] = "releasegraph-sdk"
    insight["plain"] = {k: v["would_change"] for k, v in PLAIN.items()}
    return insight


class Client:
    """Optional remote client for a running ReleaseGraph API."""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def graph(self, project_id: int) -> dict[str, Any]:
        import httpx

        r = httpx.get(
            f"{self.base_url}/api/v1/graph",
            params={"project_id": project_id},
            headers=self._headers(),
            timeout=30.0,
        )
        r.raise_for_status()
        return r.json()

    def scan(self, workspace: str, project_id: int | None = None) -> dict[str, Any]:
        import httpx

        r = httpx.post(
            f"{self.base_url}/api/v1/workspaces/scan",
            json={"workspace": workspace, "project_id": project_id, "persist": True},
            headers=self._headers(),
            timeout=90.0,
        )
        r.raise_for_status()
        return r.json()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="releasegraph-scan",
        description="Scan a microservices workspace. Plug-and-play — no server required.",
    )
    p.add_argument("workspace", help="Folder that contains connected services")
    p.add_argument("--json", action="store_true", help="Print full JSON")
    p.add_argument("--llm", action="store_true", help="Optional Groq rephrase (engine stays source of truth)")
    args = p.parse_args(argv)
    result = analyze_workspace(args.workspace, use_llm=args.llm)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 0 if not result.get("error") else 1
    print(result.get("summary") or "No summary")
    for link in result.get("broken_links") or []:
        print(f"  breaking  {link['from']} → {link['to']}")
        print(f"            {link['if_breaks']}")
        print(f"            feels it: {', '.join(link.get('affects') or [])}")
    for u in result.get("updates") or []:
        print(f"  updated   {u['service']}: {u['functionality']}")
    if result.get("error"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
