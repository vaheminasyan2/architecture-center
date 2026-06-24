"""run_inventory_health.py — Inventory health check for estimate_scenarios.xlsx.

Performs two checks against every scenario in the reference inventory except
those explicitly marked with status = 'Skip'. All other statuses are processed,
consistent with run_image_check.py and run_compare_only.py.

  Check 1 — Reverse lookup (no network):
    Is the inventory scenario's yml_url present anywhere in the current
    scan-results.xlsx? If the source file was deleted from the repo, it will
    not appear in scan results at all.

  Check 2 — HTTP liveness check (network):
    For scenarios whose file still exists in the repo (found in scan results),
    make an HTTP GET to the yml_url and follow redirects. If the final URL
    differs from the requested URL, or if the response is a 404, the scenario
    is flagged accordingly.

    Requests are throttled (default: 1 per second) to be polite to
    learn.microsoft.com. A browser-like User-Agent is sent to avoid blocks.

Output:
  Adds an 'inventory-health' worksheet to scan-results.xlsx containing one
  row per inventory scenario with the following columns:
    yml_url               — The canonical URL from estimate_scenarios.xlsx
    title_in_ac           — Article title from the Architecture Center (scanner output)
    title_in_calculator   — Title as it appears in the Pricing Calculator (from estimate_scenarios.xlsx)
    estimate_link         — Estimate link from estimate_scenarios.xlsx
    inventory_status      — active | scenario_removed | scenario_redirected |
                            scan_error | out_of_scope
    redirect_target       — Final URL after following redirects (blank if none)
    http_status_code      — HTTP response code (blank for scenario_removed)
    note                  — Human-readable explanation

  Also adds an 'inventory-health' section to the summary worksheet.

Usage:
  python scripts/run_inventory_health.py [--throttle SECONDS] [--timeout SECONDS]
"""

import sys
import time
import argparse
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pandas as pd

# ── Constants ──────────────────────────────────────────────────────────────
SCAN_RESULTS_PATH = Path('scan-results.xlsx')
ESTIMATE_SCENARIOS_PATH = Path('estimate_scenarios.xlsx')

STATUS_COL = 'status'
SKIP_STATUS = 'Skip'
YML_URL_COL = 'yml_url'
SCAN_STATUS_COL = 'scan_status'
IN_SCOPE_COL = 'in_scope'

# inventory_status values
STATUS_ACTIVE = 'active'
STATUS_REMOVED = 'scenario_removed'
STATUS_REDIRECTED = 'scenario_redirected'
STATUS_SCAN_ERROR = 'scan_error'
STATUS_OUT_OF_SCOPE = 'out_of_scope'

DEFAULT_THROTTLE = 1.0   # seconds between HTTP requests
DEFAULT_TIMEOUT = 10     # seconds per HTTP request

USER_AGENT = (
    'Mozilla/5.0 (compatible; ArchCenterScanner/1.0; '
    '+https://github.com/MicrosoftDocs/architecture-center)'
)


# ── URL helpers ────────────────────────────────────────────────────────────

def _normalize_url(url: str) -> str:
    """Normalize a Learn URL for stable matching.

    - Lowercases scheme and host
    - Strips trailing slashes
    - Strips a trailing /index segment — files named index.yml/index.md publish
      without the /index suffix on learn.microsoft.com, so both forms are
      equivalent and should not be treated as a redirect.
    """
    if not url:
        return ''
    u = str(url).strip()
    parts = urlsplit(u)
    path = parts.path.rstrip('/')
    if path.lower().endswith('/index'):
        path = path[:-len('/index')]
    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        path,
        '',
        '',
    ))


def _urls_match(a: str, b: str) -> bool:
    return _normalize_url(a) == _normalize_url(b)


# ── HTTP liveness check ────────────────────────────────────────────────────

