"""Pure graph insight — no database, no HTTP. Used by the UI and the SDK."""
from __future__ import annotations

from typing import Any

PLAIN: dict[str, dict[str, str]] = {
    "hardcoded_secret": {
        "wrong": "A secret is written in the source.",
        "if_breaks": "Anyone with the repo can impersonate this service.",
        "would_change": "Move the secret to env/config and rotate it. Callers stay the same.",
    },
    "swallowed_exception": {
        "wrong": "A failure is caught and ignored.",
        "if_breaks": "Callers think it worked when it did not.",
        "would_change": "The error is logged and returned. Partial checkouts stop looking like success.",
    },
    "http_no_timeout": {
        "wrong": "An outbound call has no timeout.",
        "if_breaks": "If a dependency hangs, this service blocks — then every caller waits.",
        "would_change": "Calls fail fast. Checkout can retry or show an error instead of hanging.",
    },
    "sql_fstring": {
        "wrong": "SQL is built with string interpolation.",
        "if_breaks": "Untrusted input can read or change this service’s data.",
        "would_change": "Queries use bound parameters. The API shape does not change.",
    },
    "incident": {
        "wrong": "There is an open production incident on this service.",
        "if_breaks": "On-call already saw this fail after a ship.",
        "would_change": "Confirm a rollback or a fix before the next release.",
    },
}


def plain_for(code: str | None) -> dict[str, str]:
    c = str(code or "")
    if c in PLAIN:
        return PLAIN[c]
    if c.startswith("incident"):
        return PLAIN["incident"]
    return {
        "wrong": "The engine flagged this service.",
        "if_breaks": "Callers of this service can fail.",
        "would_change": "Apply the engine fix, then re-scan.",
    }


def blast_names(seed: str, pairs: list[tuple[str, str]]) -> list[str]:
    """pairs: (from, to) meaning from depends on to. Return seed + everything that depends on it."""
    affected = {seed}
    changed = True
    while changed:
        changed = False
        for frm, to in pairs:
            if to in affected and frm not in affected:
                affected.add(frm)
                changed = True
    out = [seed] + [n for n in affected if n != seed]
    return out


def rank_services(names: list[str], pairs: list[tuple[str, str]]) -> dict[str, int]:
    """0 = depended-on (leaf). Higher = more callers above it."""
    rank = {n: 0 for n in names}
    for _ in range(len(names) + 2):
        for frm, to in pairs:
            if frm in rank and to in rank:
                rank[frm] = max(rank[frm], rank[to] + 1)
    return rank


