# Architecture Center YAML Criteria Scanner (Fork-friendly) — v3.3.1

This bundle scans `docs/**/*.yml` in your fork of `MicrosoftDocs/architecture-center`.

## Criteria (ALL must be true)
1. YAML has a `content` string containing an INCLUDE directive referencing a `.md` file.
2. Included `.md` contains at least one diagram reference in: `.svg`, `.png`, `.jpg`, `.jpeg`.
3. Included `.md` contains at least one link matching either:
   - `https://azure.com/e/...`
   - `https://azure.microsoft.com/pricing/calculator/...`

## Outputs
Workflow uploads two artifacts:
- **scan-results**: `scan-results.json`, `scan-results.xlsx`, plus CSVs.
- **scan-debug**: `scan-debug.json` plus Excel-friendly CSVs:
  - `scan-debug_counts.csv`
  - `scan-debug_skipped_sample.csv`

## Run
Actions → **Scan Architecture Center YAML Criteria** → **Run workflow**.
