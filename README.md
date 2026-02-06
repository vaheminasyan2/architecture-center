# Architecture Center YAML Criteria Scanner (Fork-friendly) — v3.3.3

## Key changes
- Removed the strict `## Architecture` section requirement.
- Added support for reference-style images: `![Architecture diagram][architecture]` + `[architecture]: ./path/to/file.svg`.
- Still focuses on architecture diagrams via a lightweight heuristic (and excludes thumbnails).

## Criteria (ALL must be true)
1. YAML has a `content` string containing an INCLUDE directive referencing a `.md` file.
2. Included `.md` contains at least one *architecture diagram image* in: `.svg`, `.png`, `.jpg`, `.jpeg`.
3. Included `.md` contains at least one link matching either:
   - `https://azure.com/e/...`
   - `https://azure.microsoft.com/pricing/calculator/...`

## Outputs
- **scan-results**: JSON + XLSX + CSVs
- **scan-debug**: debug JSON + CSVs (counts + skipped sample)

Run: Actions → **Scan Architecture Center YAML Criteria** → Run workflow.
