#!/usr/bin/env python3
"""MS Architecture Center Scanner

Design:
- Primary question (criteria_passed): Does the included .md article contain a *usable estimate link*?
- Usable estimate links are:
    A) Azure Experience links: https://azure.com/e/*
    B) Pricing Calculator shared-estimate links: https://azure.microsoft.com/pricing/calculator?...shared-estimate=*
- If no usable estimate link:
    1) failure_reason = no_estimate_link_calculator_tool_link_only
       when a pricing calculator link exists but none match usable estimate patterns.
    2) failure_reason = no_estimate_link
       when neither pricing calculator links nor usable estimate links are found.
- Image detection still runs for every included .md article and populates image fields,
  but images are *not* part of pass/fail criteria.
- Adds ms_date from the YAML file (metadata.ms.date or top-level ms.date).
- Restores Author and MS Author:
    * md_author_github (MD front matter author; else YAML author)
    * md_ms_author     (MD front matter ms.author; else YAML ms.author)
- Scans both *.yml and *.yaml under docs-root (Pattern A: YML+MD with [!INCLUDE]).
- Also scans standalone *.md files under docs-root whose YAML front matter contains
  a 'title' field, and which are NOT already referenced as an [!INCLUDE] target by
  any scanned YML file (Pattern B: self-contained MD pages). These articles publish
  directly as Architecture Center pages without a companion YML wrapper.
- Evaluation pipeline (strict sequence — each gate only runs if the previous passed):
    Gate 1  scan_status   Did the file parse and resolve correctly?
                          Values: ok | yaml_parse_failed | missing_content_string |
                                  no_include_directive | include_md_unresolvable |
                                  include_md_missing
                          On error → in_scope=FALSE, out_of_scope_reason='scan_error',
                          criteria_passed=FALSE. No further gates run.
    Gate 2  in_scope      Is this a complete, valid scenario? Requires ALL of:
                            1. Non-blank title
                            2. Non-blank description
                            3. At least one azureCategory
                            4. At least one image reference in the article
                          On failure → out_of_scope_reason lists each failing criterion
                          (semicolon-separated), criteria_passed=FALSE. Gate 3 skipped.
    Gate 3  criteria_passed  Does the article contain a usable pricing estimate link?
                          Values: TRUE | FALSE
                          failure_reason explains FALSE:
                            no_estimate_link
                            no_estimate_link_calculator_tool_link_only
    All rows are kept in the output for auditability. Downstream tools restrict
    comparison and review to in_scope=TRUE rows only.

Outputs:
- scan-results.json (always)
- scan-debug.json (optional)
"""

import argparse
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import yaml  # PyYAML
except Exception:
    yaml = None

INCLUDE_RE = re.compile(r"\[!INCLUDE\s*\[\s*\]\s*\(\s*([^\)\s]+\.md)\s*\)\s*\]", re.IGNORECASE)

# Link detection
AZURE_E_RE = re.compile(r"https?://azure\.com/e/[^\s\)\]\\\"']+", re.IGNORECASE)
LOCALE_SEG = r"(?:[a-z]{2}-[a-z]{2}/)?"
CALC_ANY_RE = re.compile(rf"https?://azure\.microsoft\.com/{LOCALE_SEG}pricing/calculator[^\s\)\]\\\"']*", re.IGNORECASE)
CALC_ROOT_RE = re.compile(rf"https?://azure\.microsoft\.com/{LOCALE_SEG}pricing/calculator/?(?=$|[\s\)\]\\\"'])", re.IGNORECASE)
SHARED_ESTIMATE_RE = re.compile(
    rf"https?://azure\.microsoft\.com/{LOCALE_SEG}pricing/calculator/?\?[^\s\)\]\\\"']*shared-estimate=[^\s\)\]\\\"']+",
    re.IGNORECASE,
)
# Image extraction (extension-agnostic)
MD_INLINE_IMG_RE = re.compile(r"!\[[^\]]*\]\(([^\)]+)\)")
MD_REF_IMG_USE_RE = re.compile(r"!\[[^\]]*\]\[([^\]]+)\]")
MD_REF_DEF_RE = re.compile(r"(?im)^\[([^\]]+)\]:\s*(\S+)")
DOCS_IMAGE_BLOCK_RE = re.compile(r"(?im)^\s*:::image\b[^\n]*")
DOCS_IMAGE_SOURCE_RE = re.compile(r"(?i)\bsource\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s>]+))")
HTML_IMG_SRC_RE = re.compile(r"(?i)<img[^>]+\bsrc\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s>]+))")
HTML_SOURCE_SRCSET_RE = re.compile(r"(?i)<source[^>]+\bsrcset\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s>]+))")

