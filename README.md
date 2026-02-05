# Architecture Center YAML Criteria Scanner (Fork-friendly) — v3.3.2

## Key change
Image criteria applies only to the `## Architecture` section of the included markdown.

## Criteria (ALL must be true)
1. YAML has a `content` string containing an INCLUDE directive referencing a `.md` file.
2. Included `.md` has a `## Architecture` section containing at least one diagram reference in: `.svg`, `.png`, `.jpg`, `.jpeg`.
3. Included `.md` contains at least one link matching either:
   - `https://azure.com/e/...`
   - `https://azure.microsoft.com/pricing/calculator/...`

## Outputs
- **scan-results**: JSON + XLSX + CSVs
- **scan-debug**: debug JSON + CSVs (counts + skipped sample)

Run: Actions → **Scan Architecture Center YAML Criteria** → Run workflow.
