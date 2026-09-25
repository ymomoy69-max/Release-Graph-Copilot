"""
Local UI server — stdlib HTTP server bound to 127.0.0.1 only.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

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


def _run_scan(workspace: str, config: str, repos: str, ci_dir: str | None) -> tuple[str, dict]:
    """Run a direct workspace scan, store results, return (run_id, checklist_dict)."""
    from rgc.manifest import Release, Overlay, DEFAULT_ORG_CONFIG
    from rgc.org_config import load_org_config_for_release
    from rgc.models import Checklist
    from rgc.orchestrator import run_release

    # Build release id from workspace scan
    raw_repos = [r.strip() for r in repos.split(",") if r.strip()]
    repos_list = list(dict.fromkeys(raw_repos))

    org_result = load_org_config_for_release(config, "scan")
    if isinstance(org_result, Checklist):
        run_id = uuid.uuid4().hex
        out_dir = os.path.join("out", "ui", run_id)
        checklist_dict = org_result.to_dict()
        gate_module.check(checklist_dict, out_dir)
        _runs[run_id] = out_dir
        return run_id, checklist_dict

    org = org_result
    ci = ci_dir if ci_dir else org.ci_dir
    release_id = org.name + "+" + "+".join(sorted(repos_list))

    release = Release(
        id=release_id,
        question="Is this deploy safe?",
        repos=tuple(repos_list),
        graph_path=org.graph,
        ci_dir=ci,
        changed_paths=(),
        overlays=(),
        workspace_root=workspace,
        config_path=config,
    )

    run_id = uuid.uuid4().hex
    out_dir = os.path.join("out", "ui", run_id)
    checklist = run_release(release, org_config=org)
    checklist_dict = checklist.to_dict()
    gate_module.check(checklist_dict, out_dir)
    _runs[run_id] = out_dir
    return run_id, checklist_dict


# Fixed check order for the checklist display
_CHECK_ORDER = ("pipeline_status", "workflow_config", "fc_etl", "flyway", "playwright_map")

_SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9_./-]+$")


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )


def _status_css(status: str) -> str:
    """Return CSS class for card border color."""
    if status == "pass":
        return "card-pass"
    if status == "warning":
        return "card-warning"
    return "card-blocked"


def _finding_html(finding: dict) -> str:
    """Render a single finding as HTML."""
    repos = finding.get("repos") or []
    message = _html_escape(finding.get("message") or "")
    suggested_fix = _html_escape(finding.get("suggested_fix") or "")
    location = finding.get("location")
    snippet = finding.get("snippet")
    citation = finding.get("citation")

    parts = []
    if repos:
        parts.append(f'<div class="finding-repos">Repos: {_html_escape(", ".join(repos))}</div>')
    parts.append(f'<div class="finding-message">{message}</div>')
    if suggested_fix:
        parts.append(f'<div class="finding-fix">Fix: {suggested_fix}</div>')
    if citation:
        cit_display = _html_escape(citation.get("display") or "")
        cit_section = _html_escape(str(citation.get("section") or ""))
        cit_line = citation.get("line")
        cit_quote = _html_escape(citation.get("quote") or "")
        line_str = f" line {cit_line}" if cit_line else ""
        parts.append(
            f'<div class="finding-citation">'
            f'{cit_display} §{cit_section}{line_str}: {cit_quote}'
            f'</div>'
        )
    if location:
        parts.append(f'<div class="location">{_html_escape(location)}</div>')
    if snippet is not None:
        parts.append(f'<pre class="snippet">{_html_escape(snippet)}</pre>')

    return '<div class="finding">' + "".join(parts) + '</div>'


def _check_card_html(check: dict) -> str:
    """Render a single check as a card."""
    status = check.get("status", "pass")
    name = _html_escape(check.get("name") or check.get("id") or "")
    summary = _html_escape(check.get("summary") or "")
    findings = check.get("findings") or []

    css_class = _status_css(status)
    findings_html = "".join(_finding_html(f) for f in findings)

    return (
        f'<div class="check-card {css_class}">'
        f'<div class="check-header">'
        f'<span class="check-name">{name}</span>'
        f'<span class="check-status status-{status}">{status}</span>'
        f'</div>'
        f'<div class="check-summary">{summary}</div>'
        f'{findings_html}'
        f'</div>'
    )


def _checklist_items_html(checklist: dict) -> str:
    """Build <ul id="checklist"> from checklist checks."""
    checks_by_id = {c["id"]: c for c in checklist.get("checks", [])}
    items = "".join(
        f'<li>{_html_escape(checks_by_id[cid]["summary"])}</li>'
        for cid in _CHECK_ORDER
        if cid in checks_by_id
    )
    return f'<ul id="checklist">{items}</ul>'


def _check_cards_html(checklist: dict) -> str:
    """Build the five check cards."""
    checks_by_id = {c["id"]: c for c in checklist.get("checks", [])}
    cards = "".join(
        _check_card_html(checks_by_id[cid])
        for cid in _CHECK_ORDER
        if cid in checks_by_id
    )
    return f'<div id="check-cards">{cards}</div>'


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
        cards_html = _check_cards_html(checklist)

        if verdict == "go":
            verdict_class = "verdict-go"
            verdict_label = "GO"
            block_section = ""
            approve_btn = '<button id="approve" style="min-height:36px;padding:8px 18px">Approve</button>'
        else:
            verdict_class = "verdict-nogo"
            verdict_label = "NO-GO"
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
            block_section = (
                f'<pre id="citation">{citation_content}</pre>'
                f'<p id="fix">{fixes_html}</p>'
            )
            approve_btn = '<button id="approve" hidden style="min-height:36px;padding:8px 18px">Approve</button>'

        result_section = f"""
