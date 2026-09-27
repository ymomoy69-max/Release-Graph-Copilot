"""CLI entrypoints for the platform."""
from __future__ import annotations

import argparse
import os
import sys


def serve_api() -> None:
    import uvicorn

    # Railway public networking target port is 8080; honor $PORT when set.
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("releasegraph.main:app", host="0.0.0.0", port=port, reload=False)


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Deploy docs / Dockerfile historically pass "serve_api".
    if not argv or argv[0] in ("serve", "serve_api"):
        serve_api()
        return

    parser = argparse.ArgumentParser(prog="releasegraph")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="Start API server")
    sub.add_parser("serve_api", help="Alias for serve (Railway / Docker)")
    sub.add_parser("seed", help="Seed demo database")
    scan_p = sub.add_parser("scan", help="Scan a workspace (SDK, no server)")
    scan_p.add_argument("workspace")
    scan_p.add_argument("--json", action="store_true")
    scan_p.add_argument("--llm", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd in ("serve", "serve_api"):
        serve_api()
    elif args.cmd == "seed":
        from releasegraph.seed import seed

        seed()
    elif args.cmd == "scan":
        from releasegraph.sdk import main as sdk_main

        raise SystemExit(
            sdk_main(
                [args.workspace]
                + (["--json"] if args.json else [])
                + (["--llm"] if args.llm else [])
            )
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
