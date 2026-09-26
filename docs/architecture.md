# Architecture

## Layers

| Layer | Location | Responsibility |
|-------|----------|----------------|
| Release safety engine | `rgc/` | Deterministic deploy checks (pipelines, flyway, FC/ETL, org YAML) |
| Platform API | `releasegraph/` | REST API, auth, DB, risk engine, copilot tools, simulator |
| Web UI | `web/` | React SPA — dashboard, releases, graph, incidents, copilot |
| Demo microservices | `demo/ecommerce/` | Simulated storefront services for failure demos |

## Data flow

```
Engineering events (seed / simulator) → PostgreSQL or SQLite
       ↓
FastAPI services (releases, graph, incidents, audit)
       ↓
React UI + Copilot (tool-backed answers)
```

The original **rgc** CLI and `python -m rgc serve` UI remain available for org workspace scans.

## IBM Bob

The initial `rgc` checker suite and fixture scenarios were built per the IBM Bob 2.0 execution plan. The platform layer extends that with product APIs, demo data, and a SaaS-style UI while preserving the checker engine.
