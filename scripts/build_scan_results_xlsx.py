#!/usr/bin/env python3
import argparse, json
from pathlib import Path
import pandas as pd
import re

# Allowed link categories for estimate_link
# A) Azure experience links: https://azure.com/e/*
AZURE_EXPERIENCE_RE = re.compile(r'^https?://azure\.com/e/[^\s]+$', re.IGNORECASE)
# B) Shared estimates: https://azure.microsoft.com/pricing/calculator/?...shared-estimate=*
SHARED_ESTIMATE_RE = re.compile(
    r'^https?://azure\.microsoft\.com/(?:[a-z]{2}-[a-z]{2}/)?pricing/calculator/?\?[^\s]*shared-estimate=[^\s]+$',
    re.IGNORECASE,
)
# C) Service links: https://azure.microsoft.com/pricing/calculator/?...service=* (includes calculator?service=*, calculator/?service=*, etc.)
SERVICE_RE = re.compile(
    r'^https?://azure\.microsoft\.com/(?:[a-z]{2}-[a-z]{2}/)?pricing/calculator/?\?[^\s]*service=[^\s]+$',
    re.IGNORECASE,
)


def pick_estimate_link(item: dict) -> str:
    """Return a single estimate_link that matches ONLY the allowed 3 categories.

    Priority:
      1) Azure experience (azure.com/e/*)
      2) Shared-estimate links
      3) Service links

    Anything else (including pricing calculator root) returns blank.
    """
    candidates = []
    for key in (
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

    # normalize / dedupe while preserving order
    seen = set()
    ordered = []
    for u in candidates:
        if not u or u in seen:
            continue
        seen.add(u)
        ordered.append(u)

    for u in ordered:
        if AZURE_EXPERIENCE_RE.match(u):
            return u
    for u in ordered:
        if SHARED_ESTIMATE_RE.match(u):
            return u
    for u in ordered:
        if SERVICE_RE.match(u):
            return u
    return ''


def join_list(v):
    if isinstance(v, list):
        return "
".join([str(x) for x in v if x is not None])
    return "" if v is None else str(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="scan-results.json")
    ap.add_argument("--output", default="scan-results.xlsx")
    args = ap.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    items = data.get("items", [])

    rows = []
    for it in items:
        # If you want Total scanned scenarios to reflect ALL yml files, the scanner should emit all of them.
        rows.append({
            "title": it.get("title") or "",
            "description": it.get("description") or "",
            "azureCategories": "; ".join(it.get("azureCategories") or []) if isinstance(it.get("azureCategories"), list) else (it.get("azureCategories") or ""),
            "yml_url": it.get("yml_url") or "",
            "image_download_urls": join_list(it.get("image_download_urls") or []),
            # enforce ONLY allowed link shapes; everything else becomes blank
            "estimate_link": pick_estimate_link(it),

            # Helpful passthrough + diagnostics
            "criteria_passed": bool(it.get("criteria_passed", False)),
            "failure_reason": it.get("failure_reason") or "",

            "yml_path": it.get("yml_path") or "",
            "include_md_path": it.get("include_md_path") or "",
            "md_author_name": it.get("md_author_github") or it.get("md_author_name") or "",
            "md_ms_author_name": it.get("md_ms_author") or it.get("md_ms_author_name") or "",
        })

    df = pd.DataFrame(rows)

    # IMPORTANT: write ONLY one sheet first, named "scan-results" (run_compare_only.py reads the first sheet)
    with pd.ExcelWriter(args.output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="scan-results", index=False)

    print(f"Wrote {len(df)} rows to {args.output} (sheet: scan-results)")


if __name__ == "__main__":
    main()
