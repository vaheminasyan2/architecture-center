# Architecture Center YAML Criteria Scanner (Fork-friendly) — v3.3.4

## Link categorization
The scanner categorizes pricing calculator links into:
1. **calculator_root_links**: `https://azure.microsoft.com/pricing/calculator` or `https://azure.microsoft.com/<locale>/pricing/calculator` (optional trailing slash).
2. **shared_estimate_links**: union of:
   - `https://azure.com/e/*` (treated as shared estimates)
   - `https://azure.microsoft.com/<locale>/pricing/calculator/?shared-estimate=*`

Other calculator URLs are captured as **calculator_other_links**.

## Criteria (ALL must be true)
1. YAML has a `content` string containing an INCLUDE directive referencing a `.md` file.
2. Included `.md` contains at least one architecture diagram image in: `.svg`, `.png`, `.jpg`, `.jpeg`.
3. Included `.md` contains at least one qualifying link in any category above.

## Outputs
- **scan-results**: JSON + XLSX + CSVs
- **scan-debug**: debug JSON + CSVs (counts + skipped sample)

Run: Actions → **Scan Architecture Center YAML Criteria** → Run workflow.
