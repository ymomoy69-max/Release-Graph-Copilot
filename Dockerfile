FROM node:20-bookworm-slim AS web-builder
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS app
WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml README.md ./
RUN pip install --upgrade pip \
 && pip install -e ".[postgres]"

COPY releasegraph/ ./releasegraph/
COPY rgc/ ./rgc/
COPY demo/ ./demo/
COPY fixtures/ ./fixtures/
COPY docs/ ./docs/
COPY scripts/ ./scripts/
COPY --from=web-builder /app/web/dist/ ./web/dist/

RUN mkdir -p /app/data

CMD ["python", "-m", "releasegraph.cli", "serve_api"]
