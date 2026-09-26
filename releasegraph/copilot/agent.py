"""Evidence-backed copilot — uses tools, never fabricates data."""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from releasegraph.ai_layer import complete_from_tools
from releasegraph.copilot.tools import CopilotTools


def _service_names(graph: dict[str, Any]) -> list[str]:
    return [n["label"] for n in graph.get("nodes", []) if n.get("type") == "service" and n.get("label")]


def _pick_service(question: str, names: list[str], fallback: str | None) -> str | None:
    q = question.lower()
    hits = [n for n in names if n.lower() in q]
    if hits:
        hits.sort(key=len, reverse=True)
        return hits[0]
    return fallback


def _format_issues(analysis: dict[str, Any]) -> str:
    issues = analysis.get("issues") or []
    if not issues:
        return "No file-level issues were stored for this project. Scan a workspace first."
    lines = [f"Found {len(issues)} issue(s):"]
    for i, issue in enumerate(issues[:12], 1):
        loc = issue.get("file") or "unknown"
        if issue.get("line"):
            loc = f"{loc}:{issue['line']}"
        lines.append(f"{i}. {loc}")
        if issue.get("service"):
            lines.append(f"   Service: {issue['service']}")
        lines.append(f"   Wrong: {issue.get('problem')}")
        if issue.get("verification") == "engine":
            lines.append("   Verified by: engine (not the LLM)")
        affects = issue.get("affects") or []
        if affects:
            lines.append(f"   Affects: {', '.join(affects)}")
        if issue.get("consequences"):
            lines.append(f"   Consequences: {issue['consequences']}")
        if issue.get("engine_fix"):
            lines.append(f"   Engine fix: {issue.get('engine_fix')}")
        elif issue.get("fix"):
            lines.append(f"   Fix: {issue['fix']}")
        if issue.get("llm_accepted") and issue.get("llm_fix"):
            lines.append(f"   Groq wording (not a new finding): {issue['llm_fix']}")
    safety = analysis.get("safety") or {}
    if safety:
        lines.append("")
        lines.append(safety.get("note") or "A person must approve each fix PR.")
    created = analysis.get("proposals") or []
    if created:
        lines.append(f"Opened {len(created)} in-app demo PR(s) for employees to verify.")
    return "\n".join(lines)


