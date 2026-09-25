"""Tests for the local UI server."""
import json
import threading
import urllib.request
import urllib.error
import urllib.parse
import pytest
from http.server import ThreadingHTTPServer
from rgc.server import RGCHandler


def start_test_server():
    """Start a server on port 0 (OS assigns port), return (server, port)."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), RGCHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def get(port, path):
    url = f"http://127.0.0.1:{port}{path}"
    with urllib.request.urlopen(url) as resp:
        return resp.status, resp.read().decode("utf-8"), resp.headers


def post(port, path, body):
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


@pytest.fixture(scope="module")
def server():
    srv, port = start_test_server()
    yield port
    srv.shutdown()


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

def test_get_root_contains_title(server):
    _, body, _ = get(server, "/")
    assert "Is this deploy safe?" in body


def test_get_root_has_no_result_section(server):
    """GET / with no query has no result section."""
    _, body, _ = get(server, "/")
    assert 'id="result"' not in body
    # id="approve" is not required on the empty form
    # (approve button only appears in result section)


def test_get_root_scenario_safe(server):
    """GET /?scenario=safe contains Risk: LOW and the LOW gate prompt."""
    _, body, _ = get(server, "/?scenario=safe")
    assert "Risk: LOW" in body
    assert "Ready to trigger E2E. Risk: LOW. Approve?" in body
    assert 'id="approve"' in body
    # approve button should NOT have hidden attribute
    assert 'id="approve" hidden' not in body and 'hidden' not in body.split('id="approve"')[1].split('>')[0] if 'id="approve"' in body else True


def test_get_root_scenario_unsafe_flag_flip(server):
    """GET /?scenario=unsafe-flag-flip contains the quote, id=fix, and approve has hidden."""
    _, body, _ = get(server, "/?scenario=unsafe-flag-flip")
    assert "rehydrate must run before flag flip to GIT" in body
    assert 'id="fix"' in body
    assert 'id="approve" hidden' in body


# ---------------------------------------------------------------------------
# GET /api/scenarios
# ---------------------------------------------------------------------------

def test_api_scenarios_order(server):
    _, body, _ = get(server, "/api/scenarios")
    data = json.loads(body)
    expected = [
        "safe", "unsafe-flag-flip", "red-pipeline", "unsafe-flyway",
        "broken-workflow-contract", "blocked-etl-path", "missing-docs",
        "cyclic-graph", "unknown-repo", "malformed-yaml", "empty-release",
    ]
    assert data["scenarios"] == expected


# ---------------------------------------------------------------------------
# POST /api/check
# ---------------------------------------------------------------------------

def test_post_check_safe_returns_show_approve(server):
    status, data = post(server, "/api/check", {"scenario": "safe"})
    assert status == 200
    assert data["show_approve"] is True
    assert "run_id" in data
    assert data["checklist"]["verdict"] == "go"


def test_post_check_unknown_scenario(server):
    status, data = post(server, "/api/check", {"scenario": "nonexistent"})
    assert status == 404
    assert data["message"] == "unknown scenario"


def test_post_check_bad_json(server):
    url = f"http://127.0.0.1:{server}/api/check"
    data = b"not json {{{"
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        status = e.code
        body = json.loads(e.read())
    assert status == 400
    assert body["message"] == "invalid request"


# ---------------------------------------------------------------------------
# POST /api/approve
# ---------------------------------------------------------------------------

def test_post_approve_safe(server):
    _, check_data = post(server, "/api/check", {"scenario": "safe"})
    run_id = check_data["run_id"]
    status, data = post(server, "/api/approve", {"run_id": run_id})
    assert status == 200
    assert data["ok"] is True
    assert data["message"] == "E2E trigger written."
    assert data["trigger"]["folders"] == ["backend", "etl", "gateway"]


def test_post_approve_unsafe_returns_409(server):
    _, check_data = post(server, "/api/check", {"scenario": "unsafe-flag-flip"})
    run_id = check_data["run_id"]
    status, data = post(server, "/api/approve", {"run_id": run_id})
    assert status == 409
    assert data["ok"] is False


def test_post_approve_unknown_run(server):
    status, data = post(server, "/api/approve", {"run_id": "doesnotexist"})
    assert status == 404
    assert data["message"] == "run not found"


# ---------------------------------------------------------------------------
# POST /api/cancel
# ---------------------------------------------------------------------------

def test_post_cancel_safe_returns_nothing_triggered(server):
    _, check_data = post(server, "/api/check", {"scenario": "safe"})
    run_id = check_data["run_id"]
    status, data = post(server, "/api/cancel", {"run_id": run_id})
    assert status == 200
    assert data["ok"] is True
    assert data["message"] == "Nothing was triggered."


def test_post_cancel_unknown_run(server):
    status, data = post(server, "/api/cancel", {"run_id": "doesnotexist"})
    assert status == 404


# ---------------------------------------------------------------------------
# Improvements: checklist, title, no alerts, script strings
# ---------------------------------------------------------------------------

def test_get_safe_has_checklist_and_title(server):
    """GET /?scenario=safe contains id="checklist", all five pass summaries, and correct <title>."""
    _, body, _ = get(server, "/?scenario=safe")
    assert 'id="checklist"' in body
    assert "Pipelines: all green" in body
    assert "Config diff: safe" in body
    assert "FC/ETL: clear" in body
    assert "Flyway: no unsafe migrations" in body
    assert "E2E scope: 3 folders" in body
    assert "<title>Is this deploy safe?</title>" in body


def test_get_unsafe_flag_flip_has_checklist_and_approve_hidden(server):
    """GET /?scenario=unsafe-flag-flip has id="checklist", blocked message, and approve hidden."""
    _, body, _ = get(server, "/?scenario=unsafe-flag-flip")
    assert 'id="checklist"' in body
    assert "GIT flag set, no rehydrate step found." in body
    assert 'id="approve" hidden' in body


def test_html_contains_no_alert(server):
    """The HTML source must not contain alert(."""
    _, body, _ = get(server, "/")
    assert "alert(" not in body


def test_script_contains_required_strings(server):
    """The script source contains the exact strings used for post-approve/cancel UI updates.

    Note: folder and cancel text are rendered by the script into #trigger-message and
    #e2e-folders after a successful approve/cancel API call — not server-rendered.
    """
    _, body, _ = get(server, "/")
    assert "E2E trigger written." in body
    assert "Nothing was triggered." in body
    assert "e2e-folders" in body

# ---------------------------------------------------------------------------
# Check cards
# ---------------------------------------------------------------------------

def test_get_safe_has_check_cards(server):
    """GET /?scenario=safe must have check cards with id=check-cards."""
    _, body, _ = get(server, "/?scenario=safe")
    assert 'id="check-cards"' in body
    assert 'class="check-card' in body
    # All five check cards are present
    assert "Pipeline Status" in body
    assert "Workflow-Config Diff" in body
    assert "FC/ETL Path" in body
    assert "Flyway Scan" in body
    assert "Playwright Map" in body


def test_get_safe_pass_cards_green_border(server):
    """Pass cards have card-pass CSS class."""
    _, body, _ = get(server, "/?scenario=safe")
    assert "card-pass" in body


def test_get_unsafe_flag_flip_blocked_card_red_border(server):
    """Blocked cards have card-blocked CSS class."""
    _, body, _ = get(server, "/?scenario=unsafe-flag-flip")
    assert "card-blocked" in body


def test_get_unsafe_flag_flip_shows_feature_flags_location(server):
    """The unsafe flag-flip page must show feature-flags.yaml in a location element."""
    _, body, _ = get(server, "/?scenario=unsafe-flag-flip")
    assert "feature-flags.yaml" in body


def test_get_unsafe_flag_flip_shows_rehydrate_snippet(server):
    """The unsafe flag-flip page must show the runbook quote inside a pre.snippet."""
    _, body, _ = get(server, "/?scenario=unsafe-flag-flip")
    assert 'class="snippet"' in body
    assert "rehydrate must run before flag flip to GIT" in body


def test_get_scan_form_present(server):
    """The page must contain form#scan with all required inputs."""
    _, body, _ = get(server, "/")
    assert 'id="scan"' in body
    assert 'id="workspace"' in body
    assert 'id="config"' in body
    assert 'id="repos"' in body
    assert 'id="ci-dir"' in body
    assert 'id="scan-run"' in body


# ---------------------------------------------------------------------------
# POST /api/scan
# ---------------------------------------------------------------------------

def test_post_scan_other_org_clean_returns_show_approve(server):
    """POST /api/scan on other-org clean workspace returns show_approve true."""
    status, data = post(server, "/api/scan", {
        "workspace": "fixtures/other-org/workspace",
        "config": "fixtures/other-org/org.yaml",
        "repos": "api",
        "ci_dir": "fixtures/other-org/ci",
    })
    assert status == 200
    assert data["show_approve"] is True
    assert data["checklist"]["release_id"] == "other-org+api"
    assert "run_id" in data


def test_post_scan_invalid_args_returns_400(server):
    """POST /api/scan with missing workspace returns 400."""
    status, data = post(server, "/api/scan", {
        "config": "fixtures/other-org/org.yaml",
        "repos": "api",
    })
    assert status == 400
    assert data["message"] == "invalid scan arguments"


def test_post_scan_missing_workspace_dir_returns_400(server):
    """POST /api/scan with nonexistent workspace returns 400."""
    status, data = post(server, "/api/scan", {
        "workspace": "/does/not/exist",
        "config": "fixtures/other-org/org.yaml",
        "repos": "api",
    })
    assert status == 400
    assert data["message"] == "invalid scan arguments"

