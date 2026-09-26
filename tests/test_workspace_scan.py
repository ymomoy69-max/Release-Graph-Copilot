"""Workspace scanner discovers connected microservices from disk."""
from pathlib import Path

from releasegraph.workspace_scan import scan_workspace


def test_scan_demo_ecommerce_discovers_connected_services():
    root = Path(__file__).resolve().parent.parent / "demo" / "ecommerce"
    scan = scan_workspace(str(root))
    names = {s["name"] for s in scan["services"]}
    assert "order-service" in names
    assert "payment-service" in names
    assert "api-gateway" in names or "frontend" in names
    pairs = {(d["from"], d["to"]) for d in scan["dependencies"]}
    assert ("order-service", "payment-service") in pairs
    codes = {i["code"] for i in scan["issues"]}
    assert "hardcoded_secret" in codes
    assert "http_no_timeout" in codes
    assert "swallowed_exception" in codes


def test_scan_missing_path():
    scan = scan_workspace("/this/path/does/not/exist-rgc")
    assert scan["error"] == "workspace_not_found"
    assert scan["services"] == []
