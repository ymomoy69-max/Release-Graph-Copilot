"""Deprecated monolith entrypoint — use run_all.py or docker-compose.demo.yml."""
from __future__ import annotations

import sys

if __name__ == "__main__":
    print(
        "The all-in-one demo/ecommerce/main.py is deprecated.\n"
        "Start separate microservices:\n"
        "  python demo/ecommerce/run_all.py\n"
        "Or:\n"
        "  docker compose -f docker-compose.demo.yml up --build\n",
        file=sys.stderr,
    )
    sys.exit(1)
