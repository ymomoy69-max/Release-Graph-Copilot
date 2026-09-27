"""Groq LLM — wording only. Never the source of findings."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from releasegraph.config import settings

log = logging.getLogger(__name__)

SYSTEM = (
    "You assist a release-engineering product. You do NOT discover bugs. "
    "You only rewrite the given issues in clearer English. "
    "Do not add issues. Do not change file, line, service, code, source, or affects. "
    "Do not invent paths. Return JSON {\"issues\":[...]} with the same length and identity fields."
)


def llm_enabled() -> bool:
    """Groq/Copilot is on unless RG_AI_DISABLE is explicitly set."""
    return os.getenv("RG_AI_DISABLE", "").lower() not in ("1", "true", "yes")


def _api_key() -> str:
    if not llm_enabled():
        return ""
    if "GROQ_API_KEY" in os.environ:
        return os.environ.get("GROQ_API_KEY", "").strip()
    return (settings.groq_api_key or "").strip()


def _fake_groq_answer(question: str, tool_context: dict[str, Any]) -> str:
    """Deterministic Copilot copy when no Groq key is configured."""
    keys = ", ".join(sorted(tool_context.keys())) or "none"
    q = (question or "").strip() or "this release"
    return (
        f"Copilot (demo mode): {q}\n\n"
        f"I used the ReleaseGraph tools ({keys}) as the source of truth. "
        "Findings come from the engine. A person must still approve any fix PR. "
        "Set GROQ_API_KEY for live Groq rephrasing."
    )


def _chat(messages: list[dict[str, str]], *, json_mode: bool) -> str | None:
    key = _api_key()
    if not key:
        return None
    models = []
    for m in (settings.groq_model, "openai/gpt-oss-20b", "qwen/qwen3.8-27b", "openai/gpt-oss-120b"):
        if m and m not in models:
            models.append(m)
    last_err = None
    for model in models:
        payload: dict[str, Any] = {
            "model": model,
            "temperature": 0.1,
            "messages": messages,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            with httpx.Client(timeout=45.0) as client:
                res = client.post(
                    f"{settings.groq_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            if res.status_code >= 400:
                last_err = f"HTTP {res.status_code}: {res.text[:300]}"
                continue
            return res.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
            last_err = str(exc)
            continue
    if last_err:
        log.warning("Groq call failed: %s", last_err)
    return None


def _parse_issues(content: str) -> list[dict[str, Any]] | None:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            return None
    out = data.get("issues") if isinstance(data, dict) else None
    return out if isinstance(out, list) else None


def enrich_issues(issues: list[dict[str, Any]], project_name: str | None = None) -> list[dict[str, Any]]:
    """Ask Groq to rephrase. Caller MUST run apply_safety_gate on the result."""
    if not llm_enabled() or not issues:
        return issues
    compact = []
    for i in issues[:20]:
        compact.append(
            {
                "file": i.get("file"),
                "line": i.get("line"),
                "service": i.get("service"),
                "code": i.get("code"),
                "source": i.get("source"),
                "severity": i.get("severity"),
                "problem": i.get("problem"),
                "consequences": i.get("consequences"),
                "fix": i.get("fix"),
                "affects": i.get("affects"),
                "evidence": i.get("evidence"),
            }
        )
    messages = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": "Rephrase these issues as json only. Do not add or drop rows.\n"
            + json.dumps({"project": project_name, "issues": compact}, default=str),
        },
    ]
    content = _chat(messages, json_mode=True) or _chat(messages, json_mode=False)
    if not content:
        return issues
    parsed = _parse_issues(content)
    return parsed if parsed is not None else issues


def complete_from_tools(question: str, tool_context: dict[str, Any]) -> str | None:
    if not llm_enabled():
        return None
    if not _api_key():
        return _fake_groq_answer(question, tool_context)
    messages = [
        {
            "role": "system",
            "content": (
                "Answer using only tool_context. If a field is missing, say it is unavailable. "
                "Never invent a file path. Remind the reader that a human must approve fix PRs."
            ),
        },
        {
            "role": "user",
            "content": json.dumps({"question": question, "tool_context": tool_context}, default=str)[:20000],
        },
    ]
    return _chat(messages, json_mode=False) or _fake_groq_answer(question, tool_context)
