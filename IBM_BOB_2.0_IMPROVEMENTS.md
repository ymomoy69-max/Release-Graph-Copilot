# Release Graph Copilot — improvements after review

The build matches the execution plan for the engine. `python -m pytest -q` passed **165 tests**. The safe checklist is GO, risk LOW, five pass summaries, E2E folders `backend`, `etl`, `gateway`, estimate `4m 20s`. The unsafe flag flip is NO-GO, cites `bitbucket-db-migration/README.md` section 3.2 line 15, and the quoted sentence is the real line in the runbook. Approve writes `e2e-trigger.json` only after a GO check. A blocked run cannot be approved.

Do not change those contracts. The gaps below are what the tests do not cover. Fix them in `rgc/server.py` and add tests that fail if the old behavior comes back.

## 1. The page does not show the checklist

`GET /?scenario=safe` renders GO, `Risk: LOW`, and the gate prompt. It does not render the five check summaries that are the actual answer:

- Pipelines: all green
- Config diff: safe
- FC/ETL: clear
- Flyway: no unsafe migrations
- E2E scope: 3 folders

Add a `ul#checklist` inside `#result`. One `li` per check, in the fixed order `pipeline_status`, `workflow_config`, `fc_etl`, `flyway`, `playwright_map`. Text is the check `summary`. On NO-GO, the same list stays visible above `#citation`.

## 2. Approve and Cancel only open an alert

In `rgc/server.py` the buttons call `alert('Approved! Trigger written.')` and `alert('Cancelled.')`. The page never shows the trigger, and Cancel never shows the sentence the API already returns.

After a successful approve, replace the result section in the page with:

- `p#trigger-message` text exactly `E2E trigger written.`
- `ul#e2e-folders` with one `li` per trigger folder, in the order the API returns (`backend`, `etl`, `gateway` for the safe scenario)
- `p#e2e-estimate` text exactly the trigger `estimate_display` (`4m 20s` for safe)

Hide `#approve` and `#cancel` after a successful approve so a second click is not offered. The API stays idempotent.

After a successful cancel, show `p#trigger-message` with exactly `Nothing was triggered.` Do not list folders. Hide both buttons.

On HTTP 409, show `p#trigger-message` with the API `message` (`approval rejected` or `cancel rejected`). Do not use `alert` for any of these outcomes.

## 3. The browser tab title is not the question

`<title>` is `Release Graph Copilot`. Change it to `Is this deploy safe?` so it matches `h1#title` and `p#prompt`.

## 4. Tests to add

Extend `tests/test_server.py`:

- `GET /?scenario=safe` HTML contains `id="checklist"` and all five pass summaries, and `<title>Is this deploy safe?</title>`.
- `GET /?scenario=unsafe-flag-flip` HTML contains `id="checklist"`, `GIT flag set, no rehydrate step found.`, and the approve button still has `hidden`.
- The HTML source does not contain `alert(`.
- A comment in the test states that folder and cancel text are rendered by the script into `#trigger-message` and `#e2e-folders`. Assert the script source contains the exact strings `E2E trigger written.`, `Nothing was triggered.`, and `e2e-folders`.

Do not weaken existing tests. Re-run:

```bash
.venv/bin/python -m pytest -q
```

That command must still exit 0.

## What not to change

- Checker rules, citation search, verdict and risk rules, gate files, and CLI exit codes.
- The fixed `Affected:` line in the flag-flip block report.
- Dependencies. Do not add a web framework or a browser driver.
- `IBM_BOB_2.0_EXECUTION_PLAN.md`.