THUMB_EXCLUDE_RE = re.compile(r"(?i)(/browse/thumbs/|\bthumbs/|thumbnail|social_image|/icons/)")


def load_yaml(path: Path) -> Optional[dict]:
    if yaml is None:
        return None
    try:
        return yaml.safe_load(path.read_text(encoding='utf-8', errors='ignore'))
    except Exception:
        return None


def as_list(val):
    if val is None:
        return []
    return val if isinstance(val, list) else [val]


def strip_query_fragment(s: str) -> str:
    return s.split('#', 1)[0].split('?', 1)[0]


def clean_ref(ref: str) -> str:
    ref = (ref or '').strip()
    if ref.startswith('<') and ref.endswith('>'):
        ref = ref[1:-1].strip()
    if ref.strip():
        ref = ref.strip().split()[0]
    return ref.strip('"').strip("'").strip().strip('()<>[]')


def resolve_repo_rel(base_dir: Path, ref: str, repo_root: Path) -> Optional[str]:
    ref = clean_ref(ref)
    if not ref:
        return None
    if re.match(r"^[a-zA-Z]+://", ref):
        return None
    ref = strip_query_fragment(ref)
    while ref.startswith('./'):
        ref = ref[2:]
    ref = ref.lstrip('/')
    p = (base_dir / ref).resolve()
    try:
        return p.relative_to(repo_root.resolve()).as_posix()
    except Exception:
        return None


def make_raw_url(repo_slug: str, branch: str, repo_rel_path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo_slug}/{branch}/{repo_rel_path.lstrip('/')}"


def make_github_blob_url(repo_slug: str, branch: str, repo_rel_path: str) -> str:
    return f"https://github.com/{repo_slug}/blob/{branch}/{repo_rel_path.lstrip('/')}"


def make_learn_url_from_docs_path(repo_rel_path: str) -> str:
    p = repo_rel_path.replace('\\', '/')
    if p.startswith('docs/'):
        p = p[len('docs/'):]
    for ext in ('.yml', '.yaml', '.md'):
        if p.lower().endswith(ext):
            p = p[:-len(ext)]
            break
    return f"https://learn.microsoft.com/en-us/azure/architecture/{p}"


def parse_md_front_matter(md_text: str) -> dict:
    if not md_text.startswith('---'):
        return {}
    end = md_text.find('\n---', 3)
    if end == -1:
        return {}
    fm_text = md_text[3:end]
    if yaml is None:
        return {}
    try:
        d = yaml.safe_load(fm_text)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def extract_reference_map(md_text: str) -> Dict[str, str]:
    return {k.strip().lower(): clean_ref(v) for k, v in MD_REF_DEF_RE.findall(md_text)}


def add_candidate(out: List[str], raw: str):
    raw = clean_ref(raw)
    if not raw:
        return
    if THUMB_EXCLUDE_RE.search(raw):
        return
    out.append(raw)


def extract_image_refs(md_text: str) -> List[str]:
    refs: List[str] = []

    for raw in MD_INLINE_IMG_RE.findall(md_text):
        add_candidate(refs, raw)

    for line in DOCS_IMAGE_BLOCK_RE.findall(md_text):
        m = DOCS_IMAGE_SOURCE_RE.search(line)
        if not m:
            continue
        add_candidate(refs, m.group(1) or m.group(2) or m.group(3) or '')

    for g1, g2, g3 in HTML_IMG_SRC_RE.findall(md_text):
        add_candidate(refs, g1 or g2 or g3 or '')

    for g1, g2, g3 in HTML_SOURCE_SRCSET_RE.findall(md_text):
        raw = (g1 or g2 or g3 or '')
        if raw:
            raw = raw.split(',')[0].strip().split()[0]
        add_candidate(refs, raw)

    ref_map = extract_reference_map(md_text)
    for key in MD_REF_IMG_USE_RE.findall(md_text):
        target = ref_map.get(key.strip().lower())
        if target:
            add_candidate(refs, target)

    seen = set()
    out: List[str] = []
    for r in refs:
        if r and r not in seen:
            seen.add(r)
            out.append(r)
    return out


