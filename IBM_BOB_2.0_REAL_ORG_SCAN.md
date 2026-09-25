# Release Graph Copilot — scan any organization

You are IBM Bob 2.0 in Agent mode. Read this whole file before you edit code. The product must check a workspace the user provides, not only the baked-in Meridian fixtures.

Do not edit `IBM_BOB_2.0_EXECUTION_PLAN.md` or this file. Do not add a Bitbucket client, a GitHub client, a model API, or any other network call. Repos are folders on disk. CI status is a directory of JSON files the user supplies. A missing status file is `missing_status`.

Keep every existing fixture scenario and every existing test passing. Add the new behavior beside that path.

When you are done, `.venv/bin/python -m pytest -q` must exit 0.

Also apply the page fixes in `IBM_BOB_2.0_IMPROVEMENTS.md` while you touch `rgc/server.py`. Those fixes are required by this spec and are repeated in section 11 so you do not need to guess.

---

## 1. What changes

Today these modules hardcode one organization:

- `rgc/manifest.py` defaults `workspace_root` to `fixtures/workspace`.
- `rgc/catalog.py` always loads `fixtures/catalog/repos.json`.
- `rgc/citations.py` always loads `fixtures/rules/citations.yaml` and hardcodes `Affected: prompt-backend, nc-enterprise-ai-platform-etl-jobs`.
- `rgc/checkers/fc_etl.py` hardcodes `prompt-backend` and `nc-enterprise-ai-platform-etl-jobs` and the paths `config/feature-flags.yaml`, `feature-config/published.yaml`, `jobs/consume.yaml`, and `pipeline.yaml`.
- `rgc/checkers/playwright_map.py` hardcodes `meridian-ui/tests/README.md` and `meridian-ui/tests/timings.json`.
- `rgc/checkers/workflow_config.py` only treats overlays under `workflow-configs/` as workflow diffs, and the contract path is fixed inside that checker.
- `rgc/checkers/pipeline.py` always reads `pipeline.yaml`.
- `rgc/server.py` only lists the eleven fixture scenarios.

After this change, an organization is described by one YAML file. The checkers read paths from that file. The Meridian fixture becomes one organization. A second tiny organization proves the names are not special.

The five checks, verdict rules, human gate, citation search algorithm, and Flyway scanner stay as specified in `IBM_BOB_2.0_EXECUTION_PLAN.md`. Only the locations of files and the names of repos come from the org config.

---

## 2. Org config schema

Add `rgc/org_config.py`. Load YAML with `yaml.safe_load`. A frozen dataclass `OrgConfig` holds the fields below. Paths inside the file are relative to the workspace root except `graph`, `ci_dir`, and `catalog`, which are relative to the process working directory (the repository root when tests run).

```yaml
name: meridian
workspace_root: fixtures/workspace
graph: fixtures/graph/deploy-graph.yaml
ci_dir: fixtures/ci-status/green
catalog: fixtures/catalog/repos.json
citations: fixtures/rules/citations.yaml
pipeline_file: pipeline.yaml
flyway_dir: db/migration
workflow_config_dir: workflow-configs
workflow_contract: workflow-service/contract/workflow-contract.yaml
feature_flags: prompt-backend/config/feature-flags.yaml
feature_config: prompt-backend/feature-config/published.yaml
etl_job: nc-enterprise-ai-platform-etl-jobs/jobs/consume.yaml
etl_repo: nc-enterprise-ai-platform-etl-jobs
flag_repo: prompt-backend
playwright_readme: meridian-ui/tests/README.md
playwright_timings: meridian-ui/tests/timings.json
affected_repos:
  - prompt-backend
  - nc-enterprise-ai-platform-etl-jobs
```

Required keys are every key in that example. A missing key, a non-string where a string is required, a missing file for `graph` or `citations` or `catalog`, or `affected_repos` not a list of strings, is a validation failure. Do not run the five checkers. Return a checklist whose five checks are each `blocked` with one finding:

```text
code: invalid_org_config
message: The organization config is invalid.
suggested_fix: Fix the organization YAML and re-run the check.
```

`release_id` is the release id when one exists, otherwise `invalid`. `verdict` is `no_go`, `risk` is `HIGH`, `gate` is `blocked`, `deploy_order` is `[]`, `e2e` is zero folders and `0s`, `block_report` is null. Exit code 1. stdout is that checklist JSON. It must not contain `Traceback`.

