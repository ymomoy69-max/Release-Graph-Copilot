# Demo scenarios

All scenarios use **seeded database data** and labeled **simulators** (not real cloud integrations).

## Healthy release (default seed)

Release `v2.8.0` is deployed with green builds/tests and MEDIUM risk factors.

## Payment failure

1. Sign in to the web UI.
2. Incidents → **Simulate payment-service failure**.
3. Copilot → “Investigate this incident”.
4. Audit log shows human and AI actions.

## Rollback

1. Open release `v2.8.0`.
2. Click **Rollback release** and confirm.
3. Audit log records `release.rollback`.

## Dependency blast radius

Copilot → “What could be affected by this release?” or ask about `payment-service`.

## CI/CD simulator

`POST /api/v1/simulator/deploy` with `release_id` (requires auth).

## Demo e-commerce APIs

```bash
uvicorn demo.ecommerce.main:app --port 8081
curl -X POST http://localhost:8081/admin/failure-mode -H 'Content-Type: application/json' -d '{"enabled":true}'
```
