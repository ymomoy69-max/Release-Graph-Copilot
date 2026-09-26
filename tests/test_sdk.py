"""SDK and graph insight — no server required for analyze_workspace."""
from pathlib import Path

from releasegraph.insight_core import blast_names, build_insight
from releasegraph.sdk import analyze_workspace, main as sdk_main


def test_blast_follows_callers():
    pairs = [("order-service", "payment-service"), ("api-gateway", "order-service"), ("frontend", "api-gateway")]
    names = blast_names("payment-service", pairs)
    assert names[0] == "payment-service"
    assert "order-service" in names
    assert "frontend" in names


def test_insight_marks_breaking_edge():
    insight = build_insight(
        services=[{"name": "order-service"}, {"name": "payment-service"}],
        dependencies=[{"from": "order-service", "to": "payment-service"}],
        issues=[{"service": "payment-service", "code": "hardcoded_secret", "severity": "high", "file": "app.py", "line": 1}],
    )
    assert insight["broken_services"] == ["payment-service"]
    assert insight["broken_links"][0]["from"] == "order-service"
    assert insight["broken_links"][0]["to"] == "payment-service"
    pay = next(n for n in insight["nodes"] if n["label"] == "payment-service")
    assert pay["status"] == "broken"
    order = next(n for n in insight["nodes"] if n["label"] == "order-service")
    assert order["status"] == "at_risk"
    assert "problem service" in (order.get("headline") or "").lower() or "breaking" in (order.get("if_breaks") or "")


def test_sdk_scans_demo_ecommerce():
    root = str(Path(__file__).resolve().parent.parent / "demo" / "ecommerce")
    result = analyze_workspace(root)
    assert not result.get("error")
    assert result["broken_links"]
    pairs = {(l["from"], l["to"]) for l in result["broken_links"]}
    assert ("order-service", "payment-service") in pairs
    assert "payment-service" in result["broken_services"]


def test_sdk_cli_text(capsys):
    root = str(Path(__file__).resolve().parent.parent / "demo" / "ecommerce")
    code = sdk_main([root])
    assert code == 0
    out = capsys.readouterr().out
    assert "payment-service" in out
    assert "breaking" in out
