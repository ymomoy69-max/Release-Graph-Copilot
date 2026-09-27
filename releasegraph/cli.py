"""CLI entrypoints for the platform."""
from __future__ import annotations

import argparse
import os


def serve_api() -> None:
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("releasegraph.main:app", host="0.0.0.0", port=port, reload=False)


def main() -> None:
    parser = argparse.ArgumentParser(prog="releasegraph")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="Start API server")
    sub.add_parser("seed", help="Seed demo database")
    scan_p = sub.add_parser("scan", help="Scan a workspace (SDK, no server)")
    scan_p.add_argument("workspace")
    scan_p.add_argument("--json", action="store_true")
    scan_p.add_argument("--llm", action="store_true")
    args = parser.parse_args()
    if args.cmd == "serve":
        serve_api()
    elif args.cmd == "seed":
        from releasegraph.seed import seed
        seed()
    elif args.cmd == "scan":
        from releasegraph.sdk import main as sdk_main

        raise SystemExit(sdk_main([args.workspace] + (["--json"] if args.json else []) + (["--llm"] if args.llm else [])))
    else:
        parser.print_help()