def categorize_links(md_text: str) -> dict:
    azure_experience_links = sorted(set(AZURE_E_RE.findall(md_text)))
    calc_any = sorted(set(CALC_ANY_RE.findall(md_text)))

    shared_est = sorted({u for u in calc_any if SHARED_ESTIMATE_RE.search(u)})

    calc_root: List[str] = []
    calc_other: List[str] = []
    for u in calc_any:
        u_clean = u.rstrip(').,;')
        if CALC_ROOT_RE.match(u_clean) and ('?' not in u_clean) and ('#' not in u_clean):
            calc_root.append(u_clean)
        else:
            calc_other.append(u)

    calc_root = sorted(set(calc_root))
    calc_other = sorted(set(calc_other))

    shared_estimate_links = sorted(set(azure_experience_links + shared_est))
    all_matching_links = sorted(set(azure_experience_links + calc_any))

    usable_estimate_links = sorted(set(azure_experience_links + shared_est))

    return {
        'azure_experience_links': azure_experience_links,
        'calculator_root_links': calc_root,
        'calculator_shared_estimate_links': shared_est,
        'calculator_other_links': calc_other,
        'shared_estimate_links': shared_estimate_links,
        'pricing_calculator_links': calc_any,
        'all_matching_links': all_matching_links,
        'usable_estimate_links': usable_estimate_links,
    }


def extract_yaml_meta(data: dict) -> Tuple[Optional[str], Optional[str], List[str], Optional[str], Optional[str], Optional[str]]:
    meta = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}
    title = meta.get('title') or data.get('title')
    description = meta.get('description') or data.get('description')
    azure_categories = as_list(data.get('azureCategories'))
    author = meta.get('author') or data.get('author')
    ms_author = meta.get('ms.author') or data.get('ms.author')
    ms_date = meta.get('ms.date') or data.get('ms.date')
    return title, description, azure_categories, author, ms_author, ms_date


def _make_base_record(repo_slug: str, branch: str) -> dict:
    """Return an empty result record with all expected keys."""
    return {
        'scan_status': 'ok',
        'criteria_passed': False,
        'failure_reason': '',
        'title': None,
        'description': None,
        'azureCategories': [],
        'ms_date': None,
        'yml_url': None,
        'yml_github_url': None,
        'yml_path': None,
        'include_md_path': None,
        'include_md_github_url': None,
        'md_author_github': None,
        'md_ms_author': None,
        'image_paths': [],
        'image_download_urls': [],
        'image_exists_in_repo': [],
        'image_formats': [],
        'azure_experience_links': [],
        'calculator_root_links': [],
        'calculator_shared_estimate_links': [],
        'calculator_other_links': [],
        'pricing_calculator_links': [],
        'shared_estimate_links': [],
        'all_matching_links': [],
        'usable_estimate_links': [],
        # Scope gate — populated after md content is scanned
        'in_scope': False,
        'out_of_scope_reason': '',
    }



def _mark_scan_error(base: dict, error_code: str, counts: dict) -> None:
    """Mark a record as a pipeline/structural error (Gate 1 failure).

    Sets scan_status, forces in_scope=FALSE with out_of_scope_reason='scan_error',
    and ensures criteria_passed=FALSE. The failure_reason field retains the error
    code so it stays visible in the sheet alongside the new scan_status column.
    """
    base['scan_status'] = error_code
    base['failure_reason'] = error_code   # keep legacy field populated for readability
    base['in_scope'] = False
    base['out_of_scope_reason'] = 'scan_error'
    base['criteria_passed'] = False
    counts['out_of_scope'] += 1
    counts['failed'] += 1


def evaluate_scope(base: dict) -> None:
    """Gate 2 — apply in-scope filter after md content is fully populated.

    Only called on records where scan_status == 'ok' (Gate 1 passed).
    A scenario is in_scope = TRUE only when ALL four criteria are met:
      1. title           — non-blank
      2. description     — non-blank
      3. azureCategories — at least one non-blank entry
      4. image_paths     — at least one image reference found in the article

    Sets base['in_scope'] and base['out_of_scope_reason'] in-place.
    Multiple failing criteria are combined in out_of_scope_reason (semicolon-separated).
    """
    reasons = []
    if not str(base.get('title') or '').strip():
        reasons.append('blank_title')
    if not str(base.get('description') or '').strip():
        reasons.append('blank_description')
    cats = base.get('azureCategories') or []
    if not any(str(c).strip() for c in cats):
        reasons.append('blank_category')
    if not base.get('image_paths'):
        reasons.append('no_architecture_image')

    base['in_scope'] = len(reasons) == 0
    base['out_of_scope_reason'] = '; '.join(reasons)


