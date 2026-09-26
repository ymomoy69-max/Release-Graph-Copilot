"""Service URLs for local demo (override with env vars)."""
from __future__ import annotations

import os

CONTENT_SERVICE_URL = os.getenv("CONTENT_SERVICE_URL", "http://127.0.0.1:8201")
ENTITLEMENT_SERVICE_URL = os.getenv("ENTITLEMENT_SERVICE_URL", "http://127.0.0.1:8202")
BILLING_SERVICE_URL = os.getenv("BILLING_SERVICE_URL", "http://127.0.0.1:8203")
SESSION_SERVICE_URL = os.getenv("SESSION_SERVICE_URL", "http://127.0.0.1:8204")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://127.0.0.1:8205")
RECOMMENDATION_SERVICE_URL = os.getenv("RECOMMENDATION_SERVICE_URL", "http://127.0.0.1:8206")

SERVICE_NAME = os.getenv("SERVICE_NAME", "unknown")
