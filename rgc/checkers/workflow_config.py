"""
Workflow-Config Diff checker.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from rgc.models import Finding, CheckResult

if TYPE_CHECKING:
    from rgc.manifest import Release
    from rgc.workspace import WorkspaceView
    from rgc.org_config import OrgConfig


def run(
    release: "Release",
    closure: frozenset[str],
    workspace: "WorkspaceView",
    catalog: frozenset[str],
    org_config: "OrgConfig | None" = None,
) -> CheckResult:
    if org_config is None:
        from rgc.manifest import DEFAULT_ORG_CONFIG
        from rgc.org_config import OrgConfig, load_org_config

        loaded = load_org_config(DEFAULT_ORG_CONFIG)
        if isinstance(loaded, OrgConfig):
            org_config = loaded

    workflow_config_dir = org_config.workflow_config_dir if org_config else "workflow-configs"
    contract_path = (
        org_config.workflow_contract if org_config
        else "rules-engine/contract/workflow-contract.yaml"
    )

    findings: list[Finding] = []

    # Collect overlays under workflow_config_dir/, last overlay wins per path
    prefix = workflow_config_dir.rstrip("/") + "/"
    wf_overlay_map: dict[str, tuple[str, str]] = {}  # path -> (path, content)
    for o in release.overlays:
        if o.path.startswith(prefix):
            wf_overlay_map[o.path] = (o.path, o.content)

    if not wf_overlay_map:
        return CheckResult.from_findings("workflow_config", [])

    # Load contract once
    contract = _load_contract(workspace, contract_path, findings)
    if contract is None:
        return CheckResult.from_findings("workflow_config", findings)

    required = contract.get("required", [])
    allowed_versions = contract.get("allowed_versions", [])
    fields = contract.get("fields", {})

    for overlay_path, content in wf_overlay_map.values():
        _check_overlay(content, overlay_path, required, allowed_versions, fields, findings)

    return CheckResult.from_findings("workflow_config", findings)


def _load_contract(workspace: "WorkspaceView", contract_path: str, findings: list[Finding]) -> dict | None:
    try:
        text = workspace.read_text(contract_path)
    except FileNotFoundError:
        findings.append(Finding(
            severity="block",
            code="malformed_yaml",
            message="Workflow contract file is missing.",
            repos=(),
            suggested_fix="Fix the workflow config YAML and re-run the check.",
            citation=None,
        ))
        return None

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        findings.append(Finding(
            severity="block",
            code="malformed_yaml",
            message="Invalid workflow YAML.",
            repos=(),
            suggested_fix="Fix the workflow config YAML and re-run the check.",
            citation=None,
        ))
        return None

    if not isinstance(data, dict):
        findings.append(Finding(
            severity="block",
            code="malformed_yaml",
            message="Invalid workflow YAML.",
            repos=(),
            suggested_fix="Fix the workflow config YAML and re-run the check.",
            citation=None,
        ))
        return None

    return data


def _check_overlay(
    content: str,
    overlay_path: str,
    required: list,
    allowed_versions: list,
    fields: dict,
    findings: list[Finding],
) -> None:
    location = f"{overlay_path}:1"

    # 1. Parse YAML
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        findings.append(Finding(
            severity="block",
            code="malformed_yaml",
            message="Invalid workflow YAML.",
            repos=(),
            suggested_fix="Fix the workflow config YAML and re-run the check.",
            citation=None,
            location=location,
            snippet=content.splitlines()[0] if content.strip() else None,
        ))
        return

    if not isinstance(data, dict):
        findings.append(Finding(
            severity="block",
            code="malformed_yaml",
            message="Invalid workflow YAML.",
            repos=(),
            suggested_fix="Fix the workflow config YAML and re-run the check.",
            citation=None,
            location=location,
            snippet=None,
        ))
        return

    # 3. Required keys
    for key in required:
        if key not in data:
            findings.append(Finding(
                severity="block",
                code="missing_required",
                message=f"Workflow config is missing required key {key}.",
                repos=(),
                suggested_fix="Restore required keys and use contract version 1 with the documented types.",
                citation=None,
                location=location,
                snippet=content.splitlines()[0] if content.strip() else None,
            ))

    # 4. Version check — only when present
    if "version" in data:
        value = data["version"]
        if type(value) is not int:  # noqa: E721 — booleans excluded
            findings.append(Finding(
                severity="block",
                code="type_mismatch",
                message="Workflow config field version has the wrong type.",
                repos=(),
                suggested_fix="Restore required keys and use contract version 1 with the documented types.",
                citation=None,
                location=location,
                snippet=None,
            ))
        elif value not in allowed_versions:
            findings.append(Finding(
                severity="block",
                code="unknown_version",
                message="Workflow config version is not allowed.",
                repos=(),
                suggested_fix="Restore required keys and use contract version 1 with the documented types.",
                citation=None,
                location=location,
                snippet=None,
            ))

    # 5. Field type enforcement for present fields
    for field_name, field_type in fields.items():
        if field_name == "version":
            continue  # already handled above
        if field_name not in data:
            continue
        value = data[field_name]
        if field_type == "string":
            if not isinstance(value, str):
                findings.append(Finding(
                    severity="block",
                    code="type_mismatch",
                    message=f"Workflow config field {field_name} has the wrong type.",
                    repos=(),
                    suggested_fix="Restore required keys and use contract version 1 with the documented types.",
                    citation=None,
                    location=location,
                    snippet=None,
                ))
        elif field_type == "int":
            if type(value) is not int:  # noqa: E721
                findings.append(Finding(
                    severity="block",
                    code="type_mismatch",
                    message=f"Workflow config field {field_name} has the wrong type.",
                    repos=(),
                    suggested_fix="Restore required keys and use contract version 1 with the documented types.",
                    citation=None,
                    location=location,
                    snippet=None,
                ))
        elif field_type == "list":
            if not isinstance(value, list):
                findings.append(Finding(
                    severity="block",
                    code="type_mismatch",
                    message=f"Workflow config field {field_name} has the wrong type.",
                    repos=(),
                    suggested_fix="Restore required keys and use contract version 1 with the documented types.",
                    citation=None,
                    location=location,
                    snippet=None,
                ))
