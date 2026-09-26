"""Deterministic release risk scoring."""
from __future__ import annotations

from dataclasses import dataclass

from releasegraph.models import DeploymentStatus, Release, Service


@dataclass(frozen=True)
class RiskResult:
    level: str  # LOW | MEDIUM | HIGH
    score: float
    factors: list[tuple[str, float, str]]


def calculate_release_risk(
    release: Release,
    services: list[Service],
    commit_count: int,
    pr_count: int,
    failed_builds: int,
    failed_tests: int,
    production: bool,
    dependency_depth: int,
    recent_incidents: int,
    *,
    scan_issue_count: int | None = None,
    scan_blocking_count: int | None = None,
) -> RiskResult:
    score = 0.0
    factors: list[tuple[str, float, str]] = []

    svc_count = len(services)
    if svc_count >= 4:
        score += 2.0
        factors.append(("services_changed", 2.0, f"{svc_count} services in release"))
    elif svc_count >= 2:
        score += 1.0
        factors.append(("services_changed", 1.0, f"{svc_count} services in release"))

    high_crit = sum(1 for s in services if s.criticality == "high")
    if high_crit:
        crit_score = min(high_crit * 1.5, 4.0)
        score += crit_score
        factors.append(
            ("critical_services", crit_score, f"{high_crit} high-criticality service(s)")
        )

    if commit_count > 10:
        score += 1.5
        factors.append(("commit_volume", 1.5, f"{commit_count} commits"))
    elif commit_count > 5:
        score += 0.75
        factors.append(("commit_volume", 0.75, f"{commit_count} commits"))

    if pr_count > 5:
        score += 1.0
        factors.append(("pr_volume", 1.0, f"{pr_count} pull requests"))

    if failed_builds:
        score += 3.0
        factors.append(("failed_builds", 3.0, f"{failed_builds} failed build(s)"))

    if failed_tests:
        score += 2.0
        factors.append(("failed_tests", 2.0, f"{failed_tests} failed test suite(s)"))

    if production:
        score += 1.5
        factors.append(("production_target", 1.5, "Production environment"))

    if dependency_depth > 1:
        score += dependency_depth * 0.5
        factors.append(
            ("dependency_depth", dependency_depth * 0.5, f"Dependency depth {dependency_depth}")
        )

    if recent_incidents:
        score += recent_incidents * 1.0
        factors.append(("recent_incidents", recent_incidents * 1.0, f"{recent_incidents} recent incident(s)"))

    if scan_blocking_count is not None and scan_issue_count is not None:
        if scan_blocking_count:
            bump = scan_blocking_count * 3.0
            score += bump
            factors.append(
                (
                    "scanner_blocking",
                    bump,
                    f"{scan_blocking_count} critical scanner finding(s) on disk",
                )
            )
        elif scan_issue_count:
            bump = scan_issue_count * 0.75
            score += bump
            factors.append(
                (
                    "scanner_findings",
                    bump,
                    f"{scan_issue_count} workspace scanner finding(s) on disk",
                )
            )
        else:
            score -= 4.0
            factors.append(
                ("clean_workspace", -4.0, "Workspace scan reports no code issues on disk")
            )

    if release.rollback_available:
        score -= 0.5
        factors.append(("rollback_available", -0.5, "Rollback available"))

    score = max(0.0, score)
    if score >= 5.0:
        level = "HIGH"
    elif score >= 2.5:
        level = "MEDIUM"
    else:
        level = "LOW"

    return RiskResult(level=level, score=round(score, 2), factors=factors)


def blast_radius(service_ids: set[int], deps: list[tuple[int, int]]) -> set[int]:
    """Return all services that depend on (transitively) any of service_ids."""
    # deps: (from_service_id, to_service_id) meaning from depends on to
    affected = set(service_ids)
    changed = True
    while changed:
        changed = False
        for frm, to in deps:
            if to in affected and frm not in affected:
                affected.add(frm)
                changed = True
    return affected