def answer_question(db: Session, project_id: int, question: str) -> tuple[str, list[dict[str, Any]]]:
    """Return (answer_text, tool_calls_made)."""
    tools = CopilotTools(db, project_id)
    q = question.lower().strip()
    calls: list[dict[str, Any]] = []

    def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        raw = tools.run_tool(name, args)
        data = json.loads(raw)
        calls.append({"tool": name, "arguments": args, "result": data})
        return data

    graph = call("get_release_graph", {})
    names = _service_names(graph)
    fallback = names[0] if names else None

    if any(w in q for w in ("fix pr", "pull request", "assigned", "ticket")):
        prs = call("list_fix_prs", {})
        items = prs.get("pull_requests") or []
        if not items:
            return "No in-app fix PRs yet. Scan a workspace on Readiness to open assigned tickets from engine findings.", calls
        lines = ["In-app demo PRs (not GitHub or Jira):"]
        for p in items[:12]:
            who = (p.get("assignee") or {}).get("full_name") or "unassigned"
            lines.append(f"#{p['number']} {p['status']} → {who} · {p.get('file')}")
        llm = complete_from_tools(question, {"fix_prs": items[:12]})
        return (llm or "\n".join(lines)), calls

    if any(w in q for w in ("wrong", "error", "fix", "file", "analy", "what is broken", "consequence")):
        id_match = re.search(r"#(\d+)", q)
        analysis = call(
            "analyze_errors",
            {"incident_id": int(id_match.group(1))} if id_match and "incident" in q else {},
        )
        answer = _format_issues(analysis)
        llm = complete_from_tools(question, {"analysis": analysis, "graph": graph})
        return (llm or answer), calls

    if "investigate" in q and "incident" in q:
        id_match = re.search(r"#(\d+)", q) or re.search(r"incident\s+(\d+)", q)
        if id_match:
            inc_id = int(id_match.group(1))
            detail = call("get_incidents", {"incident_id": inc_id})
            if "error" in detail:
                return (
                    f"I could not find incident #{inc_id} in this project. "
                    "Open Incidents and pick a ticket from the list.",
                    calls,
                )
        else:
            incs = call("get_incidents", {})
            if "incidents" not in incs or not incs["incidents"]:
                return "No incidents are stored for this project.", calls
            inc_id = incs["incidents"][0]["id"]
            detail = call("get_incidents", {"incident_id": inc_id})
        analysis = call("analyze_errors", {"incident_id": detail.get("id") or inc_id})
        lines = [
            f"Incident #{detail.get('id', inc_id)}: {detail.get('title', 'Unknown')}",
            f"Service: {detail.get('service') or 'unknown'}",
            f"Status: {detail.get('status')}",
            "",
            "What happened (from the stored timeline):",
        ]
        for e in detail.get("timeline", []):
            lines.append(f"- {e.get('message')}")
        rid = detail.get("release_id")
        lines.append("")
        lines.append(f"Related release id: {rid}" if rid else "No related release was stored.")
        lines.append("")
        lines.append(_format_issues(analysis))
        llm = complete_from_tools(question, {"incident": detail, "analysis": analysis, "graph": graph})
        return (llm or "\n".join(lines)), calls

    if "affected" in q or "blast" in q or "depend" in q:
        name = _pick_service(q, names, fallback)
        if not name:
            return "No services are mapped yet. Scan a workspace to build the graph.", calls
        deps = call("get_service_dependencies", {"service_name": name})
        blast = call("calculate_blast_radius", {"service_names": [name]})
        answer = (
            f"Services that depend on {name} (directly or transitively):\n"
            f"{', '.join(deps.get('dependents', []) or ['none'])}\n\n"
            f"Blast radius: {', '.join(blast.get('affected_services', []))}"
        )
        return answer, calls

    if "risky" in q or "risk" in q:
        rel = call("get_latest_release", {})
        if "error" in rel:
            return "No release data is available in this project.", calls
        answer = (
            f"Release {rel['version']} — Risk: {rel['risk_level']} (score {rel['risk_score']})\n"
            f"Status: {rel['status']}\n"
            f"Services: {', '.join(rel.get('services', []))}\n"
            "Use the release detail page for full risk factor breakdown."
        )
        return answer, calls

    if "latest release" in q or "what changed" in q or "summarize" in q:
        rel = call("get_latest_release", {})
        if "error" in rel:
            return "No releases found for this project.", calls
        answer = (
            f"Release {rel['version']} ({rel['status']})\n"
            f"Commits ({len(rel.get('commits', []))}):\n"
            + "\n".join(f"  - {c['sha']}: {c['message']}" for c in rel.get("commits", [])[:8])
            + f"\nPRs: {len(rel.get('pull_requests', []))}\n"
            f"Services: {', '.join(rel.get('services', []))}"
        )
        return answer, calls

    if "deployment" in q and "today" in q:
        rel = call("get_latest_release", {})
        deps = rel.get("deployments", [])
        answer = f"Deployments for latest release: {json.dumps(deps, indent=2)}" if deps else "No deployments recorded."
        return answer, calls

    analysis = call("analyze_errors", {})
    answer = (
        f"Graph: {len(graph.get('nodes', []))} nodes, {len(graph.get('edges', []))} edges. "
        f"Services: {', '.join(names) or 'none yet'}.\n\n"
        + _format_issues(analysis)
        + "\n\nAsk about a release, incident, blast radius, or 'what is wrong and how do we fix it'."
    )
    llm = complete_from_tools(question, {"graph": graph, "analysis": analysis})
    return (llm or answer), calls
