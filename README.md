# MS Architecture Center Scanner

A lightweight scanning tool used to analyze articles in the **[Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/browse)** to determine scenarios that include a **usable Azure Pricing Calculator estimate link** and compare them against a reference list of known scenarios. The outputs help identify pricing‑ready scenarios, detect updated estimate links (estimate drift), and highlight gaps.

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
| **2** | `in_scope` | Is this a complete, valid scenario? | Any of the four scope criteria are missing — `in_scope = FALSE` |
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

Before any pass/fail evaluation runs, the scanner applies a scope filter. A scenario is **in scope (`in_scope = TRUE`)** only when **all four** of the following are present:

1. **Non-blank title** — pulled from the YML metadata or MD front matter
2. **Non-blank description** — same source
3. **At least one Azure category** — `azureCategories` must have at least one entry
4. **At least one architecture image** — at least one image reference (`:::image`, `![]()`, `<img>`, etc.) must appear anywhere in the article body, in any format and whether local or externally hosted

Scenarios that fail one or more criteria receive `in_scope = FALSE` and an `out_of_scope_reason` that lists each failing criterion (semicolon-separated). **All rows are preserved in the output** — out-of-scope rows are visible in `scan-results` for auditability but are excluded from pass/fail evaluation, comparison, and the `needs-review` tab.

### Gate 3 — Primary question (pass / fail)

The scanner answers the primary question: **Does the Architecture Center article include a usable pricing estimate link?**

A scenario **passes (`criteria_passed = TRUE`)** if the included Markdown article contains **at least one** of the following:

1. **Azure Experience / Pricing Calculator shared estimate links**  
   `https://azure.com/e/*` **or** `https://azure.microsoft.com/pricing/calculator?...shared-estimate=*`

> **Important:** Pricing Calculator tool/root links (for example, `/pricing/calculator` without a saved estimate) do **not** count as usable estimates.

### Failure reasons

If no usable estimate is found, the scenario fails with one of the following reasons:

- **`no_estimate_link_calculator_tool_link_only`**  
  Pricing Calculator links exist, but they are **tool/root links only** (no saved or scoped estimate).

- **`no_estimate_link`**  
  No Pricing Calculator links of any kind were found in the article.

### Images (informational only)

Images are detected for every included `.md` article and captured in the output (`image_download_urls`). **Image presence does not affect pass/fail** and is provided for context and review only.

## Estimate comparison (post‑scan)

For scenarios where `criteria_passed = TRUE`, the tool compares detected **usable estimate links** against a reference inventory in `estimate_scenarios.xlsx`.

This comparison answers the question: **Is this scenario already associated with the same estimate, or does it now reference a different estimate?** This supports ongoing maintenance by identifying estimate reuse, estimate drift, and brand‑new estimate candidates.

### Comparison behavior

- Scenarios are matched using the **Learn URL** (`yml_url`).
- Estimate URLs are **normalized** before comparison (case, whitespace, trailing slashes removed; only identity‑defining query parameters such as `shared-estimate` and `service` are retained).
- If an article contains **multiple valid estimate links** (for example, Small / Medium / Large cost profiles), **all compliant links are preserved** in the report (newline‑separated).
- A scenario is treated as a match if **any scanned estimate link** matches the inventory estimate link after normalization.

### `comparison_status` values

| comparison_status value | Meaning |
|-------------------------|--------|
| `matched_existing_scenario_same_estimate` | Scenario exists in inventory and at least one scanned estimate link matches the inventory estimate link |
| `matched_existing_scenario_new_estimate` | Scenario exists in inventory, but none of the scanned estimate links match (estimate drift or new estimate) |
| `new_estimate_candidate` | Scenario passed (`criteria_passed = TRUE`) but does not exist in the inventory |
| `not_applicable` | Scenario failed (`criteria_passed = FALSE`); comparison is not performed |

Only scenarios with `criteria_passed = TRUE` participate in estimate comparison.

### needs‑review worksheet

The Excel output includes a **`needs-review`** worksheet that automatically collects scenarios requiring follow‑up—specifically those marked as `matched_existing_scenario_new_estimate` or `new_estimate_candidate`—and serves as a ready‑to‑action queue for PMMs and pricing/content owners.

## Inventory health check

After the estimate comparison runs, the workflow performs a dedicated health check on every scenario already in `estimate_scenarios.xlsx`. This is the maintenance queue for the Pricing Calculator — it tells you which scenarios need to be retired, updated, or investigated.

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

### `inventory-health` worksheet

The `inventory-health` tab in `scan-results.xlsx` contains one row per inventory scenario with the following columns:

