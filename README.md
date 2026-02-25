# MS Architecture Center Scanner

A lightweight scanning tool used to analyze **https://learn.microsoft.com/en-us/azure/architecture/browse/** to determine scenarios that include a **usable Azure Pricing Calculator estimate link** and compare them against a reference list of known scenarios. The outputs help identify pricing‑ready scenarios, detect updated estimate links (estimate drift), and highlight gaps.

## What the scanner evaluates

### Primary question (pass / fail)

The scanner answers the primary question: **Does the Architecture Center article include a usable pricing estimate link?**

A scenario **passes (`criteria_passed = TRUE`)** if the included Markdown article contains **at least one** of the following:

1. **Azure Experience / Pricing Calculator shared estimate links**  
   `https://azure.com/e/*` **or** `https://azure.microsoft.com/pricing/calculator?...shared-estimate=*`

2. **Service‑scoped Pricing Calculator estimate link**  
   `https://azure.microsoft.com/pricing/calculator?...service=*`

> **Important:** Pricing Calculator tool/root links (for example, `/pricing/calculator` without a saved or scoped estimate) do **not** count as usable estimates.

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

- `scripts/scan_architecture_center_yml.py`  
  Scans Architecture Center YAML files and their included Markdown articles. Produces `scan-results.json`.

- `scripts/build_scan_results_xlsx.py`  
  Converts `scan-results.json` into the human‑readable Excel report `scan-results.xlsx`. This is the **authoritative JSON → Excel builder** and preserves **all compliant estimate links**.

- `estimate_scenarios.xlsx`  
  Reference inventory of known scenarios and their canonical estimate links. Used to detect new scenarios, updated estimates, and gaps.

- `scripts/run_compare_only.py`  
  Compares cost‑ready scenarios (`criteria_passed = TRUE`) against `estimate_scenarios.xlsx` and updates the `comparison_status` column, as well as additional review/summary tabs, in `scan-results.xlsx`.

- `.github/workflows/scan_and_compare.yml`  
  GitHub Actions workflow that runs the scan, builds the Excel report, performs estimate comparison, and uploads the artifact.

## How to get started

### 1. Fork the Architecture Center repo

https://github.com/MicrosoftDocs/architecture-center

### 2. Copy scanner files

Copy the scanner files into the forked Architecture Center repo, preserving the same paths.

### 3. Run via GitHub Actions

- Push changes to your fork
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
- **criteria_passed** — Pricing readiness indicator
- **failure_reason** — Why the scenario failed (if applicable)
- **comparison_status** — Estimate comparison result
- **yml_path** — Path to the scenario YAML file
- **include_md_path** — Path to the included Markdown article
- **md_author_name / md_ms_author_name** — Ownership context.

### How to use the results

- Treat `criteria_passed = FALSE` as **pricing gaps**, where a usable estimate link needs to be added to the Architecture Center article.
- For any `criteria_passed = TRUE`, use `comparison_status` to determine whether the scenario is **net new** or an **existing scenario with an updated estimate link.** In both cases, this indicates a need to update the Pricing Calculator — either by adding a new estimate scenario or updating an existing one.
