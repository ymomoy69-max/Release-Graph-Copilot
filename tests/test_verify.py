"""Merge is allowed only after the workspace scanner no longer sees the finding."""
from types import SimpleNamespace

from releasegraph.verify import files_match, remaining_scan_hit, verify_fix_ready


def test_files_match_suffix():
    assert files_match("demo/ecommerce/services/payment/app.py", "services/payment/app.py")
    assert files_match("services/payment/app.py", "demo/ecommerce/services/payment/app.py")
    assert not files_match("services/order/app.py", "services/payment/app.py")


def test_remaining_scan_hit_same_file():
    p = SimpleNamespace(code="hardcoded_secret", file_path="services/payment/app.py")
    hit = remaining_scan_hit(
        [
            {
                "code": "hardcoded_secret",
                "file": "demo/ecommerce/services/payment/app.py",
                "line": 16,
            }
        ],
        p,
    )
    assert hit and hit["line"] == 16


def test_verify_blocks_until_line_is_gone(tmp_path):
    svc = tmp_path / "payment-service"
    svc.mkdir()
    app = svc / "app.py"
    app.write_text('token = "supersecretvalue"\n')

    class _Db:
        def get(self, *_a, **_k):
            return SimpleNamespace(workspace_path=str(tmp_path))

    p = SimpleNamespace(
        project_id=1,
        code="hardcoded_secret",
        file_path="payment-service/app.py",
    )
    dirty = verify_fix_ready(_Db(), p)
    assert dirty["ok"] is False
    assert dirty["present"] is True

    app.write_text('token = os.getenv("TOKEN")\n')
    clean = verify_fix_ready(_Db(), p)
    assert clean["ok"] is True
    assert clean["present"] is False
