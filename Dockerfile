# ---- Frontend (Vite) ----
FROM node:20-bookworm-slim AS web-builder
WORKDIR /app/web

# Install deps first for layer caching. Vite lives in devDependencies, so
# force-include them even when the host sets NODE_ENV=production.
COPY web/package.json web/package-lock.json ./
RUN npm ci --include=dev --no-audit --no-fund

COPY web/ ./
RUN npm run build && test -f dist/index.html

# ---- Backend (FastAPI) ----
FROM python:3.12-slim-bookworm AS app
WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    ENVIRONMENT=production \
    DEBUG=false \
    CORS_ORIGINS=* \
    RG_AI_DISABLE=false

COPY pyproject.toml README.md ./
COPY releasegraph/ ./releasegraph/
COPY rgc/ ./rgc/
COPY demo/ ./demo/
COPY fixtures/ ./fixtures/
COPY docs/ ./docs/
COPY scripts/ ./scripts/

RUN pip install --upgrade pip \
 && pip install -e "." \
 && mkdir -p /app/data

COPY --from=web-builder /app/web/dist/ ./web/dist/
RUN test -f /app/web/dist/index.html

# Railway service Target port is 8080; $PORT is injected at runtime.
ENV PORT=8080
EXPOSE 8080
# Console script from pyproject.toml → releasegraph.cli:serve_api
CMD ["releasegraph-api"]
