# Release Graph Copilot — what is left

Give this file to Bob 2.0 together with [IBM_BOB_2.0_REAL_ORG_SCAN.md](IBM_BOB_2.0_REAL_ORG_SCAN.md). Do the remaining work only. Do not rewrite the checkers, the gate, or the fixture scenarios that already pass.

Run the suite from the repository root first:

```bash
.venv/bin/python -m pytest -q
```

That command currently exits 0 with **169 passed**. Keep it green. When you finish, it must still exit 0, and the new tests below must be part of that run.

Do not edit `IBM_BOB_2.0_EXECUTION_PLAN.md`, `IBM_BOB_2.0_REAL_ORG_SCAN.md`, or this file. Do not add a git host client or a new dependency.

---

## Already done

Leave this behavior in place.

- `rgc/org_config.py` loads an org YAML. `fixtures/org.yaml` describes the Meridian fixture organization.
- The five checkers take an optional org config and no longer need the Meridian names when that config is passed.
- Findings can carry `location` and `snippet`. `WorkspaceView.get_snippet` reads the surrounding lines.
- The CLI accepts `--workspace`, `--config`, `--repos`, `--ci-dir`, `--overlays`, and `--changed-paths`, and rejects a mix of `--release` and `--workspace`.
- The page title is `Is this deploy safe?`. The result includes `ul#checklist`. Approve and Cancel do not call `alert`. A successful approve shows `E2E trigger written.` and the E2E folders. Cancel shows `Nothing was triggered.`
- The original Meridian scenarios still answer GO or NO-GO as before, including the section 3.2 flag-flip citation.

---

## 1. Finish the second organization

`fixtures/other-org/workspace/` exists, along with `graph.yaml`, `catalog.json`, `ci/`, and `citations.yaml`. These two files are missing:

- `fixtures/other-org/org.yaml`
- `fixtures/other-org/releases/clean.json`
- `fixtures/other-org/releases/flag-flip.json`

Write them exactly as section 5 of `IBM_BOB_2.0_REAL_ORG_SCAN.md` describes. Set `name: other-org`. `affected_repos` order is `api`, then `jobs`. The flag-flip overlay sets `api/config/feature-flags.yaml` to `storage: GIT`.

---

## 2. Remove the Meridian fallback strings

`rgc/checkers/fc_etl.py` and `rgc/citations.py` still fall back to `prompt-backend` and `nc-enterprise-ai-platform-etl-jobs` when no org config is passed. The scan spec forbids those strings under `rgc/`.

Always load `fixtures/org.yaml` when the caller does not pass an org config, and delete those hardcoded fallback names. After that, a search of `rgc/` must find neither `nc-enterprise-ai-platform-etl-jobs` nor `Affected: prompt-backend`.

---

## 3. Add `tests/test_org_scan.py`

This file does not exist. Add the cases in sections 6 and 9 of `IBM_BOB_2.0_REAL_ORG_SCAN.md`:

- Meridian `safe` is still GO with estimate `4m 20s` and folders `backend`, `etl`, `gateway`.
- Meridian `unsafe-flag-flip` still says `Affected: prompt-backend, nc-enterprise-ai-platform-etl-jobs`.
- Other-org `clean` is GO with deploy order `api`, `web`, `jobs`.
- Other-org `flag-flip` is NO-GO, section `9.1`, `Affected: api, jobs`, and the JSON has no `prompt-backend`.
- The flag-flip finding `snippet` contains `storage: GIT` and `location` starts with `api/config/feature-flags.yaml:`.
- A missing org key is `invalid_org_config` on all five checks, with no `Traceback`.
- Direct CLI scan of the other-org workspace exits 0 and the release id is `other-org+api`.
- `--workspace` without `--config` exits 1 with stderr `invalid scan arguments`.
- Empty `--repos` is `empty_release`.
- A named repo folder that is not on disk is `missing_repo` on pipeline status only.
- Overlay path `../secret` is `unsafe_path`.
- A runbook with the quote removed is `citation_not_found`, and the quote is absent from the JSON.
- A missing workspace directory is `missing_workspace`.
- Duplicate `--repos api,api` is one repo.
- A cyclic org graph is `graph_cycle`.
- Running Meridian after the other org still cites section `3.2`, not `9.1`.
- `affected_repos` written as `jobs` then `api` renders `Affected: jobs, api` while the finding repos array is sorted `["api", "jobs"]`.
- `pipeline_file: bitbucket-pipelines.yml` is honored in a temp workspace.
- `rgc/` contains neither banned string from section 2.

---

## 4. Make the page show the code

`rgc/server.py` lists the five summaries and nothing else about each finding. It has no scan form and no `POST /api/scan`.

Change the result into check cards, as section 11 of `IBM_BOB_2.0_REAL_ORG_SCAN.md` describes:

- One card per check, in the fixed order.
- Status word `pass`, `warning`, or `blocked`.
- Green left border for pass, amber for warning, red for blocked.
- For each finding, show repos, message, suggested fix, and `class="location"` with the `location` string.
- Show `pre.snippet` with the snippet text, HTML-escaped, newlines kept. Omit the snippet box when `snippet` is null.
- The unsafe Meridian page must show `feature-flags.yaml` and `rehydrate must run before flag flip to GIT` inside a `pre.snippet`.
- Verdict band, white content column, light page background, buttons at least 36 pixels tall. No emoji. No `alert(`.

Add `form#scan` with `input#workspace`, `input#config`, `input#repos`, `input#ci-dir`, and `button#scan-run` labeled `Scan`.

Add `POST /api/scan`. Body is `workspace`, `config`, `repos`, and optional `ci_dir`. Return `run_id`, `show_approve`, and `checklist` with HTTP 200 even on NO-GO. Invalid arguments return HTTP 400 and `{"ok": false, "message": "invalid scan arguments"}`.

Extend `tests/test_server.py` so it checks the cards, the snippet, the scan form, and `POST /api/scan` for the other-org clean workspace (`show_approve` true, release id `other-org+api`).

---

## 5. README

`README.md` has no scan section. Add `Scan a provided organization` with the direct CLI from section 4 of the scan spec. Say that the user clones repos into one folder, writes an org YAML, and supplies CI status JSON. Say that the tool does not call a git host. One sentence must say that a direct scan reads the files as they are, and a proposed flag change must be passed as an overlay.

---

## Done when

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m rgc check \
  --workspace fixtures/other-org/workspace \
  --config fixtures/other-org/org.yaml \
  --repos api \
  --ci-dir fixtures/other-org/ci \
  --out out/other-clean
.venv/bin/python -m rgc check \
  --release fixtures/other-org/releases/flag-flip.json \
  --out out/other-flip
```

The suite exits 0. The clean scan exits 0 and is GO. The flag-flip check exits 1, cites section `9.1`, includes `Affected: api, jobs`, and includes a snippet of `storage: GIT`. The page for that release shows that snippet in `pre.snippet`.
