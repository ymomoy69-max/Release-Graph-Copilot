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