<section id="result">
  <div class="verdict-band {verdict_class}">
    <p id="verdict">{verdict_label}</p>
    <p id="risk">Risk: {risk}</p>
    {f'<p id="gate-prompt">{_html_escape(gate_prompt)}</p>' if gate_prompt else ""}
    {block_section}
  </div>
  {checklist_html}
  {cards_html}
  {approve_btn}
  <button id="cancel" style="min-height:36px;padding:8px 18px">Cancel</button>
  <p id="run-id" style="display:none">{run_id}</p>
</section>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Is this deploy safe?</title>
<style>
*, *::before, *::after {{ box-sizing: border-box; }}
body {{
  font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
  font-size: 15px;
  line-height: 1.6;
  background: #f7f8fa;
  margin: 0;
  padding: 20px;
}}
.page-wrap {{
  max-width: 760px;
  margin: 0 auto;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 28px 32px;
}}
h1 {{ font-size: 1.4em; margin: 0 0 16px; color: #1f2328; }}
.forms-row {{ display: flex; flex-wrap: wrap; gap: 20px; margin-bottom: 20px; }}
.form-box {{ flex: 1; min-width: 260px; border: 1px solid #e5e7eb; border-radius: 4px; padding: 12px 16px; background: #f7f8fa; }}
.form-box label {{ display: block; font-size: 0.85em; color: #57606a; margin-bottom: 2px; }}
.form-box input {{ width: 100%; padding: 5px 8px; font-size: 0.9em; border: 1px solid #d0d7de; border-radius: 3px; margin-bottom: 8px; }}
select {{ padding: 5px 8px; font-size: 0.9em; border: 1px solid #d0d7de; border-radius: 3px; width: 100%; margin-bottom: 8px; }}
button {{ padding: 8px 18px; font-size: 0.9em; border: 1px solid #d0d7de; border-radius: 3px; background: #f6f8fa; cursor: pointer; min-height: 36px; }}
button:hover {{ background: #e9ecef; }}
#result {{ margin-top: 24px; border-top: 2px solid #e5e7eb; padding-top: 18px; }}
.verdict-band {{ padding: 14px 18px; border-radius: 4px; margin-bottom: 18px; }}
.verdict-go {{ background: #d1fae5; border-left: 5px solid #10b981; }}
.verdict-nogo {{ background: #fee2e2; border-left: 5px solid #ef4444; }}
#verdict {{ font-weight: bold; font-size: 1.5em; margin: 0 0 4px; }}
#risk {{ margin: 0 0 4px; }}
#gate-prompt {{ margin: 6px 0 0; font-size: 0.95em; }}
#citation {{ background: #f5f5f5; padding: 12px; border-radius: 4px; white-space: pre-wrap; font-family: monospace; font-size: 0.88em; }}
#fix {{ color: #57606a; font-size: 0.9em; }}
#checklist {{ line-height: 1.8; padding-left: 20px; }}
#check-cards {{ margin-top: 16px; }}
.check-card {{ border: 1px solid #e5e7eb; border-radius: 4px; padding: 14px 16px; margin-bottom: 12px; background: #fff; }}
.card-pass {{ border-left: 5px solid #10b981; }}
.card-warning {{ border-left: 5px solid #f59e0b; }}
.card-blocked {{ border-left: 5px solid #ef4444; }}
.check-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }}
.check-name {{ font-weight: 600; color: #1f2328; }}
.check-status {{ font-size: 0.82em; padding: 2px 8px; border-radius: 10px; font-weight: 600; }}
.status-pass {{ background: #d1fae5; color: #065f46; }}
.status-warning {{ background: #fef3c7; color: #92400e; }}
.status-blocked {{ background: #fee2e2; color: #991b1b; }}
.check-summary {{ color: #57606a; font-size: 0.9em; margin-bottom: 6px; }}
.finding {{ margin-top: 10px; padding: 8px 10px; border-radius: 4px; background: #f7f8fa; border: 1px solid #e5e7eb; font-size: 0.88em; }}
.finding-repos {{ color: #57606a; margin-bottom: 2px; }}
.finding-message {{ font-weight: 500; color: #1f2328; }}
.finding-fix {{ color: #3b82d4; margin-top: 3px; }}
.finding-citation {{ color: #7c5cd8; margin-top: 3px; }}
.location {{ font-family: monospace; font-size: 0.85em; color: #57606a; margin-top: 5px; }}
pre.snippet {{ background: #f0f0f0; padding: 8px 10px; border-radius: 3px; font-family: monospace; font-size: 0.85em; white-space: pre-wrap; margin: 6px 0 0; border: 1px solid #e5e7eb; }}
.actions {{ margin-top: 20px; }}
#trigger-message {{ font-weight: 600; margin-top: 12px; }}
</style>
</head>
<body>
<div class="page-wrap">
<h1 id="title">Is this deploy safe?</h1>
<div class="forms-row">
  <div class="form-box">
    <form method="get" action="/">
      <label for="scenario">Fixture scenario</label>
      <select id="scenario" name="scenario">{options}</select>
      <button id="run" type="submit" style="min-height:36px;padding:8px 18px">Check</button>
    </form>
  </div>
  <div class="form-box">
    <form id="scan">
      <label for="workspace">Workspace path</label>
      <input id="workspace" type="text" placeholder="path/to/workspace">
      <label for="config">Org YAML path</label>
      <input id="config" type="text" placeholder="path/to/org.yaml">
      <label for="repos">Repos (comma-separated)</label>
      <input id="repos" type="text" placeholder="api,web">
      <label for="ci-dir">CI dir (optional)</label>
      <input id="ci-dir" type="text" placeholder="">
      <button id="scan-run" type="button" style="min-height:36px;padding:8px 18px">Scan</button>
    </form>
  </div>
</div>
{result_section}
</div>
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
async function doScan() {{
  const workspace = document.getElementById('workspace').value.trim();
  const config = document.getElementById('config').value.trim();
  const repos = document.getElementById('repos').value.trim();
  const ciDir = document.getElementById('ci-dir').value.trim();
  const body = {{ workspace, config, repos }};
  if (ciDir) body.ci_dir = ciDir;
  const resp = await fetch('/api/scan', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(body)
  }});
  const data = await resp.json();
  if (resp.ok) {{
    window.location.href = '/?_scan_result=' + data.run_id;
  }} else {{
    showMessage(data.message || 'Scan failed.');
  }}
}}
const approveBtn = document.getElementById('approve');
const cancelBtn = document.getElementById('cancel');
const scanRunBtn = document.getElementById('scan-run');
if (approveBtn) approveBtn.addEventListener('click', doApprove);
if (cancelBtn) cancelBtn.addEventListener('click', doCancel);
if (scanRunBtn) scanRunBtn.addEventListener('click', doScan);
</script>
</body>
</html>"""


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

        elif parsed.path == "/api/scan":
            workspace = body.get("workspace", "").strip()
            config = body.get("config", "").strip()
            repos = body.get("repos", "").strip() if body.get("repos") is not None else ""
            ci_dir = body.get("ci_dir", "").strip() or None

            # Validate: workspace, config, repos must all be present
            if not workspace or not config or repos is None:
                _json_response(self, 400, {"ok": False, "message": "invalid scan arguments"})
                return

            # Validate workspace path exists
            if not os.path.isdir(workspace):
                _json_response(self, 400, {"ok": False, "message": "invalid scan arguments"})
                return

            # repos must be a non-empty list
            repo_list = [r.strip() for r in repos.split(",") if r.strip()]
            if not repo_list:
                _json_response(self, 400, {"ok": False, "message": "invalid scan arguments"})
                return

            try:
                run_id, checklist = _run_scan(workspace, config, repos, ci_dir)
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