`affected_repos` is stored sorted ascending on the config object. The flag-flip block report still prints them in the order written in the YAML, not sorted. For the Meridian file that order is `prompt-backend`, then `nc-enterprise-ai-platform-etl-jobs`, so the existing block report text does not change.

Write `fixtures/org.yaml` with the example above. Existing release JSON files do not need a new key. When a release manifest omits `config`, load `fixtures/org.yaml`. When it contains `"config": "fixtures/org.yaml"`, load that path. `workspace_root`, `graph`, and `ci_dir` on the release JSON still override the org file when present, so `red-pipeline` can keep its own `ci_dir` and `cyclic-graph` can keep its own `graph`.

---

## 3. How a check chooses files

Thread `OrgConfig` into every checker. The checker signature may grow by one argument. Update `rgc/orchestrator.py` so the injected test checkers in the existing timeout and exception tests still run. Those tests pass callables. Keep accepting a callable of the old four-argument shape and a callable of the new shape. Detect that with the number of parameters, not with a brittle name check.

Path rules:

- Pipeline file for a repo is `{repo}/{pipeline_file}` inside the workspace.
- Flyway files for a repo are listed from `{repo}/{flyway_dir}`.
- Workflow overlays are those whose path starts with `{workflow_config_dir}/`.
- Workflow contract is `{workflow_contract}` inside the workspace.
- Feature flags, feature-config, ETL job, Playwright README, and timings are the org paths, read through the workspace view so overlays still win.
- Citation rules load from the org `citations` path. Do not keep a module-level default that ignores the org.
- Catalog membership loads from the org `catalog` path.
- `etl_repo` in the closure turns on the feature-config rule. `flag_repo` is the repo whose pipeline is searched for a step named `rehydrate`.
- The flag-flip finding `repos` list is the sorted intersection of the closure with `affected_repos`.
- The block report `Affected:` line joins `affected_repos` in YAML order with `, `.

`rgc/citations.py` function `_build_block_report` must take the ordered affected names from the org config. Remove the hardcoded Meridian sentence. For `fixtures/org.yaml` the rendered report must stay byte-for-byte the same as it is today, including the final newline.

Display paths in citations stay relative to the workspace. Strip a leading `{workspace_root}/` when the rule `file` value contains it. A rule file such as `fixtures/workspace/bitbucket-db-migration/README.md` still displays as `bitbucket-db-migration/README.md`.

---

## 4. CLI for a provided workspace

Keep the current release command working:

```text
python -m rgc check --release fixtures/releases/safe.json --out out/safe
```

Add a direct scan that does not need a release JSON file:

```text
python -m rgc check \
  --workspace /path/to/org \
  --config /path/to/org.yaml \
  --repos api,web \
  --out out/scan \
  --ci-dir /path/to/ci-status \
  --overlays overlays.json
```

Rules:

- `--workspace` and `--config` and `--repos` must be passed together. Passing only one of them exits 1, stderr `invalid scan arguments`, stdout empty.
- `--repos` is a comma-separated list. Empty `--repos` is the existing `empty_release` checklist, exit 1.
- `--ci-dir` overrides the org `ci_dir`. If omitted, use the org file.
- `--overlays` is optional. The file is a JSON list of `{"path","content"}` objects. The same unsafe-path rules as today apply (`..`, absolute paths, and characters outside `^[A-Za-z0-9_./-]+$`).
- `--release` cannot be combined with `--workspace`. That combination exits 1, stderr `invalid scan arguments`.
- The question is always `Is this deploy safe?`. The release id is the org `name` plus the sorted repo list joined by `+`, for example `acme+api+web`.
- Changed paths default to `[]` for a direct scan. Playwright then reports `E2E scope: 0 folders` unless the user passes `--changed-paths path1,path2`.

The workspace root used by the checkers is `--workspace`, not the `workspace_root` inside the org YAML, when `--workspace` is present. The org YAML `workspace_root` is the default for `--release` mode.

A named repo folder that does not exist under the workspace is `missing_repo`, severity `block`, on `pipeline_status` only, message `Repository folder is missing: {repo}.`, suggested fix `Clone or copy the repository into the workspace.` The other four checks still run. Verdict is `no_go`. Do not crash.

A graph node that is in the closure but has no folder under the workspace gets the same `missing_repo` finding and does not raise.

---

## 5. Second organization fixture

Create `fixtures/other-org/` so a test can scan an organization that is not Meridian. Do not copy the Meridian tree.

Layout:

