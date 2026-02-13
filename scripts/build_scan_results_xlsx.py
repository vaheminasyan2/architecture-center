#!/usr/bin/env python3
import argparse, json
from pathlib import Path
import pandas as pd

import re

AZURE_E_RE = re.compile(r"^https?://azure\.com/e/\S+$", re.IGNORECASE)
SHARED_RE  = re.compile(
    r"^https?://azure\.microsoft\.com/(?:[a-z]{2}-[a-z]{2}/)?pricing/calculator/?\?\S*shared-estimate=\S+$",
    re.IGNORECASE
)
SERVICE_RE = re.compile(
    r"^https?://azure\.microsoft\.com/(?:[a-z]{2}-[a-z]{2}/)?pricing/calculator/?\?\S*service=\S+$",
    re.IGNORECASE
)

def pick_estimate_link(item: dict) -> str:
    """
    Allowed only:
      1) https://azure.com/e/*
      2) pricing calculator shared-estimate=*
      3) pricing calculator service=*
    Anything else => blank.
    """

    # Collect candidate link lists from scanner output (best recall)
    candidates = []
    for key in (
        "azure_experience_links",
        "shared_estimate_links",
        "pricing_calculator_links",
        "all_matching_links",
        "calculator_other_links",
        "calculator_shared_estimate_links",
    ):
        vals = item.get(key) or []
        if isinstance(vals, list):
            candidates.extend([str(v).strip() for v in vals if v])
        elif vals:
            candidates.append(str(vals).strip())

    # Prefer in order: Azure experience, shared-estimate, service
    for u in candidates:
        if AZURE_E_RE.match(u):
            return u
    for u in candidates:
        if SHARED_RE.match(u):
            return u
    for u in candidates:
        if SERVICE_RE.match(u):
            return u

    return ""
``
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="scan-results.json")
    ap.add_argument("--output", default="scan-results.xlsx")
    args = ap.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    items = data.get("items", [])

    rows = []
    for it in items:
        rows.append({
            "title": it.get("title") or "",
            "description": it.get("description") or "",
            "azureCategories": "; ".join(it.get("azureCategories") or []) if isinstance(it.get("azureCategories"), list) else (it.get("azureCategories") or ""),
            "yml_url": it.get("yml_url") or "",
            "image_download_urls": join_list(it.get("image_download_urls") or []),
            "estimate_link": pick_estimate_link(it),

            # Optional passthrough fields (if you want them later)
            "yml_path": it.get("yml_path") or "",
            "include_md_path": it.get("include_md_path") or "",
            "md_author_name": it.get("md_author_github") or "",
            "md_ms_author_name": it.get("md_ms_author") or "",
        })

    df = pd.DataFrame(rows)

    # IMPORTANT: write ONLY one sheet first, named scan-results
    with pd.ExcelWriter(args.output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="scan-results", index=False)

    print(f"Wrote {len(df)} rows to {args.output} (sheet: scan-results)")

if __name__ == "__main__":
    main()
