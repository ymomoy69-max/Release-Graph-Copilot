"""
Orchestrator: runs the five checkers concurrently and assembles a Checklist.
"""
from __future__ import annotations

import concurrent.futures
import inspect
from typing import Callable, TYPE_CHECKING

from rgc.catalog import load_catalog
from rgc.citations import attach_citations
from rgc.graph import load_graph, compute_closure, topological_sort
from rgc.manifest import load_release, Release, DEFAULT_ORG_CONFIG
from rgc.models import (
    CheckResult, Checklist, E2EScope, Finding, CHECK_ORDER, CHECK_NAMES,
    format_checklist_json,
)
from rgc.org_config import load_org_config_for_release, OrgConfig
from rgc.workspace import WorkspaceView

if TYPE_CHECKING:
    pass


def _make_error_check(check_id: str, code: str, message: str, suggested_fix: str) -> CheckResult:
    finding = Finding(
        severity="block",
        code=code,
        message=message,
        repos=(),
        suggested_fix=suggested_fix,
        citation=None,
    )
    return CheckResult(
        id=check_id,
        name=CHECK_NAMES[check_id],
        status="blocked",
        summary=message,
        findings=(finding,),
    )


def _checker_accepts_org(checker_fn: Callable) -> bool:
    """Detect whether a checker accepts 5 args (with org_config) or 4 (legacy)."""
    try:
        sig = inspect.signature(checker_fn)
        return len(sig.parameters) >= 5
    except (ValueError, TypeError):
        return False


def run_release(
    release: Release,
    checkers: list[Callable] | None = None,
    timeout_seconds: float = 5.0,
    org_config: OrgConfig | None = None,
) -> Checklist:
    """Run the five checkers and return a Checklist."""
    from rgc.checkers import default_checkers

    if checkers is None:
        checkers = default_checkers()

    # Load org config if not provided
    if org_config is None:
        config_result = load_org_config_for_release(release.config_path, release.id)
        if isinstance(config_result, Checklist):
            return config_result
        org_config = config_result

    # Load catalog from org config
    catalog = load_catalog(org_config.catalog)

    # Graph path: release overrides org if it differs from the org graph
    graph_path = release.graph_path
    graph = load_graph(graph_path)
    closure = compute_closure(graph, list(release.repos))
    deploy_order = topological_sort(graph, closure)
    workspace = WorkspaceView(release)

    # Submit all checkers concurrently
    results_map: dict[str, CheckResult | None] = {cid: None for cid in CHECK_ORDER}
    e2e_scope: E2EScope | None = None

    def run_checker(checker_fn):
        if _checker_accepts_org(checker_fn):
            return checker_fn(release, closure, workspace, catalog, org_config)
        else:
            return checker_fn(release, closure, workspace, catalog)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_id: dict[concurrent.futures.Future, str] = {}
        for checker_fn, check_id in zip(checkers, CHECK_ORDER):
            future = executor.submit(run_checker, checker_fn)
            future_to_id[future] = check_id

        for future, check_id in future_to_id.items():
            try:
                result = future.result(timeout=timeout_seconds)
            except TimeoutError:
                results_map[check_id] = _make_error_check(
                    check_id,
                    "checker_timeout",
                    "Checker timed out.",
                    "Re-run the check. The checker did not finish before the timeout.",
                )
                continue
            except Exception as exc:
                results_map[check_id] = _make_error_check(
                    check_id,
                    "checker_error",
                    f"Checker failed: {exc}",
                    "Fix the checker failure and re-run the check.",
                )
                continue

            # playwright_map returns (CheckResult, E2EScope) when changed_paths is non-empty
            if isinstance(result, tuple):
                cr, scope = result
                results_map[check_id] = cr
                if check_id == "playwright_map":
                    e2e_scope = scope
            else:
                results_map[check_id] = result

    # Build checks in fixed order
    checks = tuple(results_map[cid] for cid in CHECK_ORDER)

    # Default e2e scope if playwright didn't provide one
    if e2e_scope is None:
        e2e_scope = E2EScope(folders=(), estimate_seconds=0, estimate_display="0s")

    # Build checklist (before citations)
    checklist = Checklist.build(
        release_id=release.id,
        question=release.question,
        checks=checks,
        deploy_order=tuple(deploy_order),
        e2e=e2e_scope,
    )

    # Run citation engine
    updated_checks, block_report = attach_citations(
        list(checklist.checks),
        workspace,
        org_config=org_config,
    )

    # Rebuild checklist with citation-updated checks
    final_checklist = Checklist.build(
        release_id=release.id,
        question=release.question,
        checks=tuple(updated_checks),
        deploy_order=tuple(deploy_order),
        e2e=e2e_scope,
        block_report=block_report,
    )

    return final_checklist


def run_release_file(path: str, timeout_seconds: float = 5.0) -> Checklist:
    """Load a manifest file and run the checkers, returning a Checklist."""
    from rgc.models import Checklist as ChecklistType

    result = load_release(path)

    # Validation error — result is already a Checklist
    if isinstance(result, ChecklistType):
        return result

    return run_release(result, timeout_seconds=timeout_seconds)
