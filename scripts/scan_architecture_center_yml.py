#!/usr/bin/env python3
"""Architecture Center YAML Criteria Scanner (stable)

Emits ONE item per YAML file under docs-root (both *.yml and *.yaml).
Each item includes:
  - criteria_passed: bool
  - failure_reason: string when criteria_passed is False
  - metadata (title/description/azureCategories) when available
  - link buckets and image buckets (empty when not applicable)

Outputs:
  - scan-results.json (always)
  - scan-debug.json (optional, with counts + sample failures)
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

AZURE_E_RE = re.compile(r"https?://azure\.com/e/[^\s\)\]\\\"']+", re.IGNORECASE)
LOCALE_SEG = r"(?:[a-z]{2}-[a-z]{2}/)?"
CALC_ROOT_RE = re.compile(rf"https?://azure\.microsoft\.com/{LOCALE_SEG}pricing/calculator/?(?=$|[\s\)\]\\\"'])", re.IGNORECASE)
CALC_ANY_RE = re.compile(rf"https?://azure\.microsoft\.com/{LOCALE_SEG}pricing/calculator[^\s\)\]\\\"']*", re.IGNORECASE)

IMG_EXT_RE = r"(?:svg|png|jpg|jpeg)"
IMAGE_PATH_RE = re.compile(rf"[^\s\)\]\\\"']+\.(?:{IMG_EXT_RE})", re.IGNORECASE)
REF_DEF_RE = re.compile(r"(?im)^\[([^\]]+)\]:\s*(\S+)")
REF_USE_RE = re.compile(r"!\[[^\]]*\]\[([^\]]+)\]")
HTML_IMG_RE = re.compile(rf"(?i)<img[^>]+src=[\\\"']([^\\\"']+\.(?:{IMG_EXT_RE}))")
THUMB_EXCLUDE_RE = re.compile(r"(?i)(/browse/thumbs/|\bthumbs/|thumbnail|social_image|/icons/)")
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
    for ext in ('.yml', '.yaml'):
        if p.lower().endswith(ext):
            p = p[:-len(ext)]
            break
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


def parse_md_front_matter(md_text: str):
    if not md_text.startswith('---'):
        return {}
    end = md_text.find('\n---', 3)
    if end == -1:
        return {}
    fm_text = md_text[3:end]
    if yaml is None:
        return {}
    try:
        data = yaml.safe_load(fm_text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def extract_reference_map(md_text: str):
    m = {}
    for key, target in REF_DEF_RE.findall(md_text):
        m[key.strip().lower()] = clean_ref(target)
    return m


def is_likely_architecture_image(img_path: str, context_line: str, ref_key: str | None = None) -> bool:
    p = (img_path or '').lower()
    line = (context_line or '').lower()
    key = (ref_key or '').lower()

    if THUMB_EXCLUDE_RE.search(p) or THUMB_EXCLUDE_RE.search(line):
        return False
    if ':::image' in line:
        return True
    if key in ('architecture', 'arch', 'architecturediagram', 'architecture-diagram', 'diagram'):
        return True
    if ARCH_HINT_RE.search(line):
        return True
    fname = p.split('/')[-1]
    if ARCH_HINT_RE.search(fname):
        return True
    if '/_images/' in p or '/images/' in p or '/media/' in p:
        if ARCH_HINT_RE.search(fname):
            return True
    return False


def find_architecture_images(md_text: str):
    lines = md_text.splitlines()
    ref_map = extract_reference_map(md_text)
    found = []

    for line in lines:
        for raw in IMAGE_PATH_RE.findall(line):
            raw2 = clean_ref(raw)
            if is_likely_architecture_image(raw2, line):
                found.append((raw2, None, line))

    for line in lines:
        for raw in HTML_IMG_RE.findall(line):
            raw2 = clean_ref(raw)
            if is_likely_architecture_image(raw2, line):
                found.append((raw2, None, line))

    for line in lines:
        for ref_key in REF_USE_RE.findall(line):
            key_l = ref_key.strip().lower()
            target = ref_map.get(key_l)
            if not target:
                continue
            if not re.search(rf"\.(?:{IMG_EXT_RE})$", target, re.IGNORECASE):
                continue
            if is_likely_architecture_image(target, line, ref_key=key_l):
                found.append((target, key_l, line))

    seen = set()
    out = []
    for raw, key, line in found:
        k = raw.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append((raw, key, line))
    return out


def categorize_links(md_text: str):
    azure_experience_links = sorted(set(AZURE_E_RE.findall(md_text)))
    calc_any = sorted(set(CALC_ANY_RE.findall(md_text)))
    calc_shared = sorted({u for u in calc_any if re.search(r"shared-estimate=", u, re.IGNORECASE)})

    calc_root = []
    calc_other = []
    for u in calc_any:
        u_clean = u.rstrip(').,;')
        if CALC_ROOT_RE.match(u_clean) and ('?' not in u_clean) and ('#' not in u_clean):
            calc_root.append(u_clean)
        elif u not in calc_shared:
            calc_other.append(u)

    calc_root = sorted(set(calc_root))
    calc_other = sorted(set(calc_other))

    shared_estimate_links = sorted(set(azure_experience_links + calc_shared))
    has_any = bool(calc_root or shared_estimate_links or calc_other)
    all_matching_links = sorted(set(azure_experience_links + calc_any))

    return {
        'azure_experience_links': azure_experience_links,
        'calculator_root_links': calc_root,
        'calculator_shared_estimate_links': calc_shared,
        'calculator_other_links': calc_other,
        'shared_estimate_links': shared_estimate_links,
        'pricing_calculator_links': calc_any,
        'all_matching_links': all_matching_links,
        'has_any_qualifying_links': has_any,
    }


def extract_yaml_meta(data: dict):
    meta = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}
    title = meta.get('title') or data.get('title')
    description = meta.get('description') or data.get('description')
    azure_categories = as_list(data.get('azureCategories'))
    author = meta.get('author') or data.get('author')
    ms_author = meta.get('ms.author') or data.get('ms.author')
    return title, description, azure_categories, author, ms_author


def scan(repo_root: Path, repo_slug: str, branch: str, docs_root: str, debug: bool):
    docs_path = repo_root / docs_root

    yml_files = list(docs_path.rglob('*.yml')) + list(docs_path.rglob('*.yaml'))
    # Deduplicate in case of overlap
    yml_files = sorted({p.resolve(): p for p in yml_files}.values(), key=lambda p: str(p))

    counts = {
        'yml_total': len(yml_files),
        'yml_parsed': 0,
        'has_content': 0,
        'has_include': 0,
        'include_md_exists': 0,
        'md_has_links_any': 0,
        'md_has_arch_images_any': 0,
        'matched': 0,
        'failed': 0,
    }

    failures = []
    results = []

    for yml_path in yml_files:
        repo_rel_yml = yml_path.relative_to(repo_root).as_posix()

        base = {
            'criteria_passed': False,
            'failure_reason': '',
            'title': None,
            'description': None,
            'azureCategories': [],
            'yml_url': make_learn_url_from_docs_path(repo_rel_yml),
            'yml_github_url': make_github_blob_url(repo_slug, branch, repo_rel_yml),
            'yml_path': repo_rel_yml,
            'include_md_path': None,
            'include_md_github_url': None,
            'md_author_github': None,
            'md_ms_author': None,
            'architecture_image_heuristic': False,
            'image_paths': [],
            'image_download_urls': [],
            'image_exists_in_repo': [],
            'image_formats': [],
            'svg_paths': [],
            'svg_download_urls': [],
            'svg_exists_in_repo': [],
            'azure_experience_links': [],
            'calculator_root_links': [],
            'calculator_shared_estimate_links': [],
            'calculator_other_links': [],
            'pricing_calculator_links': [],
            'shared_estimate_links': [],
            'all_matching_links': [],
        }

        data = load_yaml(yml_path)
        if not isinstance(data, dict):
            base['failure_reason'] = 'yaml_parse_failed'
            results.append(base)
            counts['failed'] += 1
            if debug:
                failures.append({'yml_path': repo_rel_yml, 'reason': base['failure_reason']})
            continue

        counts['yml_parsed'] += 1
        title, description, azure_categories, y_author, y_ms_author = extract_yaml_meta(data)
        base['title'] = title
        base['description'] = description
        base['azureCategories'] = azure_categories

        content = data.get('content')
        if not isinstance(content, str):
            base['failure_reason'] = 'missing_content_string'
            results.append(base)
            counts['failed'] += 1
            if debug:
                failures.append({'yml_path': repo_rel_yml, 'reason': base['failure_reason']})
            continue

        counts['has_content'] += 1
        inc = INCLUDE_RE.search(content)
        if not inc:
            base['failure_reason'] = 'no_include_directive'
            results.append(base)
            counts['failed'] += 1
            if debug:
                failures.append({'yml_path': repo_rel_yml, 'reason': base['failure_reason']})
            continue

        counts['has_include'] += 1
        include_md_ref = inc.group(1)
        include_md_rel = resolve_repo_rel(yml_path.parent, include_md_ref, repo_root)
        if not include_md_rel:
            base['failure_reason'] = 'include_md_unresolvable'
            base['include_md_path'] = include_md_ref
            results.append(base)
            counts['failed'] += 1
            if debug:
                failures.append({'yml_path': repo_rel_yml, 'reason': base['failure_reason'], 'include_md_ref': include_md_ref})
            continue

        md_file = repo_root / include_md_rel
        base['include_md_path'] = include_md_rel
        base['include_md_github_url'] = make_github_blob_url(repo_slug, branch, include_md_rel)

        if not md_file.exists():
            base['failure_reason'] = 'include_md_missing'
            results.append(base)
            counts['failed'] += 1
            if debug:
                failures.append({'yml_path': repo_rel_yml, 'reason': base['failure_reason'], 'include_md_path': include_md_rel})
            continue

        counts['include_md_exists'] += 1
        md_text = md_file.read_text(encoding='utf-8', errors='ignore')

        fm = parse_md_front_matter(md_text)
        md_author = (fm.get('author') if isinstance(fm, dict) else None) or y_author
        md_ms_author = (fm.get('ms.author') if isinstance(fm, dict) else None) or y_ms_author
        base['md_author_github'] = md_author
        base['md_ms_author'] = md_ms_author

        link_info = categorize_links(md_text)
        for k in (
            'azure_experience_links',
            'calculator_root_links',
            'calculator_shared_estimate_links',
            'calculator_other_links',
            'pricing_calculator_links',
            'shared_estimate_links',
            'all_matching_links',
        ):
            base[k] = link_info.get(k, [])

        has_links_any = bool(link_info.get('has_any_qualifying_links'))
        if has_links_any:
            counts['md_has_links_any'] += 1

        arch_imgs = find_architecture_images(md_text)
        has_arch_imgs_any = bool(arch_imgs)
        if has_arch_imgs_any:
            counts['md_has_arch_images_any'] += 1

        if not has_links_any:
            base['failure_reason'] = 'no_matching_links'
            results.append(base)
            counts['failed'] += 1
            if debug:
                failures.append({'yml_path': repo_rel_yml, 'reason': base['failure_reason'], 'include_md_path': include_md_rel})
            continue

        if not has_arch_imgs_any:
            base['failure_reason'] = 'no_architecture_images'
            results.append(base)
            counts['failed'] += 1
            if debug:
                failures.append({'yml_path': repo_rel_yml, 'reason': base['failure_reason'], 'include_md_path': include_md_rel})
            continue

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

        base['criteria_passed'] = True
        base['failure_reason'] = ''
        base['architecture_image_heuristic'] = True
        base['image_paths'] = image_paths
        base['image_download_urls'] = image_download_urls
        base['image_exists_in_repo'] = image_exists
        base['image_formats'] = image_formats
        base['svg_paths'] = svg_paths
        base['svg_download_urls'] = svg_download_urls
        base['svg_exists_in_repo'] = svg_exists

        results.append(base)
        counts['matched'] += 1

    return results, counts, failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', default=None, help='Repo slug (default: GITHUB_REPOSITORY)')
    ap.add_argument('--branch', default='main')
    ap.add_argument('--docs-root', default='docs')
    ap.add_argument('--output', default='scan-results.json')
    ap.add_argument('--debug', action='store_true', help='Write scan-debug.json with counts + sample failures')
    args = ap.parse_args()

    repo_slug = args.repo or os.getenv('GITHUB_REPOSITORY') or 'MicrosoftDocs/architecture-center'
    repo_root = Path.cwd()

    items, counts, failures = scan(repo_root, repo_slug, args.branch, args.docs_root, args.debug)

    out = {
        'repo': repo_slug,
        'branch': args.branch,
        'docs_root': args.docs_root,
        'count': len(items),
        'items': items,
    }

    Path(args.output).write_text(json.dumps(out, indent=2), encoding='utf-8')
    print(f"Scanning docs_root={args.docs_root}: found {counts['yml_total']} YAML files; wrote {len(items)} items; matched={counts['matched']}; failed={counts['failed']}")

    if args.debug:
        dbg = {
            'counts': counts,
            'failures_total': len(failures),
            'failures_sample': failures[:1000],
        }
        Path('scan-debug.json').write_text(json.dumps(dbg, indent=2), encoding='utf-8')
        print(f"Wrote debug to scan-debug.json (failures_total={len(failures)})")


if __name__ == '__main__':
    main()
