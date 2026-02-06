# Architecture Center YAML Criteria Scanner (Fork-friendly) — v3.3.5

## Added fields
- Debug skipped rows now include (when available): `title`, `description`, `azureCategories`, `yml_url`.
- Results and debug include author fields:
  - `md_author_github`
  - `md_ms_author`

## Link categorization
- `calculator_root_links` for localized calculator root URLs.
- `shared_estimate_links` includes both `https://azure.com/e/*` and calculator shared-estimate links.

Run: Actions → **Scan Architecture Center YAML Criteria** → Run workflow.