def build_insight(
    *,
    services: list[dict[str, Any]],
    dependencies: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    updates: list[dict[str, Any]] | None = None,
    incidents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    names = [s["name"] for s in services if s.get("name")]
    pairs = [(d["from"], d["to"]) for d in dependencies if d.get("from") and d.get("to")]
    ranks = rank_services(names, pairs)
    updates = updates or []
    incidents = incidents or []
    update_by = {u["service"]: u for u in updates if u.get("service")}

    issues_by: dict[str, list[dict[str, Any]]] = {n: [] for n in names}
    for issue in issues:
        svc = issue.get("service")
        if svc in issues_by:
            issues_by[svc].append(issue)
        elif svc:
            issues_by.setdefault(svc, []).append(issue)
            if svc not in names:
                names.append(svc)
                ranks[svc] = ranks.get(svc, 0)

    incident_by: dict[str, dict[str, Any]] = {}
    for inc in incidents:
        svc = inc.get("service")
        if svc:
            incident_by[svc] = inc

    broken: set[str] = set()
    warning: set[str] = set()
    node_meta: dict[str, dict[str, Any]] = {}
    for name in names:
        rows = issues_by.get(name) or []
        inc = incident_by.get(name)
        high = any(
            (r.get("severity") in {"high", "block", "critical"}) or str(r.get("code") or "").startswith("incident")
            for r in rows
        )
        if inc or high:
            broken.add(name)
            status = "broken"
        elif rows:
            warning.add(name)
            status = "warning"
        elif name in update_by:
            status = "updated"
        else:
            status = "ok"
        top = rows[0] if rows else None
        code = (top or {}).get("code") or ("incident" if inc else None)
        if code:
            copy = plain_for(code)
            headline = (top or {}).get("problem") or (inc.get("title") if inc else None) or copy["wrong"]
        elif name in update_by:
            copy = {
                "wrong": "No engine finding on this service.",
                "if_breaks": f"If {name} failed, its callers would stop.",
                "would_change": "This box changed in the last ship. No new engine finding here.",
            }
            headline = f"Updated: {update_by[name].get('functionality')}"
        else:
            copy = {
                "wrong": "No engine finding on this service.",
                "if_breaks": f"If {name} failed, its callers would stop.",
                "would_change": "Nothing to change here until this service is flagged.",
            }
            headline = "No problem on this box."
        node_meta[name] = {
            "status": status,
            "headline": headline,
            "wrong": copy["wrong"],
            "if_breaks": copy["if_breaks"],
            "would_change": copy["would_change"],
            "issue_count": len(rows) + (1 if inc and not any(str(r.get("code")).startswith("incident") for r in rows) else 0),
            "codes": [r.get("code") for r in rows],
            "file": (top or {}).get("file"),
            "line": (top or {}).get("line"),
            "affects": blast_names(name, pairs) if status in {"broken", "warning"} else [name],
            "updated": update_by.get(name),
            "incident": inc.get("title") if inc else None,
        }

    at_risk: set[str] = set()
    for seed in broken | warning:
        for n in blast_names(seed, pairs):
            if n not in broken and n not in warning:
                at_risk.add(n)

    nodes = []
    for s in services:
        name = s["name"]
        meta = node_meta.get(name) or {}
        status = meta.get("status") or "ok"
        if name in at_risk and status in {"ok", "updated"}:
            status = "at_risk"
            meta = {
                **meta,
                "status": "at_risk",
                "headline": f"Depends on a problem service. If that link fails, {name} feels it.",
                "if_breaks": f"{name} sits above a breaking link.",
                "would_change": "Fix the red box it calls. This service does not need a code change of its own.",
                "affects": blast_names(name, pairs),
            }
        nodes.append(
            {
                "id": f"service:{name}",
                "type": "service",
                "label": name,
                "status": status,
                "criticality": s.get("criticality") or "medium",
                "rank": ranks.get(name, 0),
                **{k: meta[k] for k in ("headline", "wrong", "if_breaks", "would_change", "issue_count", "file", "line", "affects", "updated", "incident") if k in meta},
            }
        )

    broken_links = []
    edges = []
    for i, (frm, to) in enumerate(pairs):
        to_status = (node_meta.get(to) or {}).get("status") or "ok"
        is_breaking = to_status in {"broken", "warning"}
        copy = plain_for(((issues_by.get(to) or [{}])[0] or {}).get("code"))
        edge = {
            "id": f"dep-{i}-{frm}-{to}",
            "source": f"service:{frm}",
            "target": f"service:{to}",
            "type": "depends_on",
            "broken": is_breaking,
            "label": "breaking" if is_breaking else "",
        }
        edges.append(edge)
        if is_breaking:
            affected = blast_names(to, pairs)
            broken_links.append(
                {
                    "from": frm,
                    "to": to,
                    "why": (node_meta.get(to) or {}).get("headline") or copy["wrong"],
                    "if_breaks": f"{frm} cannot finish work that needs {to}.",
                    "would_change": copy["would_change"],
                    "affects": affected,
                }
            )

    seeds = sorted(broken | warning)
    all_affected: list[str] = []
    seen: set[str] = set()
    for s in seeds:
        for n in blast_names(s, pairs):
            if n not in seen:
                seen.add(n)
                all_affected.append(n)

    if seeds:
        summary = (
            f"{len(broken_links)} link(s) at risk. "
            f"Cause: {', '.join(seeds)}. "
            f"Feels it: {', '.join(all_affected)}."
        )
    else:
        summary = "No strained links in this workspace. Click a service to see who depends on it."

    return {
        "summary": summary,
        "nodes": nodes,
        "edges": edges,
        "broken_links": broken_links,
        "updates": updates,
        "broken_services": seeds,
        "affected_services": all_affected,
    }
