"""
Local UI server — stdlib HTTP server bound to 127.0.0.1 only.
"""
from __future__ import annotations

import json
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from typing import TYPE_CHECKING

from rgc import gate as gate_module
from rgc.models import format_checklist_json
from rgc.orchestrator import run_release_file


# Scenario order from section 20
SCENARIO_ORDER = [
    "safe",
    "unsafe-flag-flip",
    "red-pipeline",
    "unsafe-flyway",
    "broken-workflow-contract",
    "blocked-etl-path",
    "missing-docs",
    "cyclic-graph",
    "unknown-repo",
    "malformed-yaml",
    "empty-release",
]

SCENARIO_RELEASE_FILES = {
    s: f"fixtures/releases/{s}.json" for s in SCENARIO_ORDER
}

# In-memory store: run_id → out_dir
_runs: dict[str, str] = {}


def _run_check(scenario_id: str) -> tuple[str, dict]:
    """Run a check for the scenario, store results, return (run_id, checklist_dict)."""
    release_path = SCENARIO_RELEASE_FILES[scenario_id]
    run_id = uuid.uuid4().hex
    out_dir = os.path.join("out", "ui", run_id)
    checklist = run_release_file(release_path)
    checklist_dict = checklist.to_dict()
    gate_module.check(checklist_dict, out_dir)
    _runs[run_id] = out_dir
    return run_id, checklist_dict


# Fixed check order for the checklist display
_CHECK_ORDER = ("pipeline_status", "workflow_config", "fc_etl", "flyway", "playwright_map")


def _checklist_items_html(checklist: dict) -> str:
    """Build <ul id="checklist"> from checklist checks."""
    checks_by_id = {c["id"]: c for c in checklist.get("checks", [])}
    items = "".join(
        f'<li>{_html_escape(checks_by_id[cid]["summary"])}</li>'
        for cid in _CHECK_ORDER
        if cid in checks_by_id
    )
    return f'<ul id="checklist">{items}</ul>'


