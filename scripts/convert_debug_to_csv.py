#!/usr/bin/env python3
"""Convert scan-debug.json to CSVs for Excel.

Inputs:
- scan-debug.json (from the scanner workflow)

Outputs:
- scan-debug_counts.csv (one row of counters)
- scan-debug_skipped_sample.csv (rows from skipped_sample)

Usage:
  python scripts/convert_debug_to_csv.py --input scan-debug.json --outdir .
"""

import argparse
import json
from pathlib import Path
import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', default='scan-debug.json')
    ap.add_argument('--outdir', default='.')
    args = ap.parse_args()

    inp = Path(args.input)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    data = json.loads(inp.read_text(encoding='utf-8'))

    # counts -> one-row CSV
    counts = data.get('counts', {})
    counts_df = pd.DataFrame([counts])
    counts_csv = outdir / 'scan-debug_counts.csv'
    counts_df.to_csv(counts_csv, index=False)

    # skipped_sample -> table
    skipped = data.get('skipped_sample', [])
    skipped_df = pd.json_normalize(skipped)
    skipped_csv = outdir / 'scan-debug_skipped_sample.csv'
    skipped_df.to_csv(skipped_csv, index=False)

    print(f"Wrote: {counts_csv}, {skipped_csv}")


if __name__ == '__main__':
    main()
