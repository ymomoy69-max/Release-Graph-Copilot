FROM python:3.12-slim AS builder
WORKDIR /app
COPY pyproject.toml README.md ./
COPY rgc ./rgc
COPY releasegraph ./releasegraph
RUN pip install --no-cache-dir .

FROM python:3.12-slim
RUN useradd -m -u 1000 appuser
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY rgc ./rgc
COPY releasegraph ./releasegraph
USER appuser
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "releasegraph.main:app", "--host", "0.0.0.0", "--port", "8000"]
