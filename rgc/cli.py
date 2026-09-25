"""
CLI for Release Graph Copilot.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from rgc import gate
from rgc.models import format_checklist_json
from rgc.orchestrator import run_release, run_release_file


_SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9_./-]+$")


def _build_scan_release(args):
    """Build a Release object from direct scan CLI arguments."""
    from rgc.manifest import Release, Overlay, DEFAULT_ORG_CONFIG
    from rgc.org_config import load_org_config_for_release
    from rgc.models import Checklist

    # Load org config to get graph_path, ci_dir, etc.
    config_path = args.config
    # We load org first to get graph/ci_dir defaults
    org_result = load_org_config_for_release(config_path, "scan")
    if isinstance(org_result, Checklist):
        return None, org_result, None

    org = org_result

    # Repos from --repos (deduplicate, preserve order)
    raw_repos = [r.strip() for r in args.repos.split(",") if r.strip()]
    repos = list(dict.fromkeys(raw_repos))  # deduplicate preserving order

    ci_dir = args.ci_dir if args.ci_dir else org.ci_dir
    workspace_root = args.workspace

    # Changed paths
    changed_paths: tuple[str, ...] = ()
    if hasattr(args, "changed_paths") and args.changed_paths:
        changed_paths = tuple(p.strip() for p in args.changed_paths.split(",") if p.strip())

    # Overlays
    overlays: list[Overlay] = []
    if hasattr(args, "overlays") and args.overlays:
        try:
            with open(args.overlays) as f:
                raw_overlays = json.load(f)
        except (OSError, json.JSONDecodeError):
            # Return invalid_manifest
            from rgc.manifest import _make_validation_checklist
            cl = _make_validation_checklist(
                "scan", "Is this deploy safe?",
                "invalid_manifest", "The release manifest is invalid.",
                "Fix the release manifest JSON and re-run the check.",
            )
            return None, cl, None
        for item in raw_overlays:
            opath = item.get("path", "")
            ocontent = item.get("content", "")
            if (opath.startswith("/") or ".." in opath.split("/")
                    or not _SAFE_PATH_RE.match(opath)):
                from rgc.manifest import _make_validation_checklist
                cl = _make_validation_checklist(
                    "scan", "Is this deploy safe?",
                    "unsafe_path", "Overlay path is not allowed.",
                    "Use a relative path inside the workspace.",
                )
                return None, cl, None
            overlays.append(Overlay(path=opath, content=ocontent))

    # Release id = org name + sorted repos joined by +
    release_id = org.name + "+" + "+".join(sorted(repos))

    release = Release(
        id=release_id,
        question="Is this deploy safe?",
        repos=tuple(repos),
        graph_path=org.graph,
        ci_dir=ci_dir,
        changed_paths=changed_paths,
        overlays=tuple(overlays),
        workspace_root=workspace_root,
        config_path=config_path,
    )
    return release, None, org


def cmd_check(args) -> int:
    # Validate mutual exclusion of --release and --workspace
    has_release = bool(getattr(args, "release", None))
    has_workspace = bool(getattr(args, "workspace", None))
    has_config = bool(getattr(args, "config", None))
    has_repos = bool(getattr(args, "repos", None))

    if has_release and (has_workspace or has_config or has_repos):
        print("invalid scan arguments", file=sys.stderr)
        return 1

    if (has_workspace or has_config or has_repos) and not (has_workspace and has_config and has_repos):
        print("invalid scan arguments", file=sys.stderr)
        return 1

    if has_workspace:
        # Direct scan mode
        import os
        if not os.path.isdir(args.workspace):
            # missing_workspace error
            from rgc.org_config import _make_invalid_checklist
            checklist = _make_invalid_checklist(
                "scan", "missing_workspace",
                "Workspace directory is missing.",
                "Ensure the workspace directory exists before scanning.",
            )
            checklist_dict = checklist.to_dict()
            print(format_checklist_json(checklist), end="")
            gate.check(checklist_dict, args.out)
            return 1

        release, error_cl, org = _build_scan_release(args)
        if error_cl is not None:
            checklist_dict = error_cl.to_dict()
            print(format_checklist_json(error_cl), end="")
            gate.check(checklist_dict, args.out)
            return 1

        # empty_release
        if not release.repos:
            from rgc.manifest import _make_validation_checklist
            cl = _make_validation_checklist(
                release.id, "Is this deploy safe?",
                "empty_release",
                "Name at least one repository in the release.",
                "Name at least one repository in the release.",
            )
            checklist_dict = cl.to_dict()
            print(format_checklist_json(cl), end="")
            gate.check(checklist_dict, args.out)
            return 1

        try:
            checklist = run_release(release, org_config=org, timeout_seconds=args.timeout_seconds)
        except Exception as exc:
            print(json.dumps({"error": str(exc)}, indent=2) + "\n")
            return 1
    else:
        # Release file mode
        try:
            checklist = run_release_file(args.release, timeout_seconds=args.timeout_seconds)
        except Exception as exc:
            print(json.dumps({"error": str(exc)}, indent=2) + "\n")
            return 1

    checklist_dict = checklist.to_dict()
    out = format_checklist_json(checklist)
    print(out, end="")

    gate.check(checklist_dict, args.out)

    return 0 if checklist.verdict == "go" else 1


def cmd_approve(args) -> int:
    exit_code, stdout, stderr = gate.approve(args.run)
    if stdout:
        print(stdout, end="")
    if stderr:
        print(stderr, end="", file=sys.stderr)
    return exit_code


def cmd_cancel(args) -> int:
    exit_code, stdout, stderr = gate.cancel(args.run)
    if stdout:
        print(stdout, end="")
    if stderr:
        print(stderr, end="", file=sys.stderr)
    return exit_code


def cmd_serve(args) -> int:
    if args.host != "127.0.0.1":
        print("host must be loopback", file=sys.stderr)
        return 1
    from rgc.server import run_server
    run_server(host=args.host, port=args.port)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="rgc", description="Release Graph Copilot")
    subparsers = parser.add_subparsers(dest="command")

    # check
    check_p = subparsers.add_parser("check")
    check_p.add_argument("--release", default=None)
    check_p.add_argument("--workspace", default=None)
    check_p.add_argument("--config", default=None)
    check_p.add_argument("--repos", default=None)
    check_p.add_argument("--ci-dir", default=None, dest="ci_dir")
    check_p.add_argument("--overlays", default=None)
    check_p.add_argument("--changed-paths", default=None, dest="changed_paths")
    check_p.add_argument("--out", required=True)
    check_p.add_argument("--timeout-seconds", type=float, default=5.0, dest="timeout_seconds")

    # approve
    approve_p = subparsers.add_parser("approve")
    approve_p.add_argument("--run", required=True)

    # cancel
    cancel_p = subparsers.add_parser("cancel")
    cancel_p.add_argument("--run", required=True)

    # serve
    serve_p = subparsers.add_parser("serve")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8765)

    args = parser.parse_args()

    if args.command == "check":
        sys.exit(cmd_check(args))
    elif args.command == "approve":
        sys.exit(cmd_approve(args))
    elif args.command == "cancel":
        sys.exit(cmd_cancel(args))
    elif args.command == "serve":
        sys.exit(cmd_serve(args))
    else:
        parser.print_help()
        sys.exit(1)
