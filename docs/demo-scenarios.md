# Demo scenarios (workspace-driven)

All flows read **real paths on disk**, the **demo shop** (optional), and **database rows** — no seeded fake releases or preset buttons.

## Prerequisites

```bash
cd /path/to/Release-Graph-Copilot
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m releasegraph.seed --reset
./scripts/dev-all.sh
# UI http://127.0.0.1:5173 — admin@acme.demo / admin123!
# Shop http://127.0.0.1:8082
```

Or: `./scripts/dev-platform.sh` + `python demo/ecommerce/run_all.py` in a second terminal.

## 1. Scan → graph → incidents

1. **Readiness** → set workspace to `demo/ecommerce` → **Scan workspace & sync**.
2. **Home** shows live scan counts, deploy gate, production risk factors, shop payment status.
3. **Release Graph** — click a service; open a **code-scan incident** link if present.
4. Fix code on disk, rescan — scan incidents auto-close; risk rescored.

## 2. Deploy gate

1. Introduce a blocking finding (e.g. hardcoded secret) in the workspace.
2. **Releases** → draft release shows **Deploy blocked** with finding list and incident links.
3. Fix on disk, rescan — deploy unlocks when blocking count is zero.

## 3. Checkout failure (live shop)

1. **Incidents** → **Run a failing checkout** (shop must be running).
2. **Open shop & restore payments** → restore on the storefront.
3. **Check shop & sync tickets** — checkout incident closes when failure mode is off.

## 4. Fix PR loop

1. Scanner opens tickets on **Fix PRs**.
2. **Approve** (human) → **Re-scan and close** or **Re-scan workspace** on the row.
3. Merge only succeeds when verify + workspace no longer sees the finding.

## 5. Release train

1. After a clean scan, **Readiness** → **Start next release** (when train allows).
2. **Release detail** → **Deploy to production** shows blast-radius confirm.
3. **Commits since baseline** lists git-linked commits not on the baseline release.

## 6. Copilot playbooks

**Copilot** → use playbooks: safe to deploy, payment-service failure blast radius, blocking scanner issues.

## 7. Audit

**Home** → recent activity; full **Audit log** for workspace scans, deploys, fix PRs, incidents.

## org.yaml / rgc

If `org.yaml` exists under the workspace (or `fixtures/org.yaml`), readiness runs **rgc checkers** in addition to the workspace scanner. The path is stored on the project for the next check.