def _check_url(url: str, timeout: int) -> tuple:
    """Return (final_url, http_status_code, redirected: bool, error: str|None).

    Follows redirects; compares the final URL to the requested URL to detect
    redirects. Returns error string on network failure.
    """
    try:
        import urllib.request
        import urllib.error

        req = urllib.request.Request(
            url,
            headers={'User-Agent': USER_AGENT},
            method='GET',
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final_url = resp.geturl()
            status = resp.status
            redirected = not _urls_match(url, final_url)
            return final_url, status, redirected, None

    except Exception as exc:
        # urllib raises HTTPError for 4xx/5xx
        try:
            code = exc.code  # type: ignore[attr-defined]
            final_url = getattr(exc, 'url', url) or url
            redirected = not _urls_match(url, final_url)
            return final_url, code, redirected, None
        except AttributeError:
            return url, None, False, str(exc)


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        '--throttle', type=float, default=DEFAULT_THROTTLE,
        help=f'Seconds between HTTP requests (default: {DEFAULT_THROTTLE})',
    )
    ap.add_argument(
        '--timeout', type=int, default=DEFAULT_TIMEOUT,
        help=f'HTTP request timeout in seconds (default: {DEFAULT_TIMEOUT})',
    )
    args = ap.parse_args()

    # ── Load data ──────────────────────────────────────────────────────────
    if not SCAN_RESULTS_PATH.exists():
        sys.exit(f'ERROR: {SCAN_RESULTS_PATH} not found. Run the scan and compare steps first.')
    if not ESTIMATE_SCENARIOS_PATH.exists():
        sys.exit(f'ERROR: {ESTIMATE_SCENARIOS_PATH} not found.')

    scan_df = pd.read_excel(SCAN_RESULTS_PATH)
    est_df = pd.read_excel(ESTIMATE_SCENARIOS_PATH)

    if YML_URL_COL not in est_df.columns:
        sys.exit(f'ERROR: estimate_scenarios.xlsx is missing required column: {YML_URL_COL}')
    if YML_URL_COL not in scan_df.columns:
        sys.exit(f'ERROR: scan-results.xlsx is missing required column: {YML_URL_COL}')

    # ── Build lookup sets from scan results ────────────────────────────────
    # Normalized URL → scan_status and in_scope for every scanned row
    scan_index: dict = {}
    for _, row in scan_df.iterrows():
        key = _normalize_url(str(row.get(YML_URL_COL) or ''))
        if not key:
            continue
        scan_index[key] = {
            'scan_status': str(row.get(SCAN_STATUS_COL) or 'ok').strip().lower(),
            'in_scope': str(row.get(IN_SCOPE_COL) or 'false').strip().lower()
                        in ('true', '1', 'yes') or row.get(IN_SCOPE_COL) is True,
            'title_in_ac': str(row.get('title_in_ac') or '').strip(),
        }

    # ── Process each inventory row ─────────────────────────────────────────
    health_rows = []
    skipped_count = 0
    total = len(est_df)

    print(f'Checking {total} inventory scenarios (all except Skip)...')

    for i, (_, inv_row) in enumerate(est_df.iterrows(), 1):
        row_status = str(inv_row.get(STATUS_COL) or '').strip()
        yml_url = str(inv_row.get(YML_URL_COL) or '').strip()
        estimate_link = str(inv_row.get('estimate_link') or '').strip()
        title_in_calculator = str(inv_row.get('title_in_calculator') or '').strip()

        # Skip rows explicitly marked Skip — all other statuses are processed
        if row_status == SKIP_STATUS:
            skipped_count += 1
            print(f'  [{i}/{total}] skipped   {yml_url}  (status=Skip)')
            continue

        if not yml_url:
            skipped_count += 1
            continue

        norm_url = _normalize_url(yml_url)
        scan_hit = scan_index.get(norm_url)

        # ── Check 1: Reverse lookup ────────────────────────────────────────
        if scan_hit is None:
            # Not in scan results at all — file deleted from repo
            health_rows.append({
                'yml_url': yml_url,
                'title_in_ac': '',
                'title_in_calculator': title_in_calculator,
                'estimate_link': estimate_link,
                'inventory_status': STATUS_REMOVED,
                'redirect_target': '',
                'http_status_code': '',
                'note': (
                    'Source file not found in repo scan results. '
                    'The YML/MD file may have been deleted or renamed.'
                ),
            })
            print(f'  [{i}/{total}] REMOVED   {yml_url}')
            continue

        # File exists in scan results — classify by scan_status / in_scope
        scan_status = scan_hit['scan_status']
        in_scope = scan_hit['in_scope']
        title_in_ac = scan_hit.get('title_in_ac', '')

        if scan_status != 'ok':
            # Gate 1 failure — file exists but is structurally broken
            health_rows.append({
                'yml_url': yml_url,
                'title_in_ac': title_in_ac,
                'title_in_calculator': title_in_calculator,
                'estimate_link': estimate_link,
                'inventory_status': STATUS_SCAN_ERROR,
                'redirect_target': '',
                'http_status_code': '',
                'note': (
                    f'File found in repo but failed scanner Gate 1 '
                    f'(scan_status = {scan_status}). Fix the source file first.'
                ),
            })
            print(f'  [{i}/{total}] SCAN_ERR  {yml_url}  ({scan_status})')
            continue

        if not in_scope:
            # Gate 2 failure — file exists and parses but is out of scope
            health_rows.append({
                'yml_url': yml_url,
                'title_in_ac': title_in_ac,
                'title_in_calculator': title_in_calculator,
                'estimate_link': estimate_link,
                'inventory_status': STATUS_OUT_OF_SCOPE,
                'redirect_target': '',
                'http_status_code': '',
                'note': (
                    'File found in repo and parses correctly, but the scenario '
                    'is currently out of scope (see out_of_scope_reason in scan-results).'
                ),
            })
            print(f'  [{i}/{total}] OOS       {yml_url}')
            continue

        # ── Check 2: HTTP liveness ─────────────────────────────────────────
        # File is in scope — now verify the live URL is still serving correctly
        print(f'  [{i}/{total}] checking  {yml_url}', end='', flush=True)
        final_url, status_code, redirected, err = _check_url(yml_url, args.timeout)

        if err:
            # Network error — treat conservatively, flag for review
            health_rows.append({
                'yml_url': yml_url,
                'title_in_ac': title_in_ac,
                'title_in_calculator': title_in_calculator,
                'estimate_link': estimate_link,
                'inventory_status': STATUS_ACTIVE,   # don't flag on transient errors
                'redirect_target': '',
                'http_status_code': f'error: {err}',
                'note': f'HTTP check failed with network error: {err}. Verify manually.',
            })
            print(f' → network error: {err}')

        elif status_code == 404:
            health_rows.append({
                'yml_url': yml_url,
                'title_in_ac': title_in_ac,
                'title_in_calculator': title_in_calculator,
                'estimate_link': estimate_link,
                'inventory_status': STATUS_REMOVED,
                'redirect_target': final_url,
                'http_status_code': status_code,
                'note': (
                    'URL returned 404. The page has been removed from publishing '
                    'even though the source file may still exist in the repo.'
                ),
            })
            print(f' → 404 NOT FOUND')

        elif redirected:
            health_rows.append({
                'yml_url': yml_url,
                'title_in_ac': title_in_ac,
                'title_in_calculator': title_in_calculator,
                'estimate_link': estimate_link,
                'inventory_status': STATUS_REDIRECTED,
                'redirect_target': final_url,
                'http_status_code': status_code,
                'note': (
                    f'URL redirects to a different page. '
                    f'The scenario may have been replaced or merged.'
                ),
            })
            print(f' → REDIRECTED to {final_url}')

        else:
            health_rows.append({
                'yml_url': yml_url,
                'title_in_ac': title_in_ac,
                'title_in_calculator': title_in_calculator,
                'estimate_link': estimate_link,
                'inventory_status': STATUS_ACTIVE,
                'redirect_target': '',
                'http_status_code': status_code,
                'note': 'URL resolves correctly.',
            })
            print(f' → active ({status_code})')

        # Throttle between HTTP requests
        time.sleep(args.throttle)

    # ── Build health DataFrame ─────────────────────────────────────────────
    health_df = pd.DataFrame(health_rows, columns=[
        'yml_url', 'title_in_ac', 'title_in_calculator', 'estimate_link',
        'inventory_status', 'redirect_target', 'http_status_code', 'note',
    ])

    # ── Summary counts ─────────────────────────────────────────────────────
    status_counts = health_df['inventory_status'].value_counts().to_dict()
    needs_action = health_df[
        health_df['inventory_status'].isin([STATUS_REMOVED, STATUS_REDIRECTED])
    ]

    print(f'\nInventory health summary:')
    print(f'  skipped (status=Skip): {skipped_count}')
    for status, count in sorted(status_counts.items()):
        print(f'  {status}: {count}')
    print(f'  Scenarios needing action: {len(needs_action)}')

    # ── Write to Excel ─────────────────────────────────────────────────────
    # Read all existing sheets so we can preserve + update them
    existing_sheets = {}
    with pd.ExcelFile(SCAN_RESULTS_PATH, engine='openpyxl') as xf:
        for sheet_name in xf.sheet_names:
            existing_sheets[sheet_name] = pd.read_excel(xf, sheet_name=sheet_name)

    # Build updated summary with inventory health section appended
    summary_df = existing_sheets.get('summary', pd.DataFrame({'Metric': [], 'Value': []}))

    health_summary_rows = pd.DataFrame({
        'Metric': [
            '',
            '── Inventory Health ──────────────────────────',
            f'Check run date (UTC)',
            f'Inventory scenarios checked (all except Skip)',
            f'skipped (status = Skip)',
            f'active (URL resolves correctly)',
            f'scenario_removed (file deleted or page unpublished)',
            f'scenario_redirected (URL redirects to different page)',
            f'scan_error (source file has structural issues)',
            f'out_of_scope (file exists but out of scope)',
            f'Scenarios needing action (removed + redirected)',
        ],
        'Value': [
            '',
            '',
            datetime.utcnow().isoformat(),
            len(health_df),
            skipped_count,
            int(status_counts.get(STATUS_ACTIVE, 0)),
            int(status_counts.get(STATUS_REMOVED, 0)),
            int(status_counts.get(STATUS_REDIRECTED, 0)),
            int(status_counts.get(STATUS_SCAN_ERROR, 0)),
            int(status_counts.get(STATUS_OUT_OF_SCOPE, 0)),
            len(needs_action),
        ],
    })

    summary_df = pd.concat([summary_df, health_summary_rows], ignore_index=True)

    with pd.ExcelWriter(SCAN_RESULTS_PATH, engine='openpyxl', mode='w') as writer:
        # Preserve all existing sheets in order
        for sheet_name, df in existing_sheets.items():
            if sheet_name == 'summary':
                continue   # write updated summary below
            df.to_excel(writer, sheet_name=sheet_name, index=False)
        # Write new + updated sheets
        health_df.to_excel(writer, sheet_name='inventory-health', index=False)
        summary_df.to_excel(writer, sheet_name='summary', index=False)

    print(f'\nWrote inventory-health tab to {SCAN_RESULTS_PATH}')


if __name__ == '__main__':
    main()
