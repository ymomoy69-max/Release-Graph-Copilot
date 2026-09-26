#!/usr/bin/env python3
"""Start all e-commerce demo microservices (local dev)."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SERVICES: list[tuple[str, str, int, dict[str, str]]] = [
    (
        "product-service",
        "demo.ecommerce.services.product.app:app",
        8101,
        {"SERVICE_NAME": "product-service"},
    ),
    (
        "inventory-service",
        "demo.ecommerce.services.inventory.app:app",
        8102,
        {"SERVICE_NAME": "inventory-service"},
    ),
    (
        "payment-service",
        "demo.ecommerce.services.payment.app:app",
        8103,
        {"SERVICE_NAME": "payment-service"},
    ),
    (
        "notification-service",
        "demo.ecommerce.services.notification.app:app",
        8105,
        {"SERVICE_NAME": "notification-service"},
    ),
    (
        "order-service",
        "demo.ecommerce.services.order.app:app",
        8104,
        {
            "SERVICE_NAME": "order-service",
            "PRODUCT_SERVICE_URL": "http://127.0.0.1:8101",
            "INVENTORY_SERVICE_URL": "http://127.0.0.1:8102",
            "PAYMENT_SERVICE_URL": "http://127.0.0.1:8103",
            "NOTIFICATION_SERVICE_URL": "http://127.0.0.1:8105",
        },
    ),
    (
        "api-gateway",
        "demo.ecommerce.services.api_gateway.app:app",
        8080,
        {
            "SERVICE_NAME": "api-gateway",
            "PRODUCT_SERVICE_URL": "http://127.0.0.1:8101",
            "INVENTORY_SERVICE_URL": "http://127.0.0.1:8102",
            "PAYMENT_SERVICE_URL": "http://127.0.0.1:8103",
            "ORDER_SERVICE_URL": "http://127.0.0.1:8104",
            "NOTIFICATION_SERVICE_URL": "http://127.0.0.1:8105",
        },
    ),
    (
        "frontend",
        "demo.ecommerce.services.frontend.app:app",
        8082,
        {"SERVICE_NAME": "frontend", "API_GATEWAY_URL": "http://127.0.0.1:8080"},
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
    print("\nDemo stack ready:")
    print("  Storefront UI:  http://127.0.0.1:8082/")
    print("  API gateway:    http://127.0.0.1:8080/health")
    print("  order-service:  http://127.0.0.1:8104/health")
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