def _scan_md_content(
    base: dict,
    md_file: Path,
    md_text: str,
    repo_root: Path,
    repo_slug: str,
    branch: str,
    counts: dict,
    failures: list,
    debug: bool,
    debug_key: str,
):
    """Gate 3 — scan md content for links + images and set criteria_passed.

    scan_status is set to 'ok' at the top; all earlier pipeline errors bypass
    this function entirely via _mark_scan_error. evaluate_scope() (Gate 2) is
    called at the end, after all content fields are populated.
    """
    base['scan_status'] = 'ok'  # Gate 1 passed — file resolved and content found
    link_info = categorize_links(md_text)
    for k, v in link_info.items():
        if k in base:
            base[k] = v

    has_any_calc = bool(link_info.get('pricing_calculator_links'))
    has_usable = bool(link_info.get('usable_estimate_links'))
    if has_any_calc:
        counts['md_has_any_calc_link'] += 1
    if has_usable:
        counts['md_has_usable_estimate_link'] += 1

    img_refs = extract_image_refs(md_text)
    image_paths: List[str] = []
    image_download_urls: List[str] = []
    image_exists: List[bool] = []
    image_formats: List[str] = []
    for raw in img_refs:
        cleaned = clean_ref(raw)
        img_rel = resolve_repo_rel(md_file.parent, cleaned, repo_root)
        if img_rel is None:
            img_rel = strip_query_fragment(cleaned).lstrip('/')
        image_paths.append(img_rel)
        image_download_urls.append(make_raw_url(repo_slug, branch, img_rel))
        exists = bool((repo_root / img_rel).exists())
        image_exists.append(exists)
        image_formats.append(Path(img_rel).suffix.lower().lstrip('.'))

    base['image_paths'] = image_paths
    base['image_download_urls'] = image_download_urls
    base['image_exists_in_repo'] = image_exists
    base['image_formats'] = image_formats

    if has_usable:
        base['criteria_passed'] = True
        base['failure_reason'] = ''
    else:
        base['criteria_passed'] = False
        base['failure_reason'] = (
            'no_estimate_link_calculator_tool_link_only' if has_any_calc else 'no_estimate_link'
        )
        if debug:
            failures.append({'path': debug_key, 'reason': base['failure_reason']})

    # Gate 2: apply scope filter after all content fields are populated
    evaluate_scope(base)
    if base['in_scope']:
        counts['in_scope'] += 1
        # Gate 3 counts: only meaningful for in-scope rows
        if base['criteria_passed']:
            counts['passed'] += 1
        else:
            counts['failed'] += 1
    else:
        counts['out_of_scope'] += 1


