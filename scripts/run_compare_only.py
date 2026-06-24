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
IN_SCOPE_COL = 'in_scope'
SCAN_STATUS_COL = 'scan_status'

# Status values
STATUS_SAME = 'matched_existing_scenario_same_estimate'
STATUS_NEW_ESTIMATE = 'matched_existing_scenario_new_estimate'
STATUS_NEW_CANDIDATE = 'new_estimate_candidate'
STATUS_NOT_APPLICABLE = 'not_applicable'
STATUS_LINK_REMOVED = 'estimate_link_removed'

# --- URL normalization helpers ---

def _normalize_learn_url(url: str) -> str:
    """Normalize Learn URLs for stable scenario matching.

    Strips trailing slashes and /index segments — files named index.yml/index.md
    publish without the /index suffix on learn.microsoft.com, so both forms are
    equivalent and should not be treated as different scenarios.
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
    if path.lower().endswith('/index'):
        path = path[:-len('/index')]
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

    keep_keys = {'shared-estimate'}
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

# Ensure new columns exist (backwards-compat if running against older scan output)
if SCAN_STATUS_COL not in scan_df.columns:
    scan_df[SCAN_STATUS_COL] = 'ok'  # assume ok if column is absent
if IN_SCOPE_COL not in scan_df.columns:
    scan_df[IN_SCOPE_COL] = True  # assume all in scope if column is absent

# --- Scope gate ---
# Rows with a scan_status error (Gate 1) are always excluded — they are structurally
# broken files that never reached content evaluation.
# Rows with in_scope = FALSE (Gate 2) are also excluded.
# Only rows that pass both gates participate in comparison and the action queue tabs.
scan_ok = scan_df[SCAN_STATUS_COL].astype(str).str.strip().str.lower() == 'ok'

in_scope = scan_ok & (
    scan_df[IN_SCOPE_COL].astype(str).str.strip().str.lower().isin(['true', '1', 'yes'])
    | (scan_df[IN_SCOPE_COL] == True)
)

# Out-of-scope rows always get not_applicable — no further evaluation
scan_df.loc[~in_scope, STATUS_COL] = STATUS_NOT_APPLICABLE

# --- criteria_passed gate (within in-scope rows only) ---
criteria_true = (
    scan_df[CRITERIA_COL].astype(str).str.strip().str.lower().isin(['true', '1', 'yes'])
    | (scan_df[CRITERIA_COL] == True)
)

# Normalize scenario keys (Learn URL)
scan_df['_scenario_key'] = scan_df[YML_URL_COL].astype(str).map(_normalize_learn_url)
est_df['_scenario_key'] = est_df[YML_URL_COL].astype(str).map(_normalize_learn_url)

# Build title lookup maps for enriching action queue tabs
# title_in_ac        — article title from the Architecture Center (scanner output)
# title_in_calculator — title as it appears in the Pricing Calculator (from estimate_scenarios.xlsx)
ac_title_map = dict(zip(scan_df['_scenario_key'], scan_df.get('title_in_ac', pd.Series(dtype=str)).fillna('')))
calc_title_map = {}
for _, row in est_df.iterrows():
    key = row.get('_scenario_key', '')
    if key:
        calc_title_map[key] = str(row.get('title_in_calculator') or '').strip()

# Build two lookup structures from the inventory:
#   inv_map      — Published rows only; used for estimate link comparison
#   excluded_urls — non-Published rows (e.g. Skip); these are known to the
#                  inventory but intentionally excluded from the calculator.
#                  A scanned article whose URL appears here should never be
#                  surfaced as a new_estimate_candidate.
SKIP_STATUS = 'Skip'
inv_map = {}
excluded_urls = set()
for _, row in est_df.iterrows():
    key = row.get('_scenario_key', '')
    if not key:
        continue
    row_status = str(row.get('status') or '').strip()
    if row_status == SKIP_STATUS:
        excluded_urls.add(key)   # explicitly excluded — do not surface in any action queue
        continue
    inv_link = _normalize_estimate_url(row.get(ESTIMATE_LINK_COL, ''))
    if not inv_link:
        continue
    inv_map[key] = inv_link

matched_in_inventory = scan_df['_scenario_key'].isin(inv_map.keys())
excluded_from_inventory = scan_df['_scenario_key'].isin(excluded_urls)

# Within in-scope rows: apply criteria_passed -> comparison_status logic
in_scope_no_criteria = in_scope & ~criteria_true
# A scanned article is a new candidate only if it has an estimate link AND
# is not already in the inventory (Published) AND is not explicitly excluded
# (Skip or other non-Published status in estimate_scenarios.xlsx)
in_scope_criteria_new = (
    in_scope & criteria_true & ~matched_in_inventory & ~excluded_from_inventory
)

scan_df.loc[in_scope_no_criteria, STATUS_COL] = STATUS_NOT_APPLICABLE
scan_df.loc[in_scope & criteria_true & excluded_from_inventory, STATUS_COL] = STATUS_NOT_APPLICABLE
scan_df.loc[in_scope_criteria_new, STATUS_COL] = STATUS_NEW_CANDIDATE

# Split matched existing scenario into SAME vs NEW estimate link (in-scope only)
applicable = in_scope & criteria_true & matched_in_inventory

for idx, row in scan_df.loc[applicable].iterrows():
    inv_link = inv_map.get(row['_scenario_key'], '')
    scanned_links = _split_estimate_links(row.get(ESTIMATE_LINK_COL, ''))
    if inv_link and any(l == inv_link for l in scanned_links):
        scan_df.at[idx, STATUS_COL] = STATUS_SAME
    else:
        scan_df.at[idx, STATUS_COL] = STATUS_NEW_ESTIMATE

# Reverse check — detect estimate link removal.
# For every Published inventory scenario that IS found in the scan (i.e. the
# article still exists and is in scope) but has criteria_passed = FALSE, the
# estimate link has been removed from the article. This is distinct from
# scenario_removed (page gone) and matched_existing_scenario_new_estimate
# (link changed). Flag it so the calculator team can retire the scenario.
for idx, row in scan_df.loc[in_scope & matched_in_inventory & ~criteria_true].iterrows():
    scan_df.at[idx, STATUS_COL] = STATUS_LINK_REMOVED

# Action queues — all restricted to in-scope rows only.
# Kept separate because they map to different workflows:
#   estimate-updates      → existing inventory scenarios whose estimate link changed
#   new-candidates        → net-new articles not yet in the inventory
#   estimate-link-removed → existing inventory scenarios whose estimate link was removed
estimate_updates = scan_df[
    in_scope & (scan_df[STATUS_COL] == STATUS_NEW_ESTIMATE)
].copy()
estimate_updates.insert(0, 'title_in_calculator',
    estimate_updates['_scenario_key'].map(calc_title_map).fillna(''))
estimate_updates.rename(columns={'title': 'title_in_ac'}, inplace=True, errors='ignore')

new_candidates = scan_df[
    in_scope & (scan_df[STATUS_COL] == STATUS_NEW_CANDIDATE)
].copy()
new_candidates.rename(columns={'title': 'title_in_ac'}, inplace=True, errors='ignore')

link_removed = scan_df[
    in_scope & (scan_df[STATUS_COL] == STATUS_LINK_REMOVED)
].copy()
link_removed.insert(0, 'title_in_calculator',
    link_removed['_scenario_key'].map(calc_title_map).fillna(''))
link_removed.rename(columns={'title': 'title_in_ac'}, inplace=True, errors='ignore')

# Combined count for summary (total rows requiring any action)
needs_action_count = len(estimate_updates) + len(new_candidates) + len(link_removed)

# --- Summary ---
total = len(scan_df)
total_in_scope = int(in_scope.sum())
total_out_of_scope = total - total_in_scope
in_scope_criteria_true = int((in_scope & criteria_true).sum())
in_scope_criteria_false = total_in_scope - in_scope_criteria_true

summary = pd.DataFrame({
    'Metric': [
        # Overall
        'Total scanned scenarios',
        '',
        # Gate 1 — scan_status
        'Gate 1 PASS: scan_status = ok',
        'Gate 1 FAIL: scan_status = error (structural pipeline errors)',
        '',
        # Gate 2 — in_scope (of scan_ok rows)
        'Gate 2 PASS: in_scope = TRUE',
        'Gate 2 FAIL: in_scope = FALSE (missing title / description / image)',
        '',
        # Gate 3 — criteria_passed (of in_scope rows)
        'Gate 3 PASS: criteria_passed = TRUE (has usable estimate link)',
        'Gate 3 FAIL: criteria_passed = FALSE (pricing gap)',
        '',
        # Comparison status (in-scope + criteria_passed = TRUE rows only)
        'matched_existing_scenario_same_estimate',
        'matched_existing_scenario_new_estimate',
        'estimate_link_removed (link removed from article)',
        'new_estimate_candidate',
        'not_applicable (in-scope, no usable estimate)',
        'excluded from comparison (status = Skip)',
        '',
        # Action queues
        'Rows in estimate-updates tab (matched_existing_scenario_new_estimate)',
        'Rows in estimate-link-removed tab (estimate_link_removed)',
        'Rows in new-candidates tab (new_estimate_candidate)',
        'Total rows requiring action',
        '',
        # Run metadata
        'Scan date (UTC)',
        'Repo commit',
    ],
    'Value': [
        total,
        '',
        int(scan_ok.sum()),
        int((~scan_ok).sum()),
        '',
        total_in_scope,
        total_out_of_scope,
        '',
        in_scope_criteria_true,
        in_scope_criteria_false,
        '',
        int((scan_df[STATUS_COL] == STATUS_SAME).sum()),
        int((scan_df[STATUS_COL] == STATUS_NEW_ESTIMATE).sum()),
        int((scan_df[STATUS_COL] == STATUS_LINK_REMOVED).sum()),
        int((scan_df[STATUS_COL] == STATUS_NEW_CANDIDATE).sum()),
        int((in_scope & (scan_df[STATUS_COL] == STATUS_NOT_APPLICABLE)).sum()),
        int((in_scope & excluded_from_inventory).sum()),
        '',
        int(len(estimate_updates)),
        int(len(link_removed)),
        int(len(new_candidates)),
        needs_action_count,
        '',
        datetime.utcnow().isoformat(),
        os.getenv('GITHUB_SHA', 'local'),
    ]
})

with pd.ExcelWriter(SCAN_RESULTS_PATH, engine='openpyxl', mode='w') as writer:
    scan_df.drop(columns=['_scenario_key']).to_excel(writer, sheet_name='scan-results', index=False)
    estimate_updates.drop(columns=['_scenario_key'], errors='ignore').to_excel(writer, sheet_name='estimate-updates', index=False)
    link_removed.drop(columns=['_scenario_key'], errors='ignore').to_excel(writer, sheet_name='estimate-link-removed', index=False)
    new_candidates.drop(columns=['_scenario_key'], errors='ignore').to_excel(writer, sheet_name='new-candidates', index=False)
    summary.to_excel(writer, sheet_name='summary', index=False)
