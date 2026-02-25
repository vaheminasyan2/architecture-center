#!/usr/bin/env python3
"""Build scan-results.xlsx from scan-results.json.
- Adds ms.date column (from scanner's ms_date field)
- Keeps image_download_urls column
- Enforces estimate_link to ONLY be one of:
  A) https://azure.com/e/*
  B) pricing/calculator?...shared-estimate=*
  C) pricing/calculator?...service=*
- Adds author columns:
  - md_author_name
  - md_ms_author_name

Update (2026-02): If multiple compliant estimate links are found for a scenario,
write ALL of them to the `estimate_link` cell (newline-separated). This prevents
losing valid tiered estimates (for example Small/Medium/Large).
"""

import argparse
import json
from pathlib import Path
import pandas as pd
import re

AZURE_EXPERIENCE_RE = re.compile(r'^https?://azure\.com/e/[^\s]+$', re.IGNORECASE)
SHARED_ESTIMATE_RE = re.compile(
    r'^https?://azure\.microsoft\.com/(?:[a-z]{2}-[a-z]{2}/)?pricing/calculator/?\?[^\s]*shared-estimate=[^\s]+$',
    re.IGNORECASE,
)
SERVICE_RE = re.compile(
    r'^https?://azure\.microsoft\.com/(?:[a-z]{2}-[a-z]{2}/)?pricing/calculator/?\?[^\s]*service=[^\s]+$',
    re.IGNORECASE,
)


def collect_estimate_links(item: dict) -> list:
    """Return ALL compliant estimate links (A/B/C), unique and deterministic order."""
    candidates = []
    for key in (
        'usable_estimate_links',
        'azure_experience_links',
        'shared_estimate_links',
        'pricing_calculator_links',
        'all_matching_links',
        'calculator_other_links',
        'calculator_shared_estimate_links',
        'calculator_root_links',
    ):
        vals = item.get(key) or []
        if isinstance(vals, list):
            candidates.extend([str(v).strip() for v in vals if v is not None])
        elif vals:
            candidates.append(str(vals).strip())

    # de-dupe while preserving order
    seen = set()
    ordered = []
    for u in candidates:
        if not u or u in seen:
            continue
        seen.add(u)
        ordered.append(u)

    out = []
    out_seen = set()

    def _add(regex):
        for u in ordered:
            if u in out_seen:
                continue
            if regex.match(u):
                out_seen.add(u)
                out.append(u)

    # stable ordering by type
    _add(AZURE_EXPERIENCE_RE)
    _add(SHARED_ESTIMATE_RE)
    _add(SERVICE_RE)

    return out


def join_list(v):
    if isinstance(v, list):
        return "\n".join([str(x) for x in v if x is not None])
    return '' if v is None else str(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', default='scan-results.json')
    ap.add_argument('--output', default='scan-results.xlsx')
    args = ap.parse_args()

    data = json.loads(Path(args.input).read_text(encoding='utf-8'))
    items = data.get('items', [])

    rows = []
    for it in items:
        links = collect_estimate_links(it)
        rows.append({
            'title': it.get('title') or '',
            'description': it.get('description') or '',
            'azureCategories': '; '.join(it.get('azureCategories') or [])
            if isinstance(it.get('azureCategories'), list)
            else (it.get('azureCategories') or ''),
            'ms.date': it.get('ms_date') or '',
            'yml_url': it.get('yml_url') or '',
            'image_download_urls': join_list(it.get('image_download_urls') or []),
            # NEW: include all compliant estimate links (newline-separated)
            'estimate_link': "\n".join(links),
            'criteria_passed': bool(it.get('criteria_passed', False)),
            'failure_reason': it.get('failure_reason') or '',
            'yml_path': it.get('yml_path') or '',
            'include_md_path': it.get('include_md_path') or '',
            # ✅ NEW COLUMNS (additive only)
            'md_author_name': it.get('md_author_github') or '',
            'md_ms_author_name': it.get('md_ms_author') or '',
        })

    df = pd.DataFrame(rows)
    with pd.ExcelWriter(args.output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='scan-results', index=False)

    print(f"Wrote {len(df)} rows to {args.output} (sheet: scan-results)")


if __name__ == '__main__':
    main()