- **yml_url** — The canonical URL from `estimate_scenarios.xlsx`
- **title** — Title from `estimate_scenarios.xlsx`
- **estimate_link** — Estimate link from `estimate_scenarios.xlsx`
- **inventory_status** — One of the five status values above
- **redirect_target** — The final URL after following redirects (blank if no redirect)
- **http_status_code** — HTTP response code from the liveness check (blank for `scenario_removed` via Stage 1)
- **note** — Human-readable explanation of the status

The `summary` tab is also updated with an **Inventory Health** section showing counts for each status and the total number of scenarios needing action (`scenario_removed` + `scenario_redirected`).

## Image change detection

After the inventory health check, the workflow checks whether the primary architecture diagram for each `Published` scenario in `estimate_scenarios.xlsx` has changed since the last run. This helps you keep Pricing Calculator scenarios in sync with the latest diagrams published in the Architecture Center.

### How it works

For each `Published` row in `estimate_scenarios.xlsx` that has a `primary_image_path` value, the script:

1. Resolves the image file on disk (the Actions runner has a full repo clone, so no network calls are needed)
2. Computes a SHA-256 hash of the file's raw bytes
3. Compares that hash against the `primary_image_sha256` column in `estimate_scenarios.xlsx`
4. Records the result in the `image-changes` tab of `scan-results.xlsx`
5. Updates `primary_image_sha256` in `estimate_scenarios.xlsx` with the current hash, then commits the file back to the repo

SHA-256 hashing detects any change to the image content — including cases where a contributor replaces an image file in-place without changing the filename.

### `image_change_status` values

| Value | Meaning | Action |
|---|---|---|
| `unchanged` | Hash matches the stored baseline | No action needed |
| `changed` | Hash differs from baseline — image was updated in the repo | Review the updated diagram; update the Pricing Calculator image if needed |
| `new_baseline` | No stored hash yet (first run or new inventory row) | Hash recorded as the new baseline; no comparison was made |
| `image_not_found` | `primary_image_path` does not exist on disk | The file may have been moved, renamed, or deleted; verify and update the path in `estimate_scenarios.xlsx` |
| `skipped` | Row has `status != Published` or blank `primary_image_path` | No action needed |

### `image-changes` worksheet

The `image-changes` tab contains only actionable rows (`changed` and `image_not_found`) with the following columns:

- **yml_url** — Architecture Center article URL
- **title_in_calculator** — Title as it appears in the Pricing Calculator
- **primary_image_path** — Repo-relative path to the tracked image
- **image_change_status** — `changed` or `image_not_found`
- **stored_sha256** — The hash from the previous run (blank for `image_not_found`)
- **current_sha256** — The hash computed this run (blank for `image_not_found`)
- **note** — Human-readable explanation

### Reference file columns

`estimate_scenarios.xlsx` uses two image-related columns:

- **primary_image_path** — Repo-relative path to the image used in the Pricing Calculator (e.g. `docs/example-scenario/ai/media/diagram.svg`). You fill this in manually.
- **primary_image_sha256** — SHA-256 hash of the image file, auto-populated and updated by the workflow. Do not edit this column manually.

### Baseline update behaviour

The image hash baseline is **not** updated automatically during the monthly scan. This is intentional — a detected change must stay visible across every run until you have confirmed the update and actioned it. The workflow for updating the baseline is:

1. Monthly scan runs → `image-changes` tab flags a scenario with `changed`
2. You submit the image update request to the calculator team
3. Calculator team updates the scenario with the new image
4. You manually trigger the **Update Image Baseline** workflow from GitHub Actions
5. The workflow recomputes all hashes, saves them to `estimate_scenarios.xlsx`, and commits the file back to the repo
6. The next monthly scan compares against this newly confirmed baseline

**Important:** do not run the Update Image Baseline workflow to dismiss a detected change without first updating the Pricing Calculator. Doing so will silently lose the signal and the change will not be detected again unless the image changes further.

## Repository files and what they do

- `architecture-center/scripts/scan_architecture_center_yml.py`  
  Scans Architecture Center YAML files and their included Markdown articles (Pattern A), and also standalone Markdown articles that have no companion YAML file (Pattern B). Produces `scan-results.json`.

- `architecture-center/scripts/build_scan_results_xlsx.py`  
  Converts `scan-results.json` into the human‑readable Excel report `scan-results.xlsx`. This is the **authoritative JSON → Excel builder** and preserves **all compliant estimate links**.

- `architecture-center/estimate_scenarios.xlsx`  
  Reference inventory of known scenarios and their canonical estimate links. Used to detect new scenarios, updated estimates, and gaps.

- `architecture-center/scripts/run_compare_only.py`  
  Compares cost‑ready scenarios (`criteria_passed = TRUE`) against `estimate_scenarios.xlsx` and updates the `comparison_status` column, as well as additional review/summary tabs, in `scan-results.xlsx`.

