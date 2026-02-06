#!/usr/bin/env python3
"""Architecture Center YAML Criteria Scanner (v3.3.3)

Updates in this version (per your findings):
- Removed the strict `## Architecture` section requirement.
- Detects architecture diagram images ANYWHERE in the included markdown, but:
  * Excludes obvious thumbnails/browse images
  * Uses heuristics to focus on *architecture diagrams*, not incidental images.
- Supports BOTH markdown image styles:
  1) Direct-path images, including Docs `:::image ... source="...svg"` and standard `![](...svg)`
  2) Reference-style images like: `![Architecture diagram][architecture]` with a later
     `[architecture]: ./images/foo.svg` definition.

Criteria (ALL must be true):
1) docs/**/*.yml contains a `content` string with an INCLUDE directive referencing a `.md` file.
2) Included `.md` contains >=1 *architecture diagram image* in {svg,png,jpg,jpeg} (heuristic).
3) Included `.md` contains >=1 link matching either:
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

# Any direct image ref
IMG_EXT_RE = r"(?:svg|png|jpg|jpeg)"
IMAGE_PATH_RE = re.compile(rf"[^\s\)\]\"']+\.(?:{IMG_EXT_RE})", re.IGNORECASE)

# Reference-style definitions and uses
REF_DEF_RE = re.compile(r"(?im)^\[([^\]]+)\]:\s*(\S+)")
REF_USE_RE = re.compile(r"!\[[^\]]*\]\[([^\]]+)\]")

# HTML <img src="...">
HTML_IMG_RE = re.compile(rf"(?i)<img[^>]+src=[\"']([^\"']+\.(?:{IMG_EXT_RE}))")

# Obvious non-diagram image locations
THUMB_EXCLUDE_RE = re.compile(r"(?i)(/browse/thumbs/|\bthumbs/|thumbnail|social_image|/icons/)")

# Heuristic: likely architecture diagram
ARCH_HINT_RE = re.compile(r"(?i)\b(architecture|diagram|reference\s*architecture|network\s*topology|dataflow)\b")


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


def extract_reference_map(md_text: str):
    """Map reference ids to paths/urls: [architecture]: ./images/foo.svg"""
    m = {}
    for key, target in REF_DEF_RE.findall(md_text):
        m[key.strip().lower()] = clean_ref(target)
    return m


def is_likely_architecture_image(img_path: str, context_line: str, ref_key: str | None = None) -> bool:
    """Heuristic filter to focus on architecture diagrams."""
    p = (img_path or '').lower()
    line = (context_line or '').lower()
    key = (ref_key or '').lower()

    # exclude thumbnails/icons etc.
    if THUMB_EXCLUDE_RE.search(p) or THUMB_EXCLUDE_RE.search(line):
        return False

    # strong signals
    if ':::image' in line:
        return True
    if key in ('architecture', 'arch', 'architecturediagram', 'architecture-diagram', 'diagram'):
        return True
    if ARCH_HINT_RE.search(line):
        return True

    # filename hints
    fname = p.split('/')[-1]
    if ARCH_HINT_RE.search(fname):
        return True

    # folder hints common in archcenter
    if '/_images/' in p or '/images/' in p or '/media/' in p:
        # still require *some* hint in filename to avoid grabbing generic screenshots
        if ARCH_HINT_RE.search(fname):
            return True

    return False


def find_architecture_images(md_text: str):
    """Return list of (raw_ref, ref_key, context_line) for likely architecture images."""
    lines = md_text.splitlines()
    ref_map = extract_reference_map(md_text)

    found = []

    # 1) direct-path references (scan each line to get context)
    for line in lines:
        for raw in IMAGE_PATH_RE.findall(line):
            raw2 = clean_ref(raw)
            if is_likely_architecture_image(raw2, line):
                found.append((raw2, None, line))

    # 2) html img tags
    for line in lines:
        for raw in HTML_IMG_RE.findall(line):
            raw2 = clean_ref(raw)
            if is_likely_architecture_image(raw2, line):
                found.append((raw2, None, line))

    # 3) reference-style images
    for line in lines:
        for ref_key in REF_USE_RE.findall(line):
            key_l = ref_key.strip().lower()
            target = ref_map.get(key_l)
            if not target:
                continue
            # only include if target looks like supported image
            if not re.search(rf"\.(?:{IMG_EXT_RE})$", target, re.IGNORECASE):
                continue
            if is_likely_architecture_image(target, line, ref_key=key_l):
                found.append((target, key_l, line))

    # de-dupe by path
    seen = set()
    out = []
    for raw, key, line in found:
        k = raw.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append((raw, key, line))
    return out


def scan(repo_root: Path, repo_slug: str, branch: str, docs_root: str, debug: bool):
    docs_path = repo_root / docs_root

    counts = {
        'yml_total': 0,
        'yml_parsed': 0,
        'has_content': 0,
        'has_include': 0,
        'include_md_exists': 0,
        'md_has_links_any': 0,
        'md_has_arch_images_any': 0,
        'md_arch_images_only': 0,
        'md_links_only': 0,
        'md_images_and_links': 0,
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

        # Links
        azure_experience_links = sorted(set(AZURE_E_RE.findall(md_text)))
        pricing_calculator_links = sorted(set(PRICING_CALC_ANY_RE.findall(md_text)))
        shared_estimate_links = sorted(set(SHARED_ESTIMATE_RE.findall(md_text)))
        has_links_any = bool(azure_experience_links or pricing_calculator_links)
        if has_links_any:
            counts['md_has_links_any'] += 1

        # Images (architecture diagrams, heuristics)
        arch_imgs = find_architecture_images(md_text)
        has_arch_imgs_any = bool(arch_imgs)
        if has_arch_imgs_any:
            counts['md_has_arch_images_any'] += 1

        # cross-counts
        if has_arch_imgs_any and not has_links_any:
            counts['md_arch_images_only'] += 1
        elif has_links_any and not has_arch_imgs_any:
            counts['md_links_only'] += 1
        elif has_links_any and has_arch_imgs_any:
            counts['md_images_and_links'] += 1

        # Apply criteria
        if not has_links_any:
            if debug:
                skipped.append({'yml_path': repo_rel_yml, 'reason': 'no_matching_links', 'include_md_path': include_md_rel})
            continue

        if not has_arch_imgs_any:
            if debug:
                skipped.append({'yml_path': repo_rel_yml, 'reason': 'no_architecture_images', 'include_md_path': include_md_rel})
            continue

        # Build image outputs
        image_paths, image_download_urls, image_exists, image_formats = [], [], [], []
        svg_paths, svg_download_urls, svg_exists = [], [], []

        for img_ref, _key, _line in arch_imgs:
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
            'architecture_image_heuristic': True,
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
    ap.add_argument('--debug', action='store_true', help='Write scan-debug.json with counters + sample skipped reasons')
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
            'skipped_sample': skipped[:800],
        }
        Path('scan-debug.json').write_text(json.dumps(dbg, indent=2), encoding='utf-8')
        print(f"Wrote debug to scan-debug.json (skipped_total={len(skipped)})")


if __name__ == '__main__':
    main()
