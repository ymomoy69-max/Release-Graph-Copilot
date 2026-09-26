from releasegraph.models import Release, ReleaseStatus
from releasegraph.risk_engine import blast_radius, calculate_release_risk


def test_blast_radius_transitive():
    deps = [(1, 2), (2, 3)]  # 1 depends on 2, 2 depends on 3
    assert blast_radius({3}, deps) == {1, 2, 3}


def test_risk_level_medium_for_production_multi_service():
    release = Release(
        id=1,
        project_id=1,
        version="v1",
        status=ReleaseStatus.READY,
        rollback_available=True,
    )
    services = [type("S", (), {"criticality": "high"})() for _ in range(3)]
    result = calculate_release_risk(
        release, services, commit_count=8, pr_count=3,
        failed_builds=0, failed_tests=0, production=True,
        dependency_depth=2, recent_incidents=0,
    )
    assert result.level in ("MEDIUM", "HIGH")
    assert result.factors


def test_clean_workspace_scan_lowers_risk():
    release = Release(
        id=1,
        project_id=1,
        version="1.0.0",
        status=ReleaseStatus.DEPLOYED,
        rollback_available=False,
    )
    services = [type("S", (), {"criticality": "high"})() for _ in range(4)]
    with_issues = calculate_release_risk(
        release,
        services,
        commit_count=0,
        pr_count=0,
        failed_builds=0,
        failed_tests=0,
        production=True,
        dependency_depth=2,
        recent_incidents=0,
        scan_issue_count=3,
        scan_blocking_count=0,
    )
    clean = calculate_release_risk(
        release,
        services,
        commit_count=0,
        pr_count=0,
        failed_builds=0,
        failed_tests=0,
        production=True,
        dependency_depth=2,
        recent_incidents=0,
        scan_issue_count=0,
        scan_blocking_count=0,
    )
    assert clean.score < with_issues.score
    assert clean.level in ("LOW", "MEDIUM")
    assert any(f[0] == "clean_workspace" for f in clean.factors)