```text
fixtures/other-org/workspace/api/pipeline.yaml
fixtures/other-org/workspace/api/config/feature-flags.yaml
fixtures/other-org/workspace/api/feature-config/published.yaml
fixtures/other-org/workspace/api/db/migration/V1__init.sql
fixtures/other-org/workspace/web/pipeline.yaml
fixtures/other-org/workspace/web/tests/README.md
fixtures/other-org/workspace/web/tests/timings.json
fixtures/other-org/workspace/jobs/pipeline.yaml
fixtures/other-org/workspace/jobs/jobs/consume.yaml
fixtures/other-org/workspace/docs/RUNBOOK.md
fixtures/other-org/workspace/rules-service/contract/workflow-contract.yaml
fixtures/other-org/workspace/workflow-configs/job-a.yaml
fixtures/other-org/graph.yaml
fixtures/other-org/ci/api.json
fixtures/other-org/ci/web.json
fixtures/other-org/ci/jobs.json
fixtures/other-org/catalog.json
fixtures/other-org/citations.yaml
fixtures/other-org/org.yaml
fixtures/other-org/releases/clean.json
fixtures/other-org/releases/flag-flip.json
```

Graph edges, in order: `api` must deploy before `web`, `web` must deploy before `jobs`.

`catalog.json` is a JSON array: `api`, `web`, `jobs`, `docs`.

Every CI file is `{"status": "success"}`.

Each `pipeline.yaml` is:

```yaml
steps:
  - name: build
  - name: test
```

No `rehydrate` step.

`api/config/feature-flags.yaml` is `storage: MYSQL`.

`api/feature-config/published.yaml` is `published: true`.

`jobs/jobs/consume.yaml`:

```yaml
requires_feature_config: true
job: consume
```

`api/db/migration/V1__init.sql`:

```sql
CREATE TABLE items (
  id INT PRIMARY KEY
);
```

`workflow-configs/job-a.yaml` matches the same contract shape as the Meridian configs (`name`, integer `version` 1, `steps` list). Copy the contract file contents from `fixtures/workspace/workflow-service/contract/workflow-contract.yaml`.

`web/tests/README.md` contains exactly one mapping line and one fallback line:

```text
- prefix: api/ -> folder: api-e2e
- fallback folder: smoke
```

`web/tests/timings.json` is `{"api-e2e": 70, "smoke": 10}`.

`docs/RUNBOOK.md`:

```markdown
# Other org runbook

## 9.1 Storage

rehydrate must run before flag flip to GIT
```

`citations.yaml` points `file` at `fixtures/other-org/workspace/docs/RUNBOOK.md`, section `9.1`, quote `rehydrate must run before flag flip to GIT`, same suggested fix text as the Meridian rule. No line number in the file.

`org.yaml` uses the other-org paths. `etl_repo` is `jobs`. `flag_repo` is `api`. `affected_repos` in this order: `api`, then `jobs`. `pipeline_file` is `pipeline.yaml`. `flyway_dir` is `db/migration`.

`releases/clean.json` uses this org, repos `["api"]`, no overlays, no changed paths. Expect `go`, `LOW`, `pending_approval`, deploy order `api`, `web`, `jobs`.

`releases/flag-flip.json` is the same plus an overlay of `api/config/feature-flags.yaml` with content `storage: GIT\n`. Expect `no_go`. The citation section is `9.1`. The citation file display is `docs/RUNBOOK.md`. `block_report` contains `Affected: api, jobs` and the quote. It must not contain `prompt-backend` or `meridian`.

---

## 6. Tests that must exist

Add `tests/test_org_scan.py`.

- Loading `fixtures/org.yaml` and running `fixtures/releases/safe.json` still returns the current safe checklist fields: verdict `go`, risk `LOW`, estimate display `4m 20s`, folders `backend`, `etl`, `gateway`.
- Running `fixtures/releases/unsafe-flag-flip.json` still contains the quote and `Affected: prompt-backend, nc-enterprise-ai-platform-etl-jobs`.
- `fixtures/other-org/releases/clean.json` is GO.
- `fixtures/other-org/releases/flag-flip.json` is NO-GO with section `9.1` and `Affected: api, jobs`, and the JSON does not contain `prompt-backend`.
- A temp org YAML missing `etl_repo` produces `invalid_org_config` on all five checks and the stdout of the CLI does not contain `Traceback`.
- CLI `--workspace fixtures/other-org/workspace --config fixtures/other-org/org.yaml --repos api --ci-dir fixtures/other-org/ci --out` a temp directory exits 0 and writes `checklist.json` with release id `other-org+api` if the org name is `other-org`. Set `name: other-org` in that org file.
- CLI `--workspace` without `--config` exits 1 and stderr is `invalid scan arguments`.
- CLI `--repos` empty with a valid workspace and config exits 1 with `empty_release`.
- A workspace that has no `api` folder, while the release names `api`, yields `missing_repo` on pipeline status only.
- An overlay path `../secret` is `unsafe_path` and no file outside the workspace is read.
- Deleting the quote from a copied runbook in a temp workspace yields `citation_not_found` and the quote string is absent from the checklist JSON.
- A graph node `missing-folder` that is not a directory under the workspace yields `missing_repo`.
- Existing modules no longer contain the string `nc-enterprise-ai-platform-etl-jobs` except `fixtures/org.yaml` and the Meridian fixtures. Scan `rgc/` in this test and fail if that string appears under `rgc/`. The same scan fails if `rgc/` contains `Affected: prompt-backend`.

