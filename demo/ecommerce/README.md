# E-commerce demo microservices

Separate processes (not one monolith file). **Simulator** — not production integrations.

## Services

| Service | Port | Role |
|---------|------|------|
| product-service | 8101 | Catalog |
| inventory-service | 8102 | Stock / reserve |
| payment-service | 8103 | Payments + failure mode |
| order-service | 8104 | Orchestrates HTTP calls to deps |
| notification-service | 8105 | Email/SMS simulation |
| api-gateway | 8080 | Store API facade |
| frontend | 8082 | Simple shop UI |

## Run locally

From repo root (with `.venv` and `pip install -e .`):

```bash
python demo/ecommerce/run_all.py
```

Open http://127.0.0.1:8082 — place an order, then enable **payment failure** and try again.

## Docker

```bash
docker compose -f docker-compose.demo.yml up --build
```

## Tie-in to ReleaseGraph

- Platform **seed** maps these service names to the release graph (`product-service`, `order-service`, …).
- **Release readiness** (`rgc`) scans your **deploy repos** under `fixtures/workspace` (or your clone) — that is separate from running this shop stack.
- Use both: run microservices for a live shop demo; run **Release readiness** to verify deploy safety before releasing those services.
