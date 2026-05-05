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

## Repository files and what they do

- `architecture-center/scripts/scan_architecture_center_yml.py`  
  Scans Architecture Center YAML files and their included Markdown articles (Pattern A), and also standalone Markdown articles that have no companion YAML file (Pattern B). Produces `scan-results.json`.

- `architecture-center/scripts/build_scan_results_xlsx.py`  
  Converts `scan-results.json` into the human‑readable Excel report `scan-results.xlsx`. This is the **authoritative JSON → Excel builder** and preserves **all compliant estimate links**.

- `architecture-center/estimate_scenarios.xlsx`  
  Reference inventory of known scenarios and their canonical estimate links. Used to detect new scenarios, updated estimates, and gaps.

- `architecture-center/scripts/run_compare_only.py`  
  Compares cost‑ready scenarios (`criteria_passed = TRUE`) against `estimate_scenarios.xlsx` and updates the `comparison_status` column, as well as additional review/summary tabs, in `scan-results.xlsx`.

- `architecture-center/.github/workflows/scan_and_compare.yml`  
  GitHub Actions workflow that runs the scan, builds the Excel report, performs estimate comparison, and uploads the artifact.

## How to get started

### 1. Fork the Architecture Center repo

https://github.com/MicrosoftDocs/architecture-center

### 2. Copy scanner files

Copy the scanner files into the forked Architecture Center repo, preserving the same paths.

### 3. Run via GitHub Actions

- Open **GitHub Actions**
- Select **Architecture Scan + Estimate Comparison** workflow and run it

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