Do not delete or skip any current test file.

---

## 7. Catalog and unknown repos

`unknown_repo` still means the repo id is not in the org catalog and not in the graph closure. The Meridian catalog file stays 1,130 ids. The other-org catalog is only the four ids in section 5. A direct scan of a folder that is not in the org catalog and not in the graph is `unknown_repo`, not a crash.

Do not invent catalog entries by listing the workspace. The catalog file is the allow-list. Extra folders in the workspace are ignored until they are in the catalog and in the graph or in `--repos`.

---

## 8. Direct scan with real files and no overlays

When `--overlays` is omitted, the checkers read the files in the workspace.

- Feature flags are whatever `storage` is on disk. A workspace that is already `GIT` with no `rehydrate` step blocks, because the baseline is the file on disk and the effective value is also `GIT` only when an overlay changes it. A flip is baseline not `GIT` and effective `GIT`. With no overlay, baseline and effective are the same file, so a repo that is already `GIT` does not count as a flip. Document this in `README.md` in one sentence: a direct scan reports the files as they are; a proposed flag change must be passed as an overlay.
- Flyway scans the migration directory that is actually present.
- Workflow-config passes when there is no overlay under `workflow_config_dir`.
- Playwright uses `--changed-paths` when provided, otherwise zero folders.

---

## 9. Edge cases

Cover each of these in `tests/test_org_scan.py` or the existing checker tests if you extend them.

- Workspace directory does not exist: `invalid_org_config` is wrong for this case. Use code `missing_workspace`, same five-check blocked shape, message `Workspace directory is missing.`, exit 1.
- `--repos api,api` collapses to one repo `api`.
- Org graph file that is cyclic still returns `graph_cycle` and does not read pipelines.
- Citation rule `file` points at a path inside the workspace. The search uses the workspace view so an overlay of that runbook still hides the quote.
- Two `OrgConfig` objects loaded in one test process use different citation files. Running the Meridian unsafe release after the other-org flag flip still cites section `3.2`, not `9.1`.
- `affected_repos` written as `jobs` then `api` renders `Affected: jobs, api` and the finding `repos` array is still sorted `["api", "jobs"]`.
- Pipeline filename in the org config can be `bitbucket-pipelines.yml`. A temp workspace with that filename and `pipeline_file` set to it passes the pipeline file check when CI status is `success`. The Meridian fixtures keep `pipeline.yaml`.

---

## 10. README

Add a short section to `README.md` titled `Scan a provided organization`. Show the direct CLI from section 4. State that the user clones the org repos into one folder first, writes an org YAML, and supplies CI status JSON files. State that the tool does not call a git host.

---

## 11. Local UI

Keep the fixture scenario dropdown. Add a second form, `form#scan`, with:

- `input#workspace` for the workspace path
- `input#config` for the org YAML path
- `input#repos` for a comma-separated repo list
- `input#ci-dir` optional
- `button#scan-run` text `Scan`

`POST /api/scan` accepts JSON:

```json
{
  "workspace": "fixtures/other-org/workspace",
  "config": "fixtures/other-org/org.yaml",
  "repos": "api",
  "ci_dir": "fixtures/other-org/ci"
}
```

It runs the same engine as the CLI and returns the same wrapper as `POST /api/check`: `run_id`, `show_approve`, `checklist`. HTTP 200 on a completed NO-GO. Invalid arguments use HTTP 400 and `{"ok": false, "message": "invalid scan arguments"}`.

`GET /?scenario=safe` and `GET /?scenario=unsafe-flag-flip` must also satisfy `IBM_BOB_2.0_IMPROVEMENTS.md`:

- `<title>Is this deploy safe?</title>`
- `ul#checklist` with the five summaries in check order
- No `alert(` anywhere in `rgc/server.py`
- After approve, the page shows `E2E trigger written.` and `ul#e2e-folders`
- After cancel, the page shows `Nothing was triggered.`
- The unsafe page still hides `#approve`

Add those assertions to `tests/test_server.py`. Add one test that `POST /api/scan` on the other-org clean workspace returns `show_approve` true and release id `other-org+api`.

The scan form is server-rendered. A test may POST the API only. Do not add a browser driver or a new dependency.

### Present the result, and show the code

The page is the release decision, not a raw JSON dump. Keep it one column, readable at desktop width, with no remote fonts, images, or CSS. Use a plain `<style>` block.

Page structure from top to bottom:

1. Title and the question `Is this deploy safe?`
2. The fixture scenario form and the scan form, side by side only if both fit. Stack them on a narrow window.
3. A verdict band: `GO` or `NO-GO`, the risk line, and the gate prompt or the block report.
4. The five-check list. Each check is a card, not a single plain line.
5. The approve and cancel actions, then the trigger message.

Each check card contains:

- The check name and the summary.
- A status word: `pass`, `warning`, or `blocked`.
- For every finding, the repo names, the message, and the suggested fix.
- When the finding has a citation, show the file display path, the section, and the line number as text, for example `docs/RUNBOOK.md §9.1 line 5`.
- A location line and a code snippet, described below.

#### Location and snippet

Every blocking or warning finding that points at a file must include two new JSON fields on the finding:

- `location`: a string `{path}:{line}` relative to the workspace, or the citation display path when the problem is a runbook line. Example: `api/config/feature-flags.yaml:1` or `docs/RUNBOOK.md:5`.
- `snippet`: the source line at that location, plus up to two lines before it and two lines after it, joined by newlines. Skip lines that do not exist. Do not invent code. If the file cannot be read, `snippet` is null and `location` still names the path the checker looked for.

Fill these from the workspace view inside the checker or the citation step. Do not hardcode Meridian snippets.

Which line to use:

- Flag flip: the effective feature-flag line that sets `storage: GIT`.
- Missing rehydrate: the pipeline file, line 1, and say in the message that no `rehydrate` step exists.
- Unsafe Flyway: the first stripped line that matched the destructive statement, with the real surrounding lines from the SQL file.
- Workflow contract or malformed YAML: the overlay path and line 1 of that content.
- Failed or missing CI: the status path `{ci_dir}/{repo}.json` and line 1 when the file exists. If the file is missing, `location` is that path and `snippet` is null.
- Missing repo folder: `location` is the repo directory name and `snippet` is null.
- Citation found: `location` matches the citation line, and `snippet` is the runbook context around the quoted line. The unsafe flag-flip page must show the quote inside `pre.snippet`.

On the page, render `location` in an element with class `location`, and the snippet in `pre.snippet`. Escape HTML. Preserve newlines. A pass check with no findings shows the summary only and no empty snippet box.

The unsafe flag-flip fixture page must contain both `feature-flags.yaml` and the runbook quote inside a `pre.snippet`. The other-org flag-flip page must contain `api/config/feature-flags.yaml` and must not contain `prompt-backend`.

Add a test that the checklist JSON for `fixtures/other-org/releases/flag-flip.json` has a non-null `snippet` containing `storage: GIT` and a `location` that starts with `api/config/feature-flags.yaml:`.

#### Look

Use a light page background, a white content column, and a clear border on each check card. Pass cards use a green left border. Warning cards use an amber left border. Blocked cards use a red left border. The verdict band uses the same colors. Buttons have visible padding and a minimum height of 36 pixels. `pre.snippet` uses a monospace font and a light gray background. Do not use emoji. Do not use `alert`.

---

## 12. Order of work

1. Add `OrgConfig` and `fixtures/org.yaml`. Point the Meridian path at it without changing checklist JSON for `safe` and `unsafe-flag-flip`.
2. Remove hardcoded repo names and paths from the checkers and the citation report. Run the existing suite.
3. Add the direct CLI arguments.
4. Add `fixtures/other-org/` and `tests/test_org_scan.py`.
5. Update the UI and `tests/test_server.py`, including the improvements file, the check cards, and the location plus code snippet for each issue.
6. Update `README.md`.

After each step, run:

```bash
.venv/bin/python -m pytest -q
```

Do not start the next step if it fails. You are finished only when that command exits 0 and a direct scan of `fixtures/other-org` is GO while its flag-flip release is NO-GO with `Affected: api, jobs`.
