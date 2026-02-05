#!/usr/bin/env python3
"""Architecture Center YAML Criteria Scanner (v3)

Scans `docs/**/*.yml` for items that meet ALL criteria:
1) YAML has a `content` string containing an INCLUDE directive that references a `.md` file.
2) The included `.md` contains at least one `.svg` reference.
3) The included `.md` contains at least one link matching EITHER:
   - https://azure.com/e/... 
   - https://azure.microsoft.com/pricing/calculator/?shared-estimate=...

Outputs `scan-results.json` with reviewer-friendly fields:
- title, description, azureCategories
- yml_url (clickable web page URL, best-effort Learn mapping)
- yml_github_url (source)
- include_md_github_url
- svg_download_urls (raw GitHub URLs)
- azure_experience_links (all) + shared_estimate_links (all) + all_matching_links (combined)

Designed to run in GitHub Actions after actions/checkout.
"""

import argparse
import json
import os
import re
from pathlib import Path

try:
    import yaml  # PyYAML
except Exception:
    yaml = None

# Matches: [!INCLUDE [] (file.md)]  (allow casing/spaces)
INCLUDE_RE = re.compile(r"\[!INCLUDE\s*\[\s*\]\s*\(\s*([^\)\s]+\.md)\s*\)\s*\]", re.IGNORECASE)

AZURE_E_RE = re.compile(r"https?://azure\.com/e/[^\s\)\]\"']+", re.IGNORECASE)
SHARED_ESTIMATE_RE = re.compile(r"https?://azure\.microsoft\.com/pricing/calculator/\?shared-estimate=[^\s\)\]\"']+", re.IGNORECASE)

# capture relative/absolute svg refs in markdown images/links/html
SVG_RE = re.compile(r"([^\s\)\]\"']+\.svg)", re.IGNORECASE)


def load_yaml(path: Path):
    if yaml is None:
        return None
    try:
        return yaml.safe_load(path.read_text(encoding='utf-8', errors='ignore'))
    except Exception:
        return None


def as_list(val):
    if val is None:
        return []
    if isinstance(val, list):
        return val
    return [val]


def make_raw_url(repo_slug: str, branch: str, repo_rel_path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo_slug}/{branch}/{repo_rel_path.lstrip('/')}"


def make_github_blob_url(repo_slug: str, branch: str, repo_rel_path: str) -> str:
    return f"https://github.com/{repo_slug}/blob/{branch}/{repo_rel_path.lstrip('/')}"


def make_learn_url_from_docs_path(repo_rel_yml: str) -> str:
    """Best-effort mapping from repo `docs/.../*.yml` to Learn URL.

    Rule:
      docs/<path>/<name>.yml -> https://learn.microsoft.com/en-us/azure/architecture/<path>/<name>

    This matches common Architecture Center patterns but may not be exact for all pages.
    """
    p = repo_rel_yml.replace('\\', '/')
    if p.startswith('docs/'):
        p = p[len('docs/'):]
    if p.lower().endswith('.yml'):
        p = p[:-4]
    return f"https://learn.microsoft.com/en-us/azure/architecture/{p}"


def resolve_repo_rel(base_dir: Path, ref: str, repo_root: Path):
    ref = ref.strip().strip('"').strip("'")
    if re.match(r"^[a-zA-Z]+://", ref):
        return None
    while ref.startswith('./'):
        ref = ref[2:]
    ref = ref.lstrip('/')
    p = (base_dir / ref).resolve()
    try:
        rel = p.relative_to(repo_root.resolve())
        return rel.as_posix()
    except Exception:
        return None


