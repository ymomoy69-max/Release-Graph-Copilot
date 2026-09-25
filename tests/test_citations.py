"""Tests for the citation engine."""
import pytest
from rgc.citations import attach_citations, _search_citation, _load_rules
from rgc.models import Finding, CheckResult, CHECK_ORDER, CHECK_NAMES
from rgc.manifest import Release, Overlay
from rgc.workspace import WorkspaceView


def make_pass_check(check_id):
    return CheckResult(
        id=check_id,
        name=CHECK_NAMES[check_id],
        status="pass",
        summary="ok",
        findings=(),
    )


def make_release_with_overlays(overlays=()):
    return Release(
        id="test",
        question="q",
        repos=("app-backend",),
        graph_path="fixtures/graph/deploy-graph.yaml",
        ci_dir="fixtures/ci-status/green",
        changed_paths=(),
        overlays=tuple(overlays),
        workspace_root="fixtures/workspace",
    )


def make_flip_finding():
    return Finding(
        severity="block",
        code="flag_flip_without_rehydrate",
        message="GIT flag set, no rehydrate step found.",
        repos=("app-backend", "data-pipeline"),
        suggested_fix="Add rehydrate step before flag flip.",
        citation=None,
    )


# ---------------------------------------------------------------------------
# Citation lookup
# ---------------------------------------------------------------------------

def test_citation_found_line_number():
    """The runbook line number equals what a search finds."""
    rules = _load_rules()
    rule = next(r for r in rules if r["code"] == "flag_flip_without_rehydrate")
    release = make_release_with_overlays()
    ws = WorkspaceView(release)
    cit = _search_citation(ws, rule)
    assert cit is not None

    # Verify that the line number matches an actual search
    with open(rule["file"]) as f:
        lines = f.readlines()
    quote = rule["quote"]
    expected_line = next(i + 1 for i, line in enumerate(lines) if line.rstrip() == quote)
    assert cit.line == expected_line


def test_citation_not_found_if_quote_above_heading():
    """A quote that occurs only above heading 3.2 yields citation_not_found."""
    # Overlay the README with the quote ABOVE the heading
    content = (
        "rehydrate must run before flag flip to GIT\n"
        "\n"
        "### 3.2 GIT storage\n"
        "\n"
        "Some other text.\n"
    )
    release = make_release_with_overlays([
        Overlay("ops-runbooks/README.md", content)
    ])
    ws = WorkspaceView(release)
    rules = _load_rules()
    rule = next(r for r in rules if r["code"] == "flag_flip_without_rehydrate")
    cit = _search_citation(ws, rule)
    assert cit is None


def test_citation_attached_to_finding():
    """Citation is attached when runbook is intact."""
    flip_finding = make_flip_finding()
    fc_check = CheckResult(
        id="fc_etl",
        name=CHECK_NAMES["fc_etl"],
        status="blocked",
        summary=flip_finding.message,
        findings=(flip_finding,),
    )
    other_checks = [make_pass_check(cid) for cid in CHECK_ORDER if cid != "fc_etl"]

    release = make_release_with_overlays()
    ws = WorkspaceView(release)

    all_checks = []
    for cid in CHECK_ORDER:
        if cid == "fc_etl":
            all_checks.append(fc_check)
        else:
            all_checks.append(make_pass_check(cid))

    updated, block_report = attach_citations(all_checks, ws)

    fc_updated = next(c for c in updated if c.id == "fc_etl")
    flip_updated = next(f for f in fc_updated.findings if f.code == "flag_flip_without_rehydrate")
    assert flip_updated.citation is not None
    assert flip_updated.citation.section == "3.2"
    assert flip_updated.citation.quote == "rehydrate must run before flag flip to GIT"
    assert block_report is not None
    assert "BLOCKED" in block_report


def test_citation_not_found_adds_extra_finding():
    """Missing runbook → citation_not_found finding, no quote in output."""
    content = "# Ops runbook\n\n## 1. Overview\n\nThis runbook has no flag-flip rule.\n"
    release = make_release_with_overlays([
        Overlay("ops-runbooks/README.md", content)
    ])
    ws = WorkspaceView(release)

    flip_finding = make_flip_finding()
    fc_check = CheckResult(
        id="fc_etl",
        name=CHECK_NAMES["fc_etl"],
        status="blocked",
        summary=flip_finding.message,
        findings=(flip_finding,),
    )

    all_checks = [
        make_pass_check(cid) if cid != "fc_etl" else fc_check
        for cid in CHECK_ORDER
    ]

    updated, block_report = attach_citations(all_checks, ws)
    fc_updated = next(c for c in updated if c.id == "fc_etl")
    codes = [f.code for f in fc_updated.findings]
    assert "citation_not_found" in codes
    assert block_report is None

    # The quote must not appear in any field
    import json
    text = json.dumps([c.to_dict() for c in updated])
    assert "rehydrate must run before flag flip to GIT" not in text


def test_no_citation_rules_for_passing_check():
    """Checks with no matching rule codes pass through unchanged."""
    checks = [make_pass_check(cid) for cid in CHECK_ORDER]
    release = make_release_with_overlays()
    ws = WorkspaceView(release)
    updated, block_report = attach_citations(checks, ws)
    assert block_report is None
    for check in updated:
        assert check.findings == ()
