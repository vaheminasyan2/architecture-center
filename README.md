# MS Architecture Center Scanner

A maintenance and discovery tool for keeping **[Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/browse)** scenarios in sync with the **Azure Pricing Calculator**.

It serves two purposes:

1. **Maintenance of known calculator scenarios** — monitors each scenario already added to the Pricing Calculator for estimate link changes, image updates, and whether the article is still live and accessible on the Architecture Center. Flags anything that requires an update request to the calculator team.

2. **Discovery of new calculator candidates** — scans all Architecture Center articles to identify those that have added or updated a saved estimate link and are not yet in the calculator, so they can be evaluated for addition.

---

## Context and background

### What is the Azure Pricing Calculator?

The **[Azure Pricing Calculator](https://azure.microsoft.com/pricing/calculator/)** is a Microsoft tool that helps customers estimate the cost of running Azure workloads. Within the calculator, there is a **Scenarios** section that contains pre-built cost estimates tied to specific Azure architecture patterns from the Architecture Center. Each scenario in the calculator references:

- A **saved estimate link** — a shared Azure Pricing Calculator estimate URL (e.g. `https://azure.com/e/...`) that opens a pre-configured cost estimate
- An **architecture diagram image** — the primary visual from the corresponding Architecture Center article
- A **title** — a short name for the scenario (subject to a strict character limit in the calculator UI)

### What is the Azure Architecture Center?

The **[Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/browse/)** is a Microsoft documentation site containing reference architectures, design patterns, and example scenarios for building solutions on Azure. It is maintained in the open-source GitHub repository **[MicrosoftDocs/architecture-center](https://github.com/MicrosoftDocs/architecture-center)**. Articles are regularly updated by Microsoft engineers and the community — which is why ongoing monitoring is needed.

### The problem this tool solves

Architecture Center articles change over time. Authors add, update, or remove pricing estimate links. Architecture diagrams get redesigned. Entire articles get taken down or redirected. Without automated monitoring, these changes go unnoticed and the Pricing Calculator falls out of sync with the Architecture Center.

Previously, this monitoring was done manually. This tool automates it.

### Who owns what

| Party | Responsibility |
|---|---|
| **You (PM/TPM)** | Run the monthly scan, review outputs, submit update requests, maintain `estimate_scenarios.xlsx` |
| **Calculator team** | Receives update requests and makes changes to the Pricing Calculator scenarios |
| **Architecture Center team** | Maintains the Architecture Center articles and repo; you do not submit requests to them |

### Key contacts

> **Note for the incoming person:** update this section with current contacts before handing off again.

- **Calculator team contact:** _[add name and email]_
- **Architecture Center repo:** https://github.com/MicrosoftDocs/architecture-center
- **Your forked repo:** _[add your fork URL]_

---

## Your monthly workflow

This is the end-to-end process you follow each month. Each step is explained in detail later in this document.

### Step 1 — Run the monthly scan

1. Open your forked repo on GitHub
2. Go to **Actions** → **Architecture Scan + Estimate Comparison**
3. Click **Run workflow** → **Run workflow**
4. Wait for the workflow to complete (typically 5–10 minutes)
5. Download `scan-results.xlsx` from the workflow artifacts

### Step 2 — Review the estimate-updates tab

These are scenarios already in the Pricing Calculator whose estimate link has changed in the Architecture Center.

For each row:
1. Open the `yml_url` link and verify the new estimate link is correct
2. Submit an update request to the calculator team with the new estimate link
3. Update the `estimate_link` column in `estimate_scenarios.xlsx` with the new URL
4. Re-run the scan to confirm the row no longer appears

### Step 3 — Review the estimate-link-removed tab

These are scenarios already in the Pricing Calculator whose estimate link has been completely removed from the Architecture Center article.

For each row:
1. Open the `yml_url` link to verify the estimate link is genuinely gone
2. Decide whether to retire the calculator scenario or wait to see if it is restored
3. If retiring: submit a retirement request to the calculator team
4. Update or remove the row in `estimate_scenarios.xlsx`

### Step 4 — Review the inventory-health tab

These are availability checks on all scenarios currently in your reference inventory.

Focus on rows with `inventory_status` of `scenario_removed` or `scenario_redirected`:
1. Open the `yml_url` to verify the page is genuinely gone or redirected
2. For `scenario_removed`: submit a retirement request to the calculator team; remove the row from `estimate_scenarios.xlsx`
3. For `scenario_redirected`: check where the redirect leads; if the content moved to a new URL, update `yml_url` in `estimate_scenarios.xlsx` and recheck; if the content is gone, retire the scenario

### Step 5 — Review the image-changes tab

These are scenarios where the primary architecture diagram has changed in the repo since the last confirmed baseline.

For each `changed` row:
1. Open the `yml_url` to review the updated diagram
2. Decide whether the change is significant enough to update the calculator
3. If updating: submit an image update request to the calculator team with the new image
4. Once the calculator team confirms the update is done, trigger the **Update Image Baseline** workflow (see [Baseline update behaviour](#baseline-update-behaviour))

For each `image_not_found` row:
1. The image path stored in `estimate_scenarios.xlsx` is no longer valid
2. Find the new path in the Architecture Center repo and update `primary_image_path` in `estimate_scenarios.xlsx`

### Step 6 — Review the new-candidates tab

These are Architecture Center articles that now have a valid saved estimate link and are not yet in the Pricing Calculator.

For each row:
1. Open the `yml_url` and review the article and its estimate link
2. Decide whether it is a good candidate for the calculator
3. If adding: submit an add request to the calculator team with the estimate link, title, and image
4. Add a new row to `estimate_scenarios.xlsx` (see [Adding a new scenario to the reference inventory](#adding-a-new-scenario-to-the-reference-inventory))

### Step 7 — Commit your reference file updates

After actioning all tabs, commit and push the updated `estimate_scenarios.xlsx` to your forked repo so the next monthly run has an accurate baseline.

---

## The reference inventory file (`estimate_scenarios.xlsx`)

This is the single source of truth for all scenarios you are tracking. It lives in the root of your forked repo and is read by every script in the pipeline.

### Column reference

| Column | Who fills it | Description |
|---|---|---|
| `status` | You | `Skip` to exclude a row from all processing; anything else (e.g. `Published`, `Submitted`, `In Review`) is processed normally |
| `title_in_calculator` | You | The scenario title as it appears in the Pricing Calculator (50 character limit enforced by the calculator UI) |
| `yml_url` | You | The canonical Architecture Center article URL (no trailing `/index`) |
| `estimate_link` | You | The saved estimate URL currently in the Pricing Calculator for this scenario |
| `primary_image_path` | You | Repo-relative path to the architecture diagram used in the calculator (e.g. `docs/example-scenario/ai/media/diagram.svg`) |
| `primary_image_sha256` | **Tool** | SHA-256 hash of the image file — auto-populated by the workflow. **Do not edit manually.** |
| `Notes` | You | Free-text notes for your own reference |

### Status values

The `status` column controls whether a row is included in processing. Only rows with `status = Skip` are excluded. All other values are treated as active:

| Status | Meaning |
|---|---|
| `Published` | Scenario is live in the Pricing Calculator |
| `Submitted` | Update or add request has been submitted to the calculator team; awaiting confirmation |
| `In Review` | Under review by the calculator team |
| `Skip` | **Excluded from all processing** — use this for scenarios you want to keep in the file but not monitor |

You can use any status value that is meaningful to your workflow — only `Skip` has special meaning to the tool.

### Adding a new scenario to the reference inventory

When a new article is approved for the Pricing Calculator and the calculator team confirms it has been added:

1. Open `estimate_scenarios.xlsx`
2. Add a new row with:
   - `status` = your current tracking status (e.g. `Published`)
   - `title_in_calculator` = the title as entered in the calculator (≤ 50 characters)
   - `yml_url` = the article URL from the `yml_url` column in `scan-results.xlsx`
   - `estimate_link` = the saved estimate URL from the `estimate_link` column in `scan-results.xlsx`
   - `primary_image_path` = the repo-relative image path from the `primary_image_path` column in `scan-results.xlsx`
   - Leave `primary_image_sha256` blank — the tool will populate it on the next run
3. Commit and push `estimate_scenarios.xlsx` to your forked repo

### Updating an existing scenario

When the calculator team confirms an estimate link or image update has been applied:

1. Update `estimate_link` or `primary_image_path` in the corresponding row
2. If updating an image: also run the **Update Image Baseline** workflow to reset the hash (see [Baseline update behaviour](#baseline-update-behaviour))
3. Commit and push `estimate_scenarios.xlsx`

### Removing a scenario

When a scenario is retired from the Pricing Calculator:

1. Either delete the row entirely, or change `status` to `Skip` if you want to keep a record
2. Commit and push `estimate_scenarios.xlsx`

---

## What the scanner evaluates

### Two content patterns in the Architecture Center

The Architecture Center publishes articles using two distinct structures. The scanner handles both:

**Pattern A — YML + MD (companion pair)**
A `.yml` file contains page metadata and a `[!INCLUDE]` directive pointing to a separate `.md` file that holds the article body. The `.yml` is the published page; the `.md` is the content source.

**Pattern B — Standalone MD**
A single `.md` file contains both metadata (in a YAML front matter block at the top) and the full article body. There is no companion `.yml`. The `.md` file is itself the published page.

Both patterns appear in the Architecture Center repo. Examples of Pattern B articles include pages under `networking/guide/` and `data-guide/disaster-recovery/` that have no associated `.yml` file. The scanner's Pass 2 picks these up by finding `.md` files with a `title` field in their front matter that are not already consumed as `[!INCLUDE]` targets by any `.yml` file.

### Evaluation pipeline

The scanner applies three gates in strict sequence. Each gate only runs if the previous one passed. All rows are kept in the output regardless of which gate they stopped at.

| Gate | Column | Question | Stops here if… |
|---|---|---|---|
| **1** | `scan_status` | Did the file parse and resolve correctly? | File is broken or missing — `scan_status` = error code |
| **2** | `in_scope` | Is this a complete, valid scenario? | Any of the three scope criteria are missing — `in_scope = FALSE` |
| **3** | `criteria_passed` | Does the article contain a usable pricing estimate link? | No valid estimate link found — `criteria_passed = FALSE` |

Comparison (`comparison_status`) only runs on rows that reach and pass Gate 3.

### Gate 1 — Scan status

Before any content evaluation, the scanner checks whether each file could actually be parsed and resolved. A record receives `scan_status = ok` only if the file parsed successfully and all content resolved correctly. Any structural failure sets `scan_status` to one of the error codes below, forces `in_scope = FALSE` with `out_of_scope_reason = scan_error`, and stops all further evaluation. These rows are kept in the output for auditability.

| `scan_status` error code | Applies to | What it means | Common cause |
|---|---|---|---|
| `yaml_parse_failed` | Pattern A (YML+MD) | The `.yml` file exists but could not be parsed as valid YAML, or its top-level value is not a dictionary | Syntax errors, encoding issues, or a non-article YAML file (e.g. a `toc.yml` or `docfx.json` picked up by the glob) |
| `missing_content_string` | Pattern A (YML+MD) | The `.yml` file parsed successfully but contains no `content` key, or its value is not a string | The YML file is a metadata-only or config file rather than an article wrapper; or the `content` field is structured as a list instead of a string |
| `no_include_directive` | Pattern A (YML+MD) | The `content` string was found but contains no `[!INCLUDE]` directive pointing to an `.md` file | The YML embeds its article body directly as inline text instead of referencing a companion `.md` file, which is an uncommon but valid authoring pattern the scanner does not process |
| `include_md_unresolvable` | Pattern A (YML+MD) | An `[!INCLUDE]` directive was found but the referenced path could not be resolved to a location within the repo | The path in the directive is malformed, uses an unsupported syntax, or points outside the `docs` root |
| `include_md_missing` | Pattern A (YML+MD) | The `[!INCLUDE]` path resolved correctly but no file exists at that location on disk | The companion `.md` file was deleted, renamed, or never committed; or the YML references a file in a different branch |

### Gate 2 — Scope filter (in / out of scope)

Before any pass/fail evaluation runs, the scanner applies a scope filter. A scenario is **in scope (`in_scope = TRUE`)** only when **all three** of the following are present:

1. **Non-blank title** — pulled from the YML metadata or MD front matter
2. **Non-blank description** — same source
3. **At least one architecture image** — at least one image reference (`:::image`, `![]()`, `<img>`, etc.) must appear anywhere in the article body, in any format and whether local or externally hosted

`azureCategories` is captured in the output for every scenario but a missing or blank category does **not** cause a scenario to be marked out of scope.

Scenarios that fail one or more criteria receive `in_scope = FALSE` and an `out_of_scope_reason` listing each failing criterion (semicolon-separated): `blank_title`, `blank_description`, or `no_architecture_image`. **All rows are preserved in the output** — out-of-scope rows are visible in `scan-results` for auditability but are excluded from pass/fail evaluation, comparison, and the action queue tabs.

### Gate 3 — Primary question (pass / fail)

The scanner answers the primary question: **Does the Architecture Center article include a usable pricing estimate link?**

A scenario **passes (`criteria_passed = TRUE`)** if the included Markdown article contains **at least one** of the following:

1. **Azure Experience links** — `https://azure.com/e/*`
2. **Pricing Calculator shared estimate links** — `https://azure.microsoft.com/pricing/calculator?...shared-estimate=*`

> **Important:** Pricing Calculator tool/root links (for example, `/pricing/calculator` without a saved estimate) do **not** count as usable estimates.

### Failure reasons

If no usable estimate is found, the scenario fails with one of the following reasons:

- **`no_estimate_link_calculator_tool_link_only`** — Pricing Calculator links exist, but they are tool/root links only (no saved estimate).
- **`no_estimate_link`** — No Pricing Calculator links of any kind were found in the article.

### Images (informational only)

Images are detected for every included `.md` article and captured in the output (`image_download_urls`, `primary_image_path`). **Image presence does not affect pass/fail** and is provided for context and review only.

---

## Estimate comparison (post-scan)

For scenarios where `criteria_passed = TRUE`, the tool compares detected **usable estimate links** against the reference inventory in `estimate_scenarios.xlsx`.

### Comparison behavior

- Scenarios are matched using the **Learn URL** (`yml_url`).
- Estimate URLs are **normalized** before comparison (case, whitespace, and trailing slashes removed; only the identity-defining `shared-estimate` query parameter is retained).
- If an article contains **multiple valid estimate links** (for example, Small / Medium / Large cost profiles), **all compliant links are preserved** in the report (newline-separated).
- A scenario is treated as a match if **any scanned estimate link** matches the inventory estimate link after normalization.
- Only rows in `estimate_scenarios.xlsx` with `status != Skip` participate in comparison.

### `comparison_status` values

| comparison_status value | Meaning | Action queue |
|---|---|---|
| `matched_existing_scenario_same_estimate` | Scenario exists in inventory and the scanned estimate link matches | No action needed |
| `matched_existing_scenario_new_estimate` | Scenario exists in inventory but the estimate link has changed to a different URL | **`estimate-updates`** tab |
| `estimate_link_removed` | Scenario exists in inventory, article is still live and in scope, but the estimate link has been removed from the article entirely | **`estimate-link-removed`** tab |
| `new_estimate_candidate` | Scenario has a valid estimate link but does not exist in the inventory | **`new-candidates`** tab |
| `not_applicable` | Scenario failed Gate 2 or Gate 3; comparison not performed | — |

Only scenarios with `in_scope = TRUE` and `criteria_passed = TRUE` participate in estimate comparison.

### Action queue worksheets

The Excel output includes three dedicated action queue worksheets:

**`estimate-updates`** — scenarios already in the inventory whose estimate link has changed to a different URL. Each row requires submitting an update request to the calculator team and updating `estimate_scenarios.xlsx`.

**`estimate-link-removed`** — scenarios already in the inventory whose estimate link has been removed from the Architecture Center article entirely while the page is still live. Each row requires submitting a retirement request to the calculator team and updating `estimate_scenarios.xlsx`.

**`new-candidates`** — articles not yet in the inventory that now have a valid saved estimate link. Each row is a candidate for evaluation and potential addition to the calculator. Includes `primary_image_path` to make it easy to populate `estimate_scenarios.xlsx` when adding a new row.

---

## Inventory health check

After the estimate comparison runs, the workflow performs a dedicated health check on every non-Skip scenario in `estimate_scenarios.xlsx`. This detects scenarios that have been taken down or redirected on the Architecture Center so they can be retired from the Pricing Calculator.

### How it works

The check runs in two stages for each inventory scenario:

**Stage 1 — Reverse lookup (no network calls)**
Checks whether the scenario's `yml_url` appears anywhere in the current `scan-results.xlsx`. If it does not, the source file has been deleted or renamed in the repo and the scenario is immediately flagged as `scenario_removed` without making any HTTP request.

**Stage 2 — HTTP liveness check (network)**
For scenarios whose file still exists in the repo, makes an HTTP GET request to the live `yml_url` on `learn.microsoft.com` and follows any redirects. This catches three situations the reverse lookup cannot: a page removed from publishing while its source file still exists in the repo, a page that redirects to a different URL, and a page that returns a 404.

Requests are throttled at one per second by default to be polite to `learn.microsoft.com`. The throttle interval can be adjusted with the `--throttle` flag.

### `inventory_status` values

| Value | Stage detected | Meaning | Recommended action |
|---|---|---|---|
| `active` | Stage 2 | URL resolves correctly to the expected page | No action needed |
| `scenario_removed` | Stage 1 or 2 | Source file deleted from repo, or URL returns 404 | Retire or redirect this Pricing Calculator scenario |
| `scenario_redirected` | Stage 2 | URL permanently redirects to a different page | Review the redirect target; update or retire the calculator scenario |
| `scan_error` | Stage 1 | File exists but failed scanner Gate 1 | Fix the source file structural issue first, then re-run |
| `out_of_scope` | Stage 1 | File exists and parses but is currently out of scope | Investigate why the scenario dropped out of scope |

### `inventory-health` worksheet columns

- **yml_url** — The canonical URL from `estimate_scenarios.xlsx`
- **title_in_ac** — Article title from the Architecture Center (scanner output)
- **title_in_calculator** — Title as it appears in the Pricing Calculator (from `estimate_scenarios.xlsx`)
- **estimate_link** — Estimate link from `estimate_scenarios.xlsx`
- **inventory_status** — One of the five status values above
- **redirect_target** — The final URL after following redirects (blank if no redirect)
- **http_status_code** — HTTP response code from the liveness check (blank for `scenario_removed` via Stage 1)
- **note** — Human-readable explanation of the status

---

## Image change detection

After the inventory health check, the workflow checks whether the primary architecture diagram for each non-Skip scenario in `estimate_scenarios.xlsx` (that has a `primary_image_path`) has changed since the last confirmed baseline.

### How it works

For each eligible row in `estimate_scenarios.xlsx`, the script:

1. Resolves the image file on disk (the Actions runner has a full repo clone, so no network calls are needed)
2. Computes a SHA-256 hash of the file's raw bytes
3. Compares that hash against the `primary_image_sha256` column in `estimate_scenarios.xlsx`
4. Records the result in the `image-changes` tab of `scan-results.xlsx`

SHA-256 hashing detects any change to the image content — including cases where a contributor replaces an image file in-place without changing the filename.

### `image_change_status` values

| Value | Meaning | Action |
|---|---|---|
| `unchanged` | Hash matches the stored baseline | No action needed |
| `changed` | Hash differs from baseline — image was updated in the repo | Review the updated diagram; submit an image update request to the calculator team if needed |
| `new_baseline` | No stored hash yet (first run or new inventory row) | Hash recorded as the new baseline; no comparison was made this run |
| `image_not_found` | `primary_image_path` does not exist on disk | The file may have been moved, renamed, or deleted; verify and update the path in `estimate_scenarios.xlsx` |
| `skipped` | Row has `status = Skip` or blank `primary_image_path` | No action needed |

### `image-changes` worksheet columns

- **yml_url** — Architecture Center article URL
- **title_in_ac** — Article title from the Architecture Center
- **title_in_calculator** — Title as it appears in the Pricing Calculator
- **primary_image_path** — Repo-relative path to the tracked image
- **image_change_status** — `changed` or `image_not_found`
- **stored_sha256** — The hash from the previous baseline (blank for `image_not_found`)
- **current_sha256** — The hash computed this run (blank for `image_not_found`)
- **note** — Human-readable explanation

### Reference file image columns

- **primary_image_path** — Repo-relative path to the image used in the Pricing Calculator (e.g. `docs/example-scenario/ai/media/diagram.svg`). You fill this in manually when adding a new row.
- **primary_image_sha256** — SHA-256 hash of the image file, auto-populated by the workflow. **Do not edit this column manually.**

### Baseline update behaviour

The image hash baseline is **not** updated automatically during the monthly scan. This is intentional — a detected change must stay visible across every run until you have confirmed the update and actioned it.

The workflow for updating the baseline is:

1. Monthly scan runs → `image-changes` tab flags a scenario with `changed`
2. You review the updated image and decide it needs to be updated in the calculator
3. You submit an image update request to the calculator team
4. Calculator team updates the scenario with the new image and confirms
5. You manually trigger the **Update Image Baseline** workflow from GitHub Actions
6. The workflow recomputes all hashes, saves them to `estimate_scenarios.xlsx`, and commits the file back to the repo
7. The next monthly scan compares against this newly confirmed baseline

**Important:** do not run the Update Image Baseline workflow to dismiss a detected change without first updating the Pricing Calculator. Doing so will silently lose the signal and the change will not be detected again unless the image changes further.

---

## Repository files and what they do

| File | Purpose |
|---|---|
| `scripts/scan_architecture_center_yml.py` | Scans all Architecture Center YML and MD files in the repo. Handles both Pattern A (YML+MD) and Pattern B (standalone MD). Produces `scan-results.json`. |
| `scripts/build_scan_results_xlsx.py` | Converts `scan-results.json` into `scan-results.xlsx` with the `scan-results` worksheet. |
| `scripts/run_compare_only.py` | Compares scanned articles against `estimate_scenarios.xlsx`. Produces `estimate-updates`, `estimate-link-removed`, `new-candidates`, and `summary` worksheets. |
| `scripts/run_inventory_health.py` | Runs reverse lookup and HTTP liveness checks on all non-Skip inventory scenarios. Produces `inventory-health` worksheet and appends to `summary`. |
| `scripts/run_image_check.py` | Hashes primary images and compares against stored baselines (detect mode). Or resets baselines after changes are actioned (update-baseline mode). Produces `image-changes` worksheet and appends to `summary`. |
| `estimate_scenarios.xlsx` | Your reference inventory. The single source of truth for all tracked scenarios. Read by `run_compare_only.py`, `run_inventory_health.py`, and `run_image_check.py`. Updated by you after actioning changes; `primary_image_sha256` is auto-updated by the workflow. |
| `.github/workflows/scan_and_compare.yml` | Monthly scan workflow. Runs all five steps in sequence and uploads `scan-results.xlsx` as an artifact. |
| `.github/workflows/update_image_baseline.yml` | Manual baseline reset workflow. Run only after confirming the Pricing Calculator has been updated with the new image. |

---

## How to get started (first-time setup)

### Prerequisites

- Access to your team's forked copy of `MicrosoftDocs/architecture-center` on GitHub
- Write access to the repo (needed to commit `estimate_scenarios.xlsx` updates)
- `estimate_scenarios.xlsx` already populated with the current inventory of tracked scenarios

If the repo fork does not exist yet:

1. Fork https://github.com/MicrosoftDocs/architecture-center
2. Copy the scanner files into the forked repo at the paths shown in the table above
3. Add `estimate_scenarios.xlsx` to the root of the forked repo

### Running the scan for the first time

1. Open the forked repo on GitHub
2. Go to **Actions** → **Architecture Scan + Estimate Comparison**
3. Click **Run workflow** → **Run workflow**
4. Wait for the workflow to complete

**What to expect on the first run:**

- All rows in `estimate_scenarios.xlsx` that have a `primary_image_path` but no `primary_image_sha256` will show `new_baseline` in the image check — this is expected. The hashes are recorded and the `image-changes` tab will be empty.
- The `Update Image Baseline` workflow does not need to be run on the first scan — hashes are recorded automatically when a row has no existing baseline.
- All existing inventory scenarios should appear as `matched_existing_scenario_same_estimate` or `active` if the reference file is up to date.

### Downloading results

After the workflow completes:
1. Click the completed workflow run
2. Scroll to **Artifacts** at the bottom
3. Download `scan-results` — it contains `scan-results.xlsx`

---

## Outputs and how to interpret them

After a successful run, `scan-results.xlsx` contains the following worksheets:

| Worksheet | Contents | When to use it |
|---|---|---|
| `scan-results` | All scanned articles (~500+ rows) | Full audit view; look here when investigating a specific article |
| `estimate-updates` | Inventory scenarios with a changed estimate link | **Monthly action:** submit update requests |
| `estimate-link-removed` | Inventory scenarios whose estimate link was removed | **Monthly action:** submit retirement requests |
| `new-candidates` | Articles not in inventory with a valid estimate link | **Monthly action:** evaluate for addition to calculator |
| `inventory-health` | Availability check for all inventory scenarios | **Monthly action:** flag removed or redirected pages |
| `image-changes` | Inventory scenarios with a changed or missing image | **Monthly action:** submit image update requests |
| `summary` | Counts for every metric across all steps | Quick health check; review first to understand the scale of changes |

### Key columns in scan-results

- **title_in_ac** — Article title from the Architecture Center
- **description** — Article description
- **azureCategories** — Azure solution categories
- **ms.date** — Article freshness date; useful for prioritization
- **yml_url** — Published Architecture Center article URL
- **image_download_urls** — All images found in the article (informational)
- **primary_image_path** — Repo-relative path to the first image found; use this to populate `estimate_scenarios.xlsx` when adding a new row
- **estimate_link** — One or more usable estimate links (newline-separated)
- **scan_status** — Gate 1 result: `ok` or a structural error code (see [Gate 1](#gate-1--scan-status))
- **in_scope** — Gate 2 result: `TRUE` or `FALSE`
- **out_of_scope_reason** — Why the scenario is out of scope (`blank_title`, `blank_description`, `no_architecture_image`, or `scan_error`)
- **criteria_passed** — Gate 3 result: `TRUE` or `FALSE`
- **failure_reason** — Why `criteria_passed` is `FALSE` (`no_estimate_link` or `no_estimate_link_calculator_tool_link_only`)
- **comparison_status** — Estimate comparison result; drives the action queue tabs
- **yml_path** — Path to the source YML file in the repo
- **include_md_path** — Path to the included MD file (Pattern A) or same as `yml_path` (Pattern B)
- **md_author_name / md_ms_author_name** — Article author; useful for ownership context

### How to interpret the summary tab

The `summary` tab is the first thing to check after downloading results. It gives you a count for every metric across all five pipeline steps:

- **Gate 1/2/3 counts** — how many articles passed or failed each gate
- **Comparison status counts** — how many matched, updated, removed, or are new candidates
- **Action queue counts** — rows in each action queue tab
- **Inventory health counts** — how many scenarios are active, removed, or redirected
- **Image change counts** — how many images are unchanged, changed, or missing

If all counts look normal (most scenarios matched, few or no changes), a quick scan of the action queue tabs is all you need. If counts look unexpected, use the `scan-results` tab to investigate.

---

## Troubleshooting

### A scenario I expect to see is missing from scan-results

**Check 1:** Is the article's source file a Pattern A (`index.yml`) file? The scanner strips `/index` from the URL — so the `yml_url` in `scan-results.xlsx` will be `.../folder-name`, not `.../folder-name/index`. If your reference file still has `/index` in the URL, update it.

**Check 2:** Does the article have a title, description, and at least one image? If any are missing, it will be in `scan-results` but with `in_scope = FALSE`. Filter the `scan-results` tab on `in_scope = FALSE` and check `out_of_scope_reason`.

**Check 3:** Did the article recently change its structure? A Gate 1 error (`scan_status != ok`) means the scanner found the file but couldn't process it. Check `failure_reason` for the specific error code.

### A scenario appears as new_estimate_candidate but it's already in my reference file

The `yml_url` in `estimate_scenarios.xlsx` likely doesn't match what the scanner produced. Common causes:
- The reference file has `/index` at the end of the URL but the scanner strips it (see above)
- A trailing slash difference — normalize all URLs to no trailing slash

### The inventory health check flagged a scenario as scenario_redirected but the article seems fine

Some Architecture Center articles use `/index` in their URL at the source but the docs platform normalizes it — this can appear as a redirect. Check if the redirect target is just the same URL without `/index`. If so, update the `yml_url` in your reference file to the canonical form (without `/index`).

### The image baseline check shows changed but I didn't request any image updates

Architecture Center authors regularly refresh diagrams. A `changed` result means the image file bytes are different from when you last confirmed the baseline — it doesn't necessarily mean the change is significant. Open the article and review the diagram before deciding whether to submit an update request.

### The workflow failed mid-run

Check the **Actions** log for the specific step that failed. Common causes:
- Python syntax error in a script (check recent code changes)
- `estimate_scenarios.xlsx` missing a required column
- Network timeout during the inventory health HTTP checks (re-run the workflow)
