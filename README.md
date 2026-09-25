# Release Graph Copilot (rgc)

Answers one question: **Is it safe to deploy this release right now?**

See `IBM_BOB_2.0_EXECUTION_PLAN.md` for the full build spec.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Run a check

```bash
.venv/bin/python -m rgc check --release fixtures/releases/safe.json --out out/safe
```

## Approve

```bash
.venv/bin/python -m rgc approve --run out/safe
```

## Cancel

```bash
.venv/bin/python -m rgc cancel --run out/safe
```

## Start the UI

```bash
.venv/bin/python -m rgc serve --host 127.0.0.1 --port 8765
```

Then open http://127.0.0.1:8765/ in your browser.

## Scan a provided organization

Clone your organization's repos into one folder, write an org YAML that describes
them, and supply a directory of CI status JSON files — the tool does not call a
git host.

```bash
python3 -m rgc check \
  --workspace /path/to/org \
  --config /path/to/org.yaml \
  --repos api,web \
  --ci-dir /path/to/ci-status \
  --out out/scan
```

A direct scan reads the files as they are on disk; a proposed flag change must be
passed as an overlay using `--overlays overlays.json`.



## Run tests

```bash
.venv/bin/python -m pytest -q
```
