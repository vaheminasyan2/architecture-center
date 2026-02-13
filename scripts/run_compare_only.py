
import pandas as pd
from pathlib import Path
from datetime import datetime
import os

SCAN_RESULTS_PATH = Path('scan-results.xlsx')
ESTIMATE_SCENARIOS_PATH = Path('estimate_scenarios.xlsx')

ESTIMATE_LINK_COL = 'estimate_link'
YML_URL_COL = 'yml_url'
STATUS_COL = 'comparison_status'

scan_df = pd.read_excel(SCAN_RESULTS_PATH)
est_df = pd.read_excel(ESTIMATE_SCENARIOS_PATH)

required = {ESTIMATE_LINK_COL, YML_URL_COL}
missing = required - set(scan_df.columns)
if missing:
    raise ValueError(f"scan-results.xlsx missing required columns: {sorted(missing)}. "
                     f"Found columns: {list(scan_df.columns)}")

scan_df['_norm'] = scan_df[YML_URL_COL].astype(str).str.strip().str.lower()
est_df['_norm'] = est_df[YML_URL_COL].astype(str).str.strip().str.lower()

known = set(est_df['_norm'].dropna())

scan_df[STATUS_COL] = 'not_applicable'
mask = scan_df[ESTIMATE_LINK_COL].notna() & (scan_df[ESTIMATE_LINK_COL].astype(str).str.strip() != '')

scan_df.loc[mask & scan_df['_norm'].isin(known), STATUS_COL] = 'matched_existing_estimate'
scan_df.loc[mask & ~scan_df['_norm'].isin(known), STATUS_COL] = 'new_estimate_candidate'

new_estimates = scan_df[scan_df[STATUS_COL] == 'new_estimate_candidate'].drop(columns=['_norm'])

summary = pd.DataFrame({
    'Metric': [
        'Total scanned scenarios',
        'Scenarios with estimate links',
        'Matched existing estimates',
        'New estimate candidates',
        'Scan date (UTC)',
        'Repo commit'
    ],
    'Value': [
        len(scan_df),
        int(mask.sum()),
        int((scan_df[STATUS_COL] == 'matched_existing_estimate').sum()),
        int((scan_df[STATUS_COL] == 'new_estimate_candidate').sum()),
        datetime.utcnow().isoformat(),
        os.getenv('GITHUB_SHA', 'local')
    ]
})

with pd.ExcelWriter(SCAN_RESULTS_PATH, engine='openpyxl', mode='w') as writer:
    scan_df.drop(columns=['_norm']).to_excel(writer, sheet_name='scan-results', index=False)
    new_estimates.to_excel(writer, sheet_name='new estimates', index=False)
    summary.to_excel(writer, sheet_name='summary', index=False)