def scan(repo_root: Path, repo_slug: str, branch: str, docs_root: str):
    docs_path = repo_root / docs_root
    results = []

    for yml_path in docs_path.rglob('*.yml'):
        data = load_yaml(yml_path)
        if not isinstance(data, dict):
            continue

        # title/description often live under metadata
        title = None
        description = None
        md = data.get('metadata') if isinstance(data.get('metadata'), dict) else None
        if md:
            title = md.get('title')
            description = md.get('description')
        title = title or data.get('title')
        description = description or data.get('description')

        azure_categories = as_list(data.get('azureCategories'))
        content = data.get('content')
        if not isinstance(content, str):
            continue

        inc = INCLUDE_RE.search(content)
        if not inc:
            continue

        include_md_ref = inc.group(1)
        include_md_rel = resolve_repo_rel(yml_path.parent, include_md_ref, repo_root)
        if not include_md_rel:
            continue

        md_file = repo_root / include_md_rel
        if not md_file.exists():
            continue

        md_text = md_file.read_text(encoding='utf-8', errors='ignore')

        # Links criteria: Azure E OR shared-estimate
        azure_experience_links = sorted(set(AZURE_E_RE.findall(md_text)))
        shared_estimate_links = sorted(set(SHARED_ESTIMATE_RE.findall(md_text)))
        if not (azure_experience_links or shared_estimate_links):
            continue

        svg_refs = sorted(set(SVG_RE.findall(md_text)))
        if not svg_refs:
            continue

        svg_paths = []
        svg_download_urls = []
        svg_exists = []

        for svg_ref in svg_refs:
            svg_rel = resolve_repo_rel(md_file.parent, svg_ref, repo_root)
            if svg_rel is None:
                svg_rel = svg_ref.strip().lstrip('/')
            svg_paths.append(svg_rel)
            svg_download_urls.append(make_raw_url(repo_slug, branch, svg_rel))
            svg_exists.append(bool((repo_root / svg_rel).exists()))

        repo_rel_yml = yml_path.relative_to(repo_root).as_posix()

        all_matching_links = sorted(set(azure_experience_links + shared_estimate_links))

        results.append({
            'criteria_passed': True,
            'title': title,
            'description': description,
            'azureCategories': azure_categories,

            # Requested: clickable web page URL (instead of just yml path)
            'yml_url': make_learn_url_from_docs_path(repo_rel_yml),
            'yml_github_url': make_github_blob_url(repo_slug, branch, repo_rel_yml),
            'yml_path': repo_rel_yml,

            # Included markdown
            'include_md_path': include_md_rel,
            'include_md_github_url': make_github_blob_url(repo_slug, branch, include_md_rel),

            # SVGs
            'svg_paths': svg_paths,
            'svg_download_urls': svg_download_urls,
            'svg_exists_in_repo': svg_exists,

            # Links
            'azure_experience_links': azure_experience_links,
            'shared_estimate_links': shared_estimate_links,
            'all_matching_links': all_matching_links,
            'azure_experience_links_valid': all(u.lower().startswith('https://azure.com/e/') for u in azure_experience_links) if azure_experience_links else True,
            'shared_estimate_links_valid': all(u.lower().startswith('https://azure.microsoft.com/pricing/calculator/?shared-estimate=') for u in shared_estimate_links) if shared_estimate_links else True,
        })

    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', default=None, help='Repo slug like MicrosoftDocs/architecture-center (default: GITHUB_REPOSITORY)')
    ap.add_argument('--branch', default='main', help='Branch name used to generate URLs')
    ap.add_argument('--docs-root', default='docs', help='Docs folder to scan (default: docs)')
    ap.add_argument('--output', default='scan-results.json', help='Output JSON path')
    args = ap.parse_args()

    repo_slug = args.repo or os.getenv('GITHUB_REPOSITORY') or 'MicrosoftDocs/architecture-center'
    repo_root = Path.cwd()

    items = scan(repo_root, repo_slug, args.branch, args.docs_root)

    out = {
        'repo': repo_slug,
        'branch': args.branch,
        'docs_root': args.docs_root,
        'count': len(items),
        'items': items,
    }

    Path(args.output).write_text(json.dumps(out, indent=2), encoding='utf-8')
    print(f"Wrote {len(items)} matching items to {args.output}")


if __name__ == '__main__':
    main()
