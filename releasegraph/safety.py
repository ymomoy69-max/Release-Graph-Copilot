"""Human safety gate — the engine is source of truth; the LLM may only explain."""
from __future__ import annotations

from typing import Any


def _key(issue: dict[str, Any]) -> tuple[str, str, int | None]:
    line = issue.get("line")
    try:
        line_n = int(line) if line is not None and str(line).isdigit() else None
    except (TypeError, ValueError):
        line_n = None
    return (str(issue.get("file") or ""), str(issue.get("code") or ""), line_n)


def _same_identity(engine: dict[str, Any], llm: dict[str, Any]) -> bool:
    if _key(engine) != _key(llm):
        return False
    eng_svc = (engine.get("service") or "").strip()
    llm_svc = (llm.get("service") or "").strip()
    if eng_svc and llm_svc and eng_svc != llm_svc:
        return False
    return True


def apply_safety_gate(
    engine_issues: list[dict[str, Any]],
    llm_issues: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Keep every engine finding. Drop LLM rows that invent files or change identity."""
    llm_map: dict[tuple[str, str, int | None], dict[str, Any]] = {}
    for row in llm_issues or []:
        if isinstance(row, dict):
            llm_map[_key(row)] = row

    accepted = 0
    rejected = 0
    used_llm_keys: set[tuple[str, str, int | None]] = set()
    out: list[dict[str, Any]] = []
    for orig in engine_issues:
        row = dict(orig)
        row["engine_fix"] = orig.get("fix")
        row["engine_problem"] = orig.get("problem")
        row["human_required"] = True
        row["verification"] = "engine"
        extra = llm_map.get(_key(orig))
        if extra and _same_identity(orig, extra):
            used_llm_keys.add(_key(orig))
            for field in ("problem", "consequences", "fix"):
                text = extra.get(field)
                if isinstance(text, str) and 8 < len(text.strip()) < 2000:
                    row[f"llm_{field}"] = text.strip()
                    row[field] = text.strip()
            row["llm_accepted"] = True
            row["confidence"] = "high" if orig.get("source") in {"rgc", "workspace_scan"} else "medium"
            accepted += 1
        else:
            row["llm_accepted"] = False
            if extra:
                used_llm_keys.add(_key(orig))
                row["llm_rejected_reason"] = "LLM changed file, line, or service — engine finding kept"
                rejected += 1
            row["confidence"] = "high"
        out.append(row)

    for key in llm_map:
        if key not in used_llm_keys:
            rejected += 1

    return out, {
        "engine_source_of_truth": True,
        "human_required": True,
        "llm_used": bool(llm_issues),
        "llm_accepted": accepted,
        "llm_rejected": rejected,
        "note": (
            "Checkers and the workspace scanner produced these findings. "
            "Groq may only rephrase them. A person must approve each fix PR before it is marked merged."
        ),
    }