def scan(repo_root: Path, repo_slug: str, branch: str, docs_root: str, debug: bool):
    docs_path = repo_root / docs_root
    yml_files = list(docs_path.rglob('*.yml')) + list(docs_path.rglob('*.yaml'))
    yml_files = sorted({p.resolve(): p for p in yml_files}.values(), key=lambda p: str(p))

    counts = {
        'yml_total': len(yml_files),
        'yml_parsed': 0,
        'has_include': 0,
        'include_md_exists': 0,
        'standalone_md_total': 0,
        'standalone_md_scanned': 0,
        'md_has_any_calc_link': 0,
        'md_has_usable_estimate_link': 0,
        'in_scope': 0,
        'out_of_scope': 0,
        'passed': 0,
        'failed': 0,
    }

    failures = []
    results = []

    # --- Pass 1: YML+MD pattern (existing behaviour) ---
    # Track every .md path that is consumed as an [!INCLUDE] target so we can
    # exclude them from the standalone-MD pass below.
    included_md_paths: set = set()  # resolved absolute paths

    for yml_path in yml_files:
        repo_rel_yml = yml_path.relative_to(repo_root).as_posix()

        base = _make_base_record(repo_slug, branch)
        base['yml_url'] = make_learn_url_from_docs_path(repo_rel_yml)
        base['yml_github_url'] = make_github_blob_url(repo_slug, branch, repo_rel_yml)
        base['yml_path'] = repo_rel_yml

        data = load_yaml(yml_path)
        if not isinstance(data, dict):
            _mark_scan_error(base, 'yaml_parse_failed', counts)
            results.append(base)
            if debug:
                failures.append({'yml_path': repo_rel_yml, 'reason': base['scan_status']})
            continue

        counts['yml_parsed'] += 1
        title, description, azure_categories, y_author, y_ms_author, ms_date = extract_yaml_meta(data)
        base['title'] = title
        base['description'] = description
        base['azureCategories'] = azure_categories
        base['ms_date'] = ms_date

        content = data.get('content')
        if not isinstance(content, str):
            _mark_scan_error(base, 'missing_content_string', counts)
            results.append(base)
            if debug:
                failures.append({'yml_path': repo_rel_yml, 'reason': base['scan_status']})
            continue

        inc = INCLUDE_RE.search(content)
        if not inc:
            _mark_scan_error(base, 'no_include_directive', counts)
            results.append(base)
            if debug:
                failures.append({'yml_path': repo_rel_yml, 'reason': base['scan_status']})
            continue

        counts['has_include'] += 1

        include_md_ref = inc.group(1)
        include_md_rel = resolve_repo_rel(yml_path.parent, include_md_ref, repo_root)
        if not include_md_rel:
            base['include_md_path'] = include_md_ref
            _mark_scan_error(base, 'include_md_unresolvable', counts)
            results.append(base)
            if debug:
                failures.append({'yml_path': repo_rel_yml, 'reason': base['scan_status'], 'include_md_ref': include_md_ref})
            continue

        md_file = repo_root / include_md_rel
        base['include_md_path'] = include_md_rel
        base['include_md_github_url'] = make_github_blob_url(repo_slug, branch, include_md_rel)

        # Register this md as consumed so the standalone pass skips it
        included_md_paths.add(md_file.resolve())

        if not md_file.exists():
            _mark_scan_error(base, 'include_md_missing', counts)
            results.append(base)
            if debug:
                failures.append({'yml_path': repo_rel_yml, 'reason': base['scan_status'], 'include_md_path': include_md_rel})
            continue

        counts['include_md_exists'] += 1

        md_text = md_file.read_text(encoding='utf-8', errors='ignore')

        fm = parse_md_front_matter(md_text)
        base['md_author_github'] = (fm.get('author') if isinstance(fm, dict) else None) or y_author
        base['md_ms_author'] = (fm.get('ms.author') if isinstance(fm, dict) else None) or y_ms_author

        _scan_md_content(base, md_file, md_text, repo_root, repo_slug, branch,
                         counts, failures, debug, repo_rel_yml)
        results.append(base)

    # --- Pass 2: Standalone MD pattern ---
    # These are .md files that publish as their own Architecture Center page,
    # identified by having a YAML front matter block with a 'title' field.
    # Files already consumed as [!INCLUDE] targets are excluded.
    all_md_files = sorted(
        {p.resolve(): p for p in docs_path.rglob('*.md')}.values(),
        key=lambda p: str(p),
    )
    counts['standalone_md_total'] = sum(
        1 for p in all_md_files if p.resolve() not in included_md_paths
    )

    for md_path in all_md_files:
        if md_path.resolve() in included_md_paths:
            continue  # already handled in Pass 1

        md_text = md_path.read_text(encoding='utf-8', errors='ignore')
        fm = parse_md_front_matter(md_text)

        # Only treat as a valid scenario page if front matter has a title.
        # This filters out index pages, partial includes, and non-article md files.
        if not isinstance(fm, dict) or not fm.get('title'):
            continue

        counts['standalone_md_scanned'] += 1
        repo_rel_md = md_path.relative_to(repo_root).as_posix()

        base = _make_base_record(repo_slug, branch)
        # For standalone MDs, yml_url is derived from the .md path itself.
        # yml_path is set to the md path so downstream tools (run_compare_only)
        # can use it for matching; include_md_path mirrors it for consistency.
        base['yml_url'] = make_learn_url_from_docs_path(repo_rel_md)
        base['yml_github_url'] = make_github_blob_url(repo_slug, branch, repo_rel_md)
        base['yml_path'] = repo_rel_md          # the .md IS the page source
        base['include_md_path'] = repo_rel_md   # same file — content is here
        base['include_md_github_url'] = make_github_blob_url(repo_slug, branch, repo_rel_md)

        base['title'] = fm.get('title')
        base['description'] = fm.get('description')
        base['azureCategories'] = as_list(fm.get('ms.service') or fm.get('azureCategories'))
        base['ms_date'] = fm.get('ms.date')
        base['md_author_github'] = fm.get('author')
        base['md_ms_author'] = fm.get('ms.author')

        _scan_md_content(base, md_path, md_text, repo_root, repo_slug, branch,
                         counts, failures, debug, repo_rel_md)
        results.append(base)

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
    print(
        f"Scanning docs_root={args.docs_root}: yml_total={counts['yml_total']}; "
        f"standalone_md_scanned={counts['standalone_md_scanned']}; "
        f"wrote={len(items)}; in_scope={counts['in_scope']}; out_of_scope={counts['out_of_scope']}; "
        f"passed={counts['passed']}; failed={counts['failed']}; "
        f"md_has_any_calc_link={counts['md_has_any_calc_link']}; md_has_usable_estimate_link={counts['md_has_usable_estimate_link']}"
    )

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
