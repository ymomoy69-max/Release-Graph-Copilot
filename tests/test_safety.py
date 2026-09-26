"""Safety gate: LLM cannot invent files or become the source of truth."""
from releasegraph.safety import apply_safety_gate


def test_engine_finding_kept_when_llm_invents_file():
    engine = [
        {
            "file": "services/payment/app.py",
            "line": 12,
            "service": "payment-service",
            "code": "hardcoded_secret",
            "problem": "Secret in source",
            "fix": "Use env var",
            "source": "workspace_scan",
            "severity": "high",
        }
    ]
    llm = [
        {
            "file": "totally/invented.py",
            "line": 1,
            "service": "payment-service",
            "code": "hardcoded_secret",
            "problem": "Made up",
            "fix": "Made up fix",
        }
    ]
    out, meta = apply_safety_gate(engine, llm)
    assert len(out) == 1
    assert out[0]["file"] == "services/payment/app.py"
    assert out[0]["llm_accepted"] is False
    assert out[0]["human_required"] is True
    assert out[0]["engine_fix"] == "Use env var"
    assert meta["engine_source_of_truth"] is True
    assert meta["llm_rejected"] == 1


def test_llm_may_rephrase_same_identity():
    engine = [
        {
            "file": "a.py",
            "line": 3,
            "service": "order-service",
            "code": "http_no_timeout",
            "problem": "No timeout",
            "consequences": "Hang",
            "fix": "Set timeout",
            "source": "workspace_scan",
        }
    ]
    llm = [
        {
            "file": "a.py",
            "line": 3,
            "service": "order-service",
            "code": "http_no_timeout",
            "problem": "Outbound client has no timeout",
            "consequences": "A hung dependency blocks callers",
            "fix": "Pass timeout=(2, 10) to httpx.Client",
        }
    ]
    out, meta = apply_safety_gate(engine, llm)
    assert out[0]["llm_accepted"] is True
    assert out[0]["file"] == "a.py"
    assert out[0]["llm_fix"] == "Pass timeout=(2, 10) to httpx.Client"
    assert out[0]["engine_fix"] == "Set timeout"
    assert meta["llm_accepted"] == 1


def test_llm_only_rows_are_dropped():
    engine = [{"file": "real.py", "line": 1, "code": "x", "fix": "a", "problem": "p"}]
    llm = [
        {"file": "real.py", "line": 1, "code": "x", "fix": "a", "problem": "p"},
        {"file": "ghost.py", "line": 9, "code": "y", "fix": "nope", "problem": "invented"},
    ]
    out, _meta = apply_safety_gate(engine, llm)
    assert [i["file"] for i in out] == ["real.py"]
