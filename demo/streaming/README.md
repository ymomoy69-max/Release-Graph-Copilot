# Streaming platform demo

Eight FastAPI microservices (same shape as `demo/ecommerce`, different domain):

| Service | Role |
|---------|------|
| `content-service` | Title catalog |
| `entitlement-service` | Concurrent stream slots |
| `billing-service` | Charges (+ demo failure mode) |
| `session-service` | Playback orchestration |
| `notification-service` | Email/push |
| `recommendation-service` | Personalized rows |
| `api-gateway` | Public API |
| `frontend` | Catalog UI |

```bash
python demo/streaming/run_all.py
```

ReleaseGraph seeds this tree as the **Streaming Platform** project (sidebar project selector).