def _html_page(scenario_id: str | None = None, checklist: dict | None = None, run_id: str | None = None) -> str:
    """Build the full HTML page."""
    # Build scenario options
    options = "\n".join(
        f'<option value="{s}"{" selected" if s == scenario_id else ""}>{s}</option>'
        for s in SCENARIO_ORDER
    )

    result_section = ""
    if checklist is not None and run_id is not None:
        verdict = checklist.get("verdict", "")
        risk = checklist.get("risk", "")
        gate_prompt = checklist.get("gate_prompt", "") or ""
        block_report = checklist.get("block_report")
        suggested_fixes = checklist.get("suggested_fixes", [])
        checklist_html = _checklist_items_html(checklist)

        if verdict == "go":
            result_section = f"""
<section id="result">
  <p id="verdict">GO</p>
  <p id="risk">Risk: {risk}</p>
  {checklist_html}
  <p id="gate-prompt">{gate_prompt}</p>
  <button id="approve">Approve</button>
  <button id="cancel">Cancel</button>
  <p id="run-id" style="display:none">{run_id}</p>
</section>"""
        else:
            # NO-GO
            if block_report:
                citation_content = _html_escape(block_report)
            else:
                blocked_msgs = []
                for check in checklist.get("checks", []):
                    for f in check.get("findings", []):
                        if f.get("severity") == "block":
                            blocked_msgs.append(f.get("message", ""))
                citation_content = _html_escape("\n".join(blocked_msgs))

            fixes_html = "\n".join(f"<span>{_html_escape(fix)}</span>" for fix in suggested_fixes)
            result_section = f"""
<section id="result">
  <p id="verdict">NO-GO</p>
  <p id="risk">Risk: {risk}</p>
  {checklist_html}
  <pre id="citation">{citation_content}</pre>
  <p id="fix">{fixes_html}</p>
  <button id="approve" hidden>Approve</button>
  <button id="cancel">Cancel</button>
  <p id="run-id" style="display:none">{run_id}</p>
</section>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Is this deploy safe?</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; }}
h1 {{ font-size: 1.5em; }}
select, button {{ padding: 6px 12px; margin: 4px; }}
#result {{ margin-top: 20px; border-top: 1px solid #ccc; padding-top: 16px; }}
pre {{ background: #f5f5f5; padding: 12px; border-radius: 4px; white-space: pre-wrap; }}
#checklist {{ line-height: 1.8; padding-left: 20px; }}
.go {{ color: green; font-weight: bold; font-size: 1.4em; }}
.no-go {{ color: red; font-weight: bold; font-size: 1.4em; }}
</style>
</head>
<body>
<h1 id="title">Is this deploy safe?</h1>
<p id="prompt">Is this deploy safe?</p>
<form method="get" action="/">
  <select id="scenario" name="scenario">{options}</select>
  <button id="run" type="submit">Check</button>
</form>
{result_section}
<script>
function showMessage(msg) {{
  let el = document.getElementById('trigger-message');
  if (!el) {{
    el = document.createElement('p');
    el.id = 'trigger-message';
    document.getElementById('result').appendChild(el);
  }}
  el.textContent = msg;
}}
function hideBtns() {{
  const a = document.getElementById('approve');
  const c = document.getElementById('cancel');
  if (a) a.hidden = true;
  if (c) c.hidden = true;
}}
async function doApprove() {{
  const runId = document.getElementById('run-id').textContent.trim();
  const resp = await fetch('/api/approve', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{run_id: runId}})
  }});
  const data = await resp.json();
  if (resp.ok) {{
    showMessage('E2E trigger written.');
    const folders = data.trigger && data.trigger.folders ? data.trigger.folders : [];
    let ul = document.getElementById('e2e-folders');
    if (!ul) {{
      ul = document.createElement('ul');
      ul.id = 'e2e-folders';
      document.getElementById('result').appendChild(ul);
    }}
    ul.innerHTML = folders.map(f => '<li>' + f + '</li>').join('');
    let est = document.getElementById('e2e-estimate');
    if (!est) {{
      est = document.createElement('p');
      est.id = 'e2e-estimate';
      document.getElementById('result').appendChild(est);
    }}
    est.textContent = data.trigger && data.trigger.estimate_display ? data.trigger.estimate_display : '';
    hideBtns();
  }} else {{
    showMessage(data.message);
  }}
}}
async function doCancel() {{
  const runId = document.getElementById('run-id').textContent.trim();
  const resp = await fetch('/api/cancel', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{run_id: runId}})
  }});
  const data = await resp.json();
  if (resp.ok) {{
    showMessage('Nothing was triggered.');
    hideBtns();
  }} else {{
    showMessage(data.message);
  }}
}}
const approveBtn = document.getElementById('approve');
const cancelBtn = document.getElementById('cancel');
if (approveBtn) approveBtn.addEventListener('click', doApprove);
if (cancelBtn) cancelBtn.addEventListener('click', doCancel);
</script>
</body>
</html>"""


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _json_response(handler, status: int, data: dict) -> None:
    body = json.dumps(data, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class RGCHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress access log

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path == "/":
            scenario_id = qs.get("scenario", [None])[0]
            checklist = None
            run_id = None

            if scenario_id is not None:
                if scenario_id not in SCENARIO_RELEASE_FILES:
                    _json_response(self, 404, {"ok": False, "message": "unknown scenario"})
                    return
                try:
                    run_id, checklist = _run_check(scenario_id)
                except Exception as exc:
                    _json_response(self, 500, {"ok": False, "message": str(exc)})
                    return

            html = _html_page(scenario_id, checklist, run_id)
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif parsed.path == "/api/scenarios":
            _json_response(self, 200, {"scenarios": SCENARIO_ORDER})

        else:
            _json_response(self, 404, {"ok": False, "message": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)

        # Read body
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b""
        try:
            body = json.loads(body_bytes) if body_bytes else {}
        except json.JSONDecodeError:
            _json_response(self, 400, {"ok": False, "message": "invalid request"})
            return

        if not isinstance(body, dict):
            _json_response(self, 400, {"ok": False, "message": "invalid request"})
            return

        if parsed.path == "/api/check":
            scenario_id = body.get("scenario")
            if not scenario_id or scenario_id not in SCENARIO_RELEASE_FILES:
                _json_response(self, 404, {"ok": False, "message": "unknown scenario"})
                return
            try:
                run_id, checklist = _run_check(scenario_id)
            except Exception as exc:
                _json_response(self, 500, {"ok": False, "message": str(exc)})
                return

            show_approve = (
                checklist.get("verdict") == "go"
                and checklist.get("gate") == "pending_approval"
            )
            _json_response(self, 200, {
                "run_id": run_id,
                "show_approve": show_approve,
                "checklist": checklist,
            })

        elif parsed.path == "/api/approve":
            run_id = body.get("run_id")
            if not run_id or run_id not in _runs:
                _json_response(self, 404, {"ok": False, "message": "run not found"})
                return
            out_dir = _runs[run_id]
            exit_code, stdout, stderr = gate_module.approve(out_dir)
            if exit_code != 0:
                msg = stderr.strip() if stderr else "approval rejected"
                _json_response(self, 409, {"ok": False, "message": msg})
                return
            trigger = json.loads(stdout)
            _json_response(self, 200, {
                "ok": True,
                "message": "E2E trigger written.",
                "trigger": trigger,
            })

        elif parsed.path == "/api/cancel":
            run_id = body.get("run_id")
            if not run_id or run_id not in _runs:
                _json_response(self, 404, {"ok": False, "message": "run not found"})
                return
            out_dir = _runs[run_id]
            exit_code, stdout, stderr = gate_module.cancel(out_dir)
            if exit_code != 0:
                msg = stderr.strip() if stderr else "cancel rejected"
                _json_response(self, 409, {"ok": False, "message": msg})
                return
            _json_response(self, 200, {
                "ok": True,
                "message": "Nothing was triggered.",
            })

        else:
            _json_response(self, 404, {"ok": False, "message": "not found"})


def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    if host != "127.0.0.1":
        raise ValueError("host must be loopback")
    server = ThreadingHTTPServer((host, port), RGCHandler)
    server.serve_forever()
