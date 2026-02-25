import pandas as pd
from pathlib import Path
from datetime import datetime
import os
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

SCAN_RESULTS_PATH = Path('scan-results.xlsx')
ESTIMATE_SCENARIOS_PATH = Path('estimate_scenarios.xlsx')

ESTIMATE_LINK_COL = 'estimate_link'
YML_URL_COL = 'yml_url'
CRITERIA_COL = 'criteria_passed'
STATUS_COL = 'comparison_status'

# Status values
STATUS_SAME = 'matched_existing_scenario_same_estimate'
STATUS_NEW_ESTIMATE = 'matched_existing_scenario_new_estimate'
STATUS_NEW_CANDIDATE = 'new_estimate_candidate'
STATUS_NOT_APPLICABLE = 'not_applicable'

# --- URL normalization helpers ---

def _normalize_learn_url(url: str) -> str:
    """Normalize Learn URLs for stable scenario matching."""
    if url is None:
        return ''
    u = str(url).strip()
    if not u:
        return ''
    parts = urlsplit(u)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip('/')
    return urlunsplit((scheme, netloc, path, '', ''))


def _normalize_estimate_url(url: str) -> str:
    """Normalize estimate URLs so formatting differences don't create false mismatches.

    Keeps only query params that define the estimate identity:
      - shared-estimate
      - service
    """
    if url is None:
        return ''
    u = str(url).strip()
    if not u:
        return ''

    parts = urlsplit(u)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip('/')

    keep_keys = {'shared-estimate', 'service'}
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False) if k.lower() in keep_keys]
    q_sorted = sorted((k.lower(), (v or '').strip()) for k, v in q)
    query = urlencode(q_sorted, doseq=True)

    return urlunsplit((scheme, netloc, path, query, ''))


def _split_estimate_links(cell_value) -> list:
    """Scan results may contain multiple estimate links per scenario.
    Support newline-delimited and semicolon-delimited values.
    """
    if cell_value is None:
        return []
    s = str(cell_value).strip()
    if not s:
        return []

    parts = []
    for chunk in s.replace(';', '\n').splitlines():
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)

    seen = set()
    out = []
    for p in parts:
        n = _normalize_estimate_url(p)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


# --- Load data ---
scan_df = pd.read_excel(SCAN_RESULTS_PATH)
est_df = pd.read_excel(ESTIMATE_SCENARIOS_PATH)

required_scan = {YML_URL_COL, ESTIMATE_LINK_COL, CRITERIA_COL}
missing_scan = required_scan - set(scan_df.columns)
if missing_scan:
    raise ValueError(
        f"scan-results.xlsx missing required columns: {sorted(missing_scan)}. "
        f"Found columns: {list(scan_df.columns)}"
    )

required_inv = {YML_URL_COL, ESTIMATE_LINK_COL}
missing_inv = required_inv - set(est_df.columns)
if missing_inv:
    raise ValueError(
        f"estimate_scenarios.xlsx missing required columns: {sorted(missing_inv)}. "
        f"Found columns: {list(est_df.columns)}"
    )

# Ensure comparison_status exists
if STATUS_COL not in scan_df.columns:
    scan_df[STATUS_COL] = STATUS_NOT_APPLICABLE

# Normalize criteria_passed (supports bool or string)
criteria_true = (
    scan_df[CRITERIA_COL].astype(str).str.strip().str.lower().isin(['true', '1', 'yes'])
    | (scan_df[CRITERIA_COL] == True)
)

# Normalize scenario keys (Learn URL)
scan_df['_scenario_key'] = scan_df[YML_URL_COL].astype(str).map(_normalize_learn_url)
est_df['_scenario_key'] = est_df[YML_URL_COL].astype(str).map(_normalize_learn_url)

# Build inventory map: one estimate link per scenario
inv_map = {}
for _, row in est_df.iterrows():
    key = row.get('_scenario_key', '')
    if not key:
        continue
    inv_link = _normalize_estimate_url(row.get(ESTIMATE_LINK_COL, ''))
    if not inv_link:
        continue
    inv_map[key] = inv_link

matched_in_inventory = scan_df['_scenario_key'].isin(inv_map.keys())

# Default statuses to preserve previous behavior
scan_df.loc[~criteria_true, STATUS_COL] = STATUS_NOT_APPLICABLE
scan_df.loc[criteria_true & ~matched_in_inventory, STATUS_COL] = STATUS_NEW_CANDIDATE

# Split matched existing scenario into SAME vs NEW estimate link
applicable = criteria_true & matched_in_inventory

for idx, row in scan_df.loc[applicable].iterrows():
    inv_link = inv_map.get(row['_scenario_key'], '')
    scanned_links = _split_estimate_links(row.get(ESTIMATE_LINK_COL, ''))
    if inv_link and any(l == inv_link for l in scanned_links):
        scan_df.at[idx, STATUS_COL] = STATUS_SAME
    else:
        scan_df.at[idx, STATUS_COL] = STATUS_NEW_ESTIMATE

# New tab request: include rows with these statuses
needs_review = scan_df[scan_df[STATUS_COL].isin([STATUS_NEW_ESTIMATE, STATUS_NEW_CANDIDATE])].copy()

# Summary
summary = pd.DataFrame({
    'Metric': [
        'Total scanned scenarios',
        'Scenarios criteria_passed = TRUE',
        'Scenarios not in inventory (new_estimate_candidate)',
        'matched_existing_scenario_same_estimate',
        'matched_existing_scenario_new_estimate',
        'Rows in needs-review tab',
        'Scan date (UTC)',
        'Repo commit'
    ],
    'Value': [
        int(len(scan_df)),
        int(criteria_true.sum()),
        int((scan_df[STATUS_COL] == STATUS_NEW_CANDIDATE).sum()),
        int((scan_df[STATUS_COL] == STATUS_SAME).sum()),
        int((scan_df[STATUS_COL] == STATUS_NEW_ESTIMATE).sum()),
        int(len(needs_review)),
        datetime.utcnow().isoformat(),
        os.getenv('GITHUB_SHA', 'local')
    ]
})

with pd.ExcelWriter(SCAN_RESULTS_PATH, engine='openpyxl', mode='w') as writer:
    scan_df.drop(columns=['_scenario_key']).to_excel(writer, sheet_name='scan-results', index=False)
    needs_review.to_excel(writer, sheet_name='needs-review', index=False)
    summary.to_excel(writer, sheet_name='summary', index=False)
