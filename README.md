# Architecture Center YAML Criteria Scanner (Fork-friendly) — v3

This adds a GitHub Actions workflow + Python scanner to your fork of `MicrosoftDocs/architecture-center`.

## Criteria (ALL must be true)

1. `docs/**/*.yml` contains a `content` string with an INCLUDE directive referencing a `.md` file (e.g., `[!INCLUDE [] (file.md)]`).
2. The included `.md` contains at least one `.svg` reference.
3. The included `.md` contains at least one link matching **either**:
   - `https://azure.com/e/...`
   - `https://azure.microsoft.com/pricing/calculator/?shared-estimate=...`

Architecture Center `.yml` files commonly include `metadata.title`, `metadata.description`, `azureCategories`, and a `content: |` block with an include reference, as seen in examples like `guidance.yml` where `content: | [!include [] (guidance-content.md)]`. citeturn26search138turn26search142turn26search143

## Run

In your fork:
1. Go to **Actions**
2. Select **Scan Architecture Center YAML Criteria**
3. Click **Run workflow**
4. Download the artifact **scan-results** → `scan-results.json`

## Output fields (per item)

- `title`, `description`, `azureCategories`
- `yml_url` (clickable Learn URL, best-effort) + `yml_github_url` (source) + `yml_path`
- `include_md_path` + `include_md_github_url`
- `svg_paths`, `svg_download_urls`, `svg_exists_in_repo`
- `azure_experience_links` (ALL matches)
- `shared_estimate_links` (ALL matches)
- `all_matching_links` (combined, deduped)

> Note: `yml_url` is derived from the repo path using a consistent mapping pattern. If any page doesn’t resolve due to redirects or special routing, you still have `yml_github_url` as a fallback.
