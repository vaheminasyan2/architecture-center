#!/usr/bin/env python3
"""Convert scan-debug.json to CSVs for Excel."""

import json
from pathlib import Path
import pandas as pd

data = json.loads(Path('scan-debug.json').read_text(encoding='utf-8'))

pd.DataFrame([data.get('counts', {})]).to_csv('scan-debug_counts.csv', index=False)
pd.json_normalize(data.get('skipped_sample', [])).to_csv('scan-debug_skipped_sample.csv', index=False)
print('Wrote debug CSVs')
