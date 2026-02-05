# Architecture Center YAML Criteria Scanner (Fork-friendly) — v3.3

This repo add-on scans `docs/**/*.yml` in your fork of `MicrosoftDocs/architecture-center`.

## Criteria (ALL must be true)

1. YAML has a `content` string containing an INCLUDE directive referencing a `.md` file.
2. Included `.md` contains at least one diagram reference in one of these formats: `.svg`, `.png`, `.jpg`, `.jpeg`.
3. Included `.md` contains at least one link matching either:
   - `https://azure.com/e/...`
   - `https://azure.microsoft.com/pricing/calculator/...` (any calculator link)

## What you get

The workflow produces:
- `scan-results.json`
- `scan-results.xlsx` (3 tabs: items_flat, links, images)
- `scan-results_flat.csv`
- `scan-results_links.csv`
- `scan-results_images.csv`
- `scan-debug.json` (counters + sample skipped reasons)

## Run

In your fork:
1. **Actions** → **Scan Architecture Center YAML Criteria**
2. **Run workflow**
3. Download artifacts:
   - **scan-results** (json/xlsx/csv)
   - **scan-debug** (debug json)

## Output fields (per item)

- Title/Description/AzureCategories from YAML metadata
- `yml_url` (clickable Learn URL) + `yml_github_url`
- `image_paths`, `image_download_urls`, `image_formats`
- SVG-only compatibility: `svg_paths`, `svg_download_urls`
- Links: `azure_experience_links`, `pricing_calculator_links`, `shared_estimate_links`, `all_matching_links`
