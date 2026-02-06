#!/usr/bin/env python3
"""Convert scan-results.json into Excel + CSVs."""

import argparse, json
from pathlib import Path
import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', default='scan-results.json')
    ap.add_argument('--outdir', default='.')
    args = ap.parse_args()

    inp = Path(args.input)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    data = json.loads(inp.read_text(encoding='utf-8'))
    items = data.get('items', [])

    df = pd.json_normalize(items)

    list_cols = [c for c in df.columns if df[c].apply(lambda x: isinstance(x, list)).any()]
    for c in list_cols:
        df[c] = df[c].apply(lambda x: " | ".join(map(str, x)) if isinstance(x, list) else x)

    df.to_csv(outdir/'scan-results_flat.csv', index=False)

    link_rows = []
    for it in items:
        base = {'title': it.get('title'), 'yml_url': it.get('yml_url'), 'yml_path': it.get('yml_path'),
                'md_author_github': it.get('md_author_github'), 'md_ms_author': it.get('md_ms_author')}
        for link in (it.get('calculator_root_links') or []):
            link_rows.append({**base, 'link_category': 'calculator_root', 'link': link})
        for link in (it.get('calculator_shared_estimate_links') or []):
            link_rows.append({**base, 'link_category': 'calculator_shared_estimate', 'link': link})
        for link in (it.get('azure_experience_links') or []):
            link_rows.append({**base, 'link_category': 'azure_experience_shared_estimate', 'link': link})
        for link in (it.get('calculator_other_links') or []):
            link_rows.append({**base, 'link_category': 'calculator_other', 'link': link})

    links_df = pd.DataFrame(link_rows)
    links_df.to_csv(outdir/'scan-results_links.csv', index=False)

    img_rows = []
    for it in items:
        base = {'title': it.get('title'), 'yml_url': it.get('yml_url'), 'yml_path': it.get('yml_path'),
                'md_author_github': it.get('md_author_github'), 'md_ms_author': it.get('md_ms_author')}
        paths = it.get('image_paths') or []
        urls = it.get('image_download_urls') or []
        fmts = it.get('image_formats') or []
        exists = it.get('image_exists_in_repo') or []
        for i, p in enumerate(paths):
            img_rows.append({
                **base,
                'image_path': p,
                'image_download_url': urls[i] if i < len(urls) else None,
                'image_format': fmts[i] if i < len(fmts) else None,
                'image_exists_in_repo': exists[i] if i < len(exists) else None,
            })

    images_df = pd.DataFrame(img_rows)
    images_df.to_csv(outdir/'scan-results_images.csv', index=False)

    with pd.ExcelWriter(outdir/'scan-results.xlsx', engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='items_flat', index=False)
        links_df.to_excel(writer, sheet_name='links', index=False)
        images_df.to_excel(writer, sheet_name='images', index=False)


if __name__ == '__main__':
    main()
