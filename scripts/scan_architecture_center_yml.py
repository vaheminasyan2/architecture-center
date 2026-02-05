#!/usr/bin/env python3
"""Architecture Center YAML Criteria Scanner (v3.3.1)

Includes v3.3 functionality + debug artifacts.

Criteria (ALL must be true):
1) docs/**/*.yml contains a `content` string with an INCLUDE directive referencing a `.md` file.
2) Included `.md` contains at least one diagram reference with extension in {svg,png,jpg,jpeg}.
3) Included `.md` contains at least one link matching either:
   - https://azure.com/e/...
   - https://azure.microsoft.com/pricing/calculator/...

Outputs scan-results.json and (when --debug) scan-debug.json.
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

INCLUDE_RE = re.compile(r"\[!INCLUDE\s*\[\s*\]\s*\(\s*([^\)\s]+\.md)\s*\)\s*\]", re.IGNORECASE)
AZURE_E_RE = re.compile(r"https?://azure\.com/e/[^\s\)\]\"']+", re.IGNORECASE)
PRICING_CALC_ANY_RE = re.compile(r"https?://azure\.microsoft\.com/pricing/calculator/[^\s\)\]\"']*", re.IGNORECASE)
SHARED_ESTIMATE_RE = re.compile(r"https?://azure\.microsoft\.com/pricing/calculator/\?shared-estimate=[^\s\)\]\"']+", re.IGNORECASE)
IMAGE_RE = re.compile(r"[^\s\)\]\"']+\.(?:svg|png|jpg|jpeg)", re.IGNORECASE)


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
    p = repo_rel_yml.replace('\\', '/')
    if p.startswith('docs/'):
        p = p[len('docs/'):]
    if p.lower().endswith('.yml'):
        p = p[:-4]
    return f"https://learn.microsoft.com/en-us/azure/architecture/{p}"


def clean_ref(ref: str) -> str:
    return ref.strip().strip('"').strip("'").strip().strip('()<>[]')


def resolve_repo_rel(base_dir: Path, ref: str, repo_root: Path):
    ref = clean_ref(ref)
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


def scan(repo_root: Path, repo_slug: str, branch: str, docs_root: str, debug: bool):
    docs_path = repo_root / docs_root

    counts = {
        'yml_total': 0,
        'yml_parsed': 0,
        'has_content': 0,
        'has_include': 0,
        'include_md_exists': 0,
        'md_has_images': 0,
        'md_has_links': 0,
        'matched': 0,
    }
    skipped = []
    results = []

    for yml_path in docs_path.rglob('*.yml'):
        counts['yml_total'] += 1
        repo_rel_yml = yml_path.relative_to(repo_root).as_posix()

        data = load_yaml(yml_path)
        if not isinstance(data, dict):
            if debug:
                skipped.append({'yml_path': repo_rel_yml, 'reason': 'yaml_parse_failed'})
            continue
        counts['yml_parsed'] += 1

        title = None
        description = None
        md_meta = data.get('metadata') if isinstance(data.get('metadata'), dict) else None
        if md_meta:
            title = md_meta.get('title')
            description = md_meta.get('description')
        title = title or data.get('title')
        description = description or data.get('description')

        azure_categories = as_list(data.get('azureCategories'))

        content = data.get('content')
        if not isinstance(content, str):
            if debug:
                skipped.append({'yml_path': repo_rel_yml, 'reason': 'missing_content_string'})
            continue
        counts['has_content'] += 1

        inc = INCLUDE_RE.search(content)
        if not inc:
            if debug:
                skipped.append({'yml_path': repo_rel_yml, 'reason': 'no_include_directive'})
            continue
        counts['has_include'] += 1

        include_md_ref = inc.group(1)
        include_md_rel = resolve_repo_rel(yml_path.parent, include_md_ref, repo_root)
        if not include_md_rel:
            if debug:
                skipped.append({'yml_path': repo_rel_yml, 'reason': 'include_md_unresolvable', 'include_md_ref': include_md_ref})
            continue

        md_file = repo_root / include_md_rel
        if not md_file.exists():
            if debug:
                skipped.append({'yml_path': repo_rel_yml, 'reason': 'include_md_missing', 'include_md_path': include_md_rel})
            continue
        counts['include_md_exists'] += 1

        md_text = md_file.read_text(encoding='utf-8', errors='ignore')

        azure_experience_links = sorted(set(AZURE_E_RE.findall(md_text)))
        pricing_calculator_links = sorted(set(PRICING_CALC_ANY_RE.findall(md_text)))
        shared_estimate_links = sorted(set(SHARED_ESTIMATE_RE.findall(md_text)))

        if not (azure_experience_links or pricing_calculator_links):
            if debug:
                skipped.append({'yml_path': repo_rel_yml, 'reason': 'no_matching_links', 'include_md_path': include_md_rel})
            continue
        counts['md_has_links'] += 1

        image_refs_raw = sorted(set(IMAGE_RE.findall(md_text)))
        if not image_refs_raw:
            if debug:
                skipped.append({'yml_path': repo_rel_yml, 'reason': 'no_image_refs', 'include_md_path': include_md_rel})
            continue
        counts['md_has_images'] += 1

        image_paths, image_download_urls, image_exists, image_formats = [], [], [], []
        svg_paths, svg_download_urls, svg_exists = [], [], []

        for img_ref in image_refs_raw:
            img_ref = clean_ref(img_ref)
            fmt = img_ref.split('.')[-1].lower() if '.' in img_ref else None

            img_rel = resolve_repo_rel(md_file.parent, img_ref, repo_root)
            if img_rel is None:
                img_rel = img_ref.strip().lstrip('/')

            image_paths.append(img_rel)
            image_download_urls.append(make_raw_url(repo_slug, branch, img_rel))
            exists = bool((repo_root / img_rel).exists())
            image_exists.append(exists)
            image_formats.append(fmt)

            if fmt == 'svg':
                svg_paths.append(img_rel)
                svg_download_urls.append(make_raw_url(repo_slug, branch, img_rel))
                svg_exists.append(exists)

        all_matching_links = sorted(set(azure_experience_links + pricing_calculator_links))

        results.append({
            'criteria_passed': True,
            'title': title,
            'description': description,
            'azureCategories': azure_categories,
            'yml_url': make_learn_url_from_docs_path(repo_rel_yml),
            'yml_github_url': make_github_blob_url(repo_slug, branch, repo_rel_yml),
            'yml_path': repo_rel_yml,
            'include_md_path': include_md_rel,
            'include_md_github_url': make_github_blob_url(repo_slug, branch, include_md_rel),
            'image_paths': image_paths,
            'image_download_urls': image_download_urls,
            'image_exists_in_repo': image_exists,
            'image_formats': image_formats,
            'svg_paths': svg_paths,
            'svg_download_urls': svg_download_urls,
            'svg_exists_in_repo': svg_exists,
            'azure_experience_links': azure_experience_links,
            'pricing_calculator_links': pricing_calculator_links,
            'shared_estimate_links': shared_estimate_links,
            'all_matching_links': all_matching_links,
        })
        counts['matched'] += 1

    return results, counts, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', default=None, help='Repo slug (default: GITHUB_REPOSITORY)')
    ap.add_argument('--branch', default='main')
    ap.add_argument('--docs-root', default='docs')
    ap.add_argument('--output', default='scan-results.json')
    ap.add_argument('--debug', action='store_true', help='Write scan-debug.json with counters + skipped reasons')
    args = ap.parse_args()

    repo_slug = args.repo or os.getenv('GITHUB_REPOSITORY') or 'MicrosoftDocs/architecture-center'
    repo_root = Path.cwd()

    items, counts, skipped = scan(repo_root, repo_slug, args.branch, args.docs_root, args.debug)

    out = {
        'repo': repo_slug,
        'branch': args.branch,
        'docs_root': args.docs_root,
        'count': len(items),
        'items': items,
    }

    Path(args.output).write_text(json.dumps(out, indent=2), encoding='utf-8')
    print(f"Wrote {len(items)} matching items to {args.output}")

    if args.debug:
        dbg = {
            'counts': counts,
            'skipped_total': len(skipped),
            'skipped_sample': skipped[:400],
        }
        Path('scan-debug.json').write_text(json.dumps(dbg, indent=2), encoding='utf-8')
        print(f"Wrote debug to scan-debug.json (skipped_total={len(skipped)})")


if __name__ == '__main__':
    main()
