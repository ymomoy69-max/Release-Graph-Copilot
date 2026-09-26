#!/usr/bin/env python3
"""Start all streaming demo microservices (local dev)."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SERVICES: list[tuple[str, str, int, dict[str, str]]] = [
    ("content-service", "demo.streaming.services.content.app:app", 8201, {"SERVICE_NAME": "content-service"}),
    ("entitlement-service", "demo.streaming.services.entitlement.app:app", 8202, {"SERVICE_NAME": "entitlement-service"}),
    ("billing-service", "demo.streaming.services.billing.app:app", 8203, {"SERVICE_NAME": "billing-service"}),
    ("notification-service", "demo.streaming.services.notification.app:app", 8205, {"SERVICE_NAME": "notification-service"}),
    ("recommendation-service", "demo.streaming.services.recommendation.app:app", 8206, {"SERVICE_NAME": "recommendation-service"}),
    (
        "session-service",
        "demo.streaming.services.session.app:app",
        8204,
        {
            "SERVICE_NAME": "session-service",
            "CONTENT_SERVICE_URL": "http://127.0.0.1:8201",
            "ENTITLEMENT_SERVICE_URL": "http://127.0.0.1:8202",
            "BILLING_SERVICE_URL": "http://127.0.0.1:8203",
            "NOTIFICATION_SERVICE_URL": "http://127.0.0.1:8205",
        },
    ),
    (
        "api-gateway",
        "demo.streaming.services.api_gateway.app:app",
        8090,
        {
            "SERVICE_NAME": "api-gateway",
            "CONTENT_SERVICE_URL": "http://127.0.0.1:8201",
            "ENTITLEMENT_SERVICE_URL": "http://127.0.0.1:8202",
            "BILLING_SERVICE_URL": "http://127.0.0.1:8203",
            "SESSION_SERVICE_URL": "http://127.0.0.1:8204",
            "NOTIFICATION_SERVICE_URL": "http://127.0.0.1:8205",
            "RECOMMENDATION_SERVICE_URL": "http://127.0.0.1:8206",
        },
    ),
    (
        "frontend",
        "demo.streaming.services.frontend.app:app",
        8092,
        {"SERVICE_NAME": "frontend", "API_GATEWAY_URL": "http://127.0.0.1:8090"},
    ),
]

_procs: list[subprocess.Popen] = []


def _start() -> None:
    py = sys.executable
    for name, app, port, extra_env in SERVICES:
        env = os.environ.copy()
        env.update(extra_env)
        cmd = [py, "-m", "uvicorn", app, "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"]
        print(f"Starting {name} on :{port}")
        _procs.append(subprocess.Popen(cmd, cwd=ROOT, env=env))
    time.sleep(1.5)
    print("\nStreaming demo stack ready:")
    print("  Catalog UI:     http://127.0.0.1:8092/")
    print("  API gateway:    http://127.0.0.1:8090/health")
    print("  session-service: http://127.0.0.1:8204/health")
    print("\nCtrl+C to stop all.\n")


def _stop(*_args) -> None:
    for p in _procs:
        p.terminate()
    sys.exit(0)


def main() -> None:
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    _start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        _stop()


if __name__ == "__main__":
    main()