- `architecture-center/scripts/run_inventory_health.py`  
  Performs a two-stage health check against every scenario in `estimate_scenarios.xlsx`: (1) a reverse lookup to detect scenarios whose source file has been deleted from the repo, and (2) an HTTP liveness check to detect scenarios whose URL has been removed from publishing or now redirects to a different page. Adds an `inventory-health` worksheet and a summary section to `scan-results.xlsx`.

- `architecture-center/scripts/run_image_check.py`  
  Detects image changes for `Published` scenarios in `estimate_scenarios.xlsx`. Hashes each `primary_image_path` file and compares it against the stored `primary_image_sha256` baseline. Updates the baseline in `estimate_scenarios.xlsx` after each run and adds an `image-changes` worksheet to `scan-results.xlsx`.

- `architecture-center/.github/workflows/scan_and_compare.yml`  
  GitHub Actions workflow that runs the monthly scan: scan → build Excel → compare estimates → inventory health check → image change detection (detect mode). Does **not** update the image hash baseline.

- `architecture-center/.github/workflows/update_image_baseline.yml`  
  Separate manually triggered workflow that recomputes and stores SHA-256 hashes for all Published scenarios. Run this only after you have confirmed the Pricing Calculator has been updated with the new image. Commits the refreshed `estimate_scenarios.xlsx` back to the repo.

## How to get started

### 1. Fork the Architecture Center repo

https://github.com/MicrosoftDocs/architecture-center

### 2. Copy scanner files

Copy the scanner files into the forked Architecture Center repo, preserving the same paths.

### 3. Run via GitHub Actions

- Open **GitHub Actions**
- Select **Architecture Scan + Estimate Comparison** workflow and run it

The monthly workflow runs five steps in sequence: scan → build Excel → compare estimates → inventory health check → image change detection (detect only, baseline not modified). A separate **Update Image Baseline** workflow handles baseline commits and is triggered manually after changes have been actioned.

## Outputs and how to interpret them

After a successful run, download `scan-results.xlsx` from the workflow artifacts.

### Key columns

- **title** — Article title (from the YAML file)
- **description** — Article description (from the YAML file)
- **azureCategories** — Azure solution categories from the YAML file
- **ms.date** — Freshness / prioritization signal
- **yml_url** — Published Architecture Center article URL
- **image_download_urls** — Images found in the article (informational)
- **estimate_link** — One or more usable estimate links (newline‑separated)
- **scan_status** — `ok` if the file parsed and resolved correctly; otherwise one of five structural error codes (see [Gate 1 — Scan status](#gate-1--scan-status) for the full description of each)
- **in_scope** — `TRUE` if the scenario passes all four scope criteria; `FALSE` otherwise (`scan_status = ok` rows only)
- **out_of_scope_reason** — Why the scenario is out of scope: semicolon-separated failing criteria, or `scan_error` for Gate 1 failures
- **criteria_passed** — Pricing readiness indicator (`in_scope = TRUE` rows only)
- **failure_reason** — Why the scenario failed (if applicable)
- **comparison_status** — Estimate comparison result
- **yml_path** — Path to the scenario YAML file
- **include_md_path** — Path to the included Markdown article
- **md_author_name / md_ms_author_name** — Ownership context.

### How to use the results

- Treat `scan_status != ok` rows as **structural file issues** — the YML or MD file has a problem that needs fixing before the scenario can be evaluated at all.
- Treat `scan_status = ok` + `in_scope = FALSE` rows as **out-of-scope scenarios** that need content work (missing title, description, category, or architecture image) before they can be considered for pricing readiness.
- Treat `in_scope = TRUE` + `criteria_passed = FALSE` as **pricing gaps**, where a usable estimate link needs to be added to the Architecture Center article.
- For any `criteria_passed = TRUE`, use `comparison_status` to determine whether the scenario is **net new** or an **existing scenario with an updated estimate link.** In both cases, this indicates a need to update the Pricing Calculator — either by adding a new estimate scenario or updating an existing one.
- Use the **`inventory-health`** tab to maintain scenarios already in the Pricing Calculator. `scenario_removed` and `scenario_redirected` rows are your action queue for retiring or updating calculator scenarios whose Architecture Center pages have changed.
- Use the **`image-changes`** tab to track architecture diagram updates. `changed` rows mean the primary image was modified in the repo since the last confirmed baseline and may need to be updated in the Pricing Calculator. After actioning a change, trigger the **Update Image Baseline** workflow to reset the baseline. `image_not_found` rows mean the tracked image path is no longer valid and needs to be corrected in `estimate_scenarios.xlsx`.
