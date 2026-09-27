FROM node:20-bookworm-slim AS web-builder
WORKDIR /app/web
COPY web/package.json web/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci || (echo "npm ci failed, falling back to npm install" && npm install); else npm install; fi
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS app
WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libpq-dev \
        libssl-dev \
        libffi-dev \
        curl \
        ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

COPY pyproject.toml README.md ./
RUN pip install --upgrade pip \
 && pip install -e ".[postgres]" || (echo "pip install extras failed, retrying without postgres extras" && pip install -e ".")

COPY releasegraph/ ./releasegraph/
COPY rgc/ ./rgc/
COPY demo/ ./demo/
COPY fixtures/ ./fixtures/
COPY docs/ ./docs/
COPY scripts/ ./scripts/
COPY --from=web-builder /app/web/dist/ ./web/dist/

RUN mkdir -p /app/data && \
    printf '%s\n' \
      '#!/bin/sh' \
      'set +e' \
      'echo "--- Railway deploy startup diagnostics ---"' \
      'echo "PORT=${PORT:-<unset>}"' \
      'echo "ENVIRONMENT=${ENVIRONMENT:-<unset>}"' \
      'echo "DEBUG=${DEBUG:-<unset>}"' \
      'echo "DATABASE_URL_SET=${DATABASE_URL:+yes}"' \
      'echo "JWT_SECRET_SET=${JWT_SECRET:+yes}"' \
      'echo "WEB_DIST_PRESENT=$([ -d /app/web/dist/assets ] && echo yes || echo NO_assets_dir)"' \
      'echo "PYTHONPATH=${PYTHONPATH:-<unset>}"' \
      'python -c "import releasegraph.cli, releasegraph.main, uvicorn, fastapi, sqlalchemy; print(\"python imports OK\")" 2>&1 | tail -5' \
      'python -c "import psycopg2; print(\"psycopg2 OK\")" 2>&1 | tail -3 || echo "psycopg2 not installed (fallback to sqlite only)"' \
      'echo "--- End diagnostics, starting uvicorn ---"' \
      'exec python -m releasegraph.cli serve_api' \
      > /app/entrypoint.sh && \
    chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
