"""run_image_check.py — Detect image changes for scenarios in estimate_scenarios.xlsx.

Operates in two modes controlled by the --update-baseline flag:

DETECT mode (default — used by the monthly scan workflow):
  Compares the SHA-256 hash of each image file against the stored baseline in
  estimate_scenarios.xlsx. Flags any image whose hash has changed since the
  last baseline update. Does NOT update the stored hashes — the baseline stays
  frozen until you explicitly trigger an update.

UPDATE BASELINE mode (--update-baseline — separate manual workflow):
  Recomputes and stores SHA-256 hashes for all non-Skip scenarios without
  performing any comparison. Run this only after you have confirmed that the
  Pricing Calculator has been updated with the new image. This commits the new
  baseline so the next detect run compares against the freshly confirmed state.

This separation ensures that a detected image change stays visible across
monthly runs until you explicitly action it and update the baseline.

image_change_status values (detect mode only):
  unchanged         — Hash matches the stored baseline; image has not changed.
  changed           — Hash differs from the stored baseline; image was updated.
  new_baseline      — No stored hash exists yet (first run or new row). Hash
                      recorded; no comparison made.
  image_not_found   — primary_image_path does not exist on disk.
  skipped           — Row has status = 'Skip' or blank primary_image_path.

The 'image-changes' tab contains only 'changed' and 'image_not_found' rows —
the action queue for updating the Pricing Calculator.

Usage:
  # Monthly detect run (called by scan_and_compare.yml):
  python scripts/run_image_check.py [--repo-root PATH]

  # Manual baseline update (called by update_image_baseline.yml):
  python scripts/run_image_check.py --update-baseline [--repo-root PATH]

  --repo-root        Root of the cloned repo (default: current working directory).
  --update-baseline  Run in baseline-update mode instead of detect mode.
"""

import argparse
import hashlib
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

# ── Paths ──────────────────────────────────────────────────────────────────
SCAN_RESULTS_PATH = Path('scan-results.xlsx')
ESTIMATE_SCENARIOS_PATH = Path('estimate_scenarios.xlsx')

# Column names
STATUS_COL = 'status'
YML_URL_COL = 'yml_url'
TITLE_COL = 'title_in_calculator'
IMAGE_PATH_COL = 'primary_image_path'
IMAGE_SHA_COL = 'primary_image_sha256'
SKIP_STATUS = 'Skip'

# image_change_status values
IMG_UNCHANGED = 'unchanged'
IMG_CHANGED = 'changed'
IMG_NEW_BASELINE = 'new_baseline'
IMG_NOT_FOUND = 'image_not_found'
IMG_SKIPPED = 'skipped'


# ── Hashing ────────────────────────────────────────────────────────────────

def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of a file's bytes."""
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        '--repo-root', default='.',
        help='Root of the cloned repo (default: current working directory)',
    )
    ap.add_argument(
        '--update-baseline', action='store_true',
        help='Update stored hashes without comparing (run after actioning changes)',
    )
    args = ap.parse_args()
    repo_root = Path(args.repo_root).resolve()
    update_baseline_mode = args.update_baseline

    # ── Load data ──────────────────────────────────────────────────────────
    if not update_baseline_mode and not SCAN_RESULTS_PATH.exists():
        sys.exit(f'ERROR: {SCAN_RESULTS_PATH} not found. Run scan and compare steps first.')
    if not ESTIMATE_SCENARIOS_PATH.exists():
        sys.exit(f'ERROR: {ESTIMATE_SCENARIOS_PATH} not found.')

    if update_baseline_mode:
        print('Mode: UPDATE BASELINE — hashes will be recomputed and stored. No comparison performed.')
    else:
        print('Mode: DETECT — comparing current hashes against stored baseline.')

    est_df = pd.read_excel(ESTIMATE_SCENARIOS_PATH, dtype=str).fillna('')

    # Build title_in_ac lookup from scan-results.xlsx if available
    # (run after the scan step so scan-results.xlsx exists)
    ac_title_map = {}
    if SCAN_RESULTS_PATH.exists():
        try:
            scan_df = pd.read_excel(SCAN_RESULTS_PATH)
            for _, row in scan_df.iterrows():
                url = str(row.get('yml_url') or '').strip().rstrip('/')
                t = str(row.get('title_in_ac') or '').strip()
                if url:
                    ac_title_map[url] = t
        except Exception:
            pass  # non-fatal — title_in_ac will be blank if lookup fails

    required = {STATUS_COL, YML_URL_COL, IMAGE_PATH_COL}
    missing = required - set(est_df.columns)
    if missing:
        sys.exit(f'ERROR: estimate_scenarios.xlsx missing columns: {sorted(missing)}')

    # Add sha column if not present (first ever run)
    if IMAGE_SHA_COL not in est_df.columns:
        est_df[IMAGE_SHA_COL] = ''

    # ── Process each inventory row ─────────────────────────────────────────
    image_rows = []
    changed_count = 0
    unchanged_count = 0
    new_baseline_count = 0
    not_found_count = 0
    skipped_count = 0

    for idx, row in est_df.iterrows():
        status = str(row.get(STATUS_COL) or '').strip()
        yml_url = str(row.get(YML_URL_COL) or '').strip()
        title_in_ac = ac_title_map.get(yml_url.rstrip('/'), '')
        title = str(row.get(TITLE_COL) or '').strip() if TITLE_COL in est_df.columns else ''
        image_path_str = str(row.get(IMAGE_PATH_COL) or '').strip()
        stored_sha = str(row.get(IMAGE_SHA_COL) or '').strip()

        # Skip non-Published rows or rows without an image path
        if status == SKIP_STATUS or not image_path_str:
            est_df.at[idx, IMAGE_SHA_COL] = stored_sha  # preserve existing
            skipped_count += 1
            continue

        image_file = repo_root / image_path_str

        # ── Image not found on disk ────────────────────────────────────────
        if not image_file.exists():
            not_found_count += 1
            image_rows.append({
                'yml_url': yml_url,
                'title_in_ac': title_in_ac,
                'title_in_calculator': title,
                'primary_image_path': image_path_str,
                'image_change_status': IMG_NOT_FOUND,
                'stored_sha256': stored_sha,
                'current_sha256': '',
                'note': (
                    'Image file not found on disk at the specified path. '
                    'The file may have been moved, renamed, or deleted in the repo.'
                ),
            })
            print(f'  NOT FOUND  {image_path_str}')
            continue

        # ── Hash the current file ──────────────────────────────────────────
        current_sha = sha256_file(image_file)

        # ── UPDATE BASELINE mode — store hash, skip comparison ────────────
        if update_baseline_mode:
            est_df.at[idx, IMAGE_SHA_COL] = current_sha
            new_baseline_count += 1
            print(f'  UPDATED    {image_path_str}  ({current_sha[:12]}...)')
            continue

        # ── DETECT mode — compare against stored baseline ─────────────────
        if not stored_sha:
            # No baseline yet — record hash but don't flag as changed
            new_baseline_count += 1
            est_df.at[idx, IMAGE_SHA_COL] = current_sha
            print(f'  BASELINE   {image_path_str}  ({current_sha[:12]}...)')
            continue  # new_baseline rows don't appear in the image-changes tab

        if current_sha == stored_sha:
            unchanged_count += 1
            # Do NOT update stored hash — baseline stays frozen until explicit update
            print(f'  unchanged  {image_path_str}')
        else:
            changed_count += 1
            # Do NOT update stored hash — keep the old value so the change
            # remains visible on every detect run until baseline is updated
            image_rows.append({
                'yml_url': yml_url,
                'title_in_ac': title_in_ac,
                'title_in_calculator': title,
                'primary_image_path': image_path_str,
                'image_change_status': IMG_CHANGED,
                'stored_sha256': stored_sha,
                'current_sha256': current_sha,
                'note': (
                    'Image file hash has changed since the last baseline update. '
                    'Review the image and update the Pricing Calculator. '
                    'Then run the Update Image Baseline workflow to reset the baseline.'
                ),
            })
            print(f'  CHANGED    {image_path_str}')
            print(f'             was: {stored_sha[:12]}...')
            print(f'             now: {current_sha[:12]}...')

    # ── Build image-changes DataFrame ─────────────────────────────────────
    # Tab shows only actionable rows: changed + not_found
    changes_df = pd.DataFrame(image_rows, columns=[
        'yml_url', 'title_in_ac', 'title_in_calculator', 'primary_image_path',
        'image_change_status', 'stored_sha256', 'current_sha256', 'note',
    ])

    print(f'\nImage check summary:')
    print(f'  unchanged:        {unchanged_count}')
    print(f'  changed:          {changed_count}')
    print(f'  new_baseline:     {new_baseline_count}')
    print(f'  image_not_found:  {not_found_count}')
    print(f'  skipped:          {skipped_count}')
    print(f'  Action needed:    {changed_count + not_found_count}')

    # ── Write estimate_scenarios.xlsx only when hashes changed ──────────────
    # In detect mode: only write if new_baseline rows were recorded (first run
    # or new inventory row). Changed images intentionally keep the old hash so
    # the change stays visible until the baseline is explicitly updated.
    # In update-baseline mode: always write.
    should_write_est = update_baseline_mode or new_baseline_count > 0
    if should_write_est:
        cols = list(est_df.columns)
        if IMAGE_SHA_COL not in cols:
            insert_at = cols.index(IMAGE_PATH_COL) + 1
            cols.insert(insert_at, IMAGE_SHA_COL)
            est_df = est_df[cols]
        est_df.to_excel(ESTIMATE_SCENARIOS_PATH, index=False)
        if update_baseline_mode:
            print(f'\nBaseline updated: wrote {new_baseline_count} hash(es) to {ESTIMATE_SCENARIOS_PATH}.')
        else:
            print(f'\nRecorded {new_baseline_count} new baseline hash(es) to {ESTIMATE_SCENARIOS_PATH}.')
    else:
        print(f'\nDetect mode: {ESTIMATE_SCENARIOS_PATH} not modified (baseline preserved).')

    # ── Update scan-results.xlsx (detect mode only) ──────────────────────────
    if update_baseline_mode:
        print('Baseline update complete. scan-results.xlsx not modified.')
        return

    # Read all existing sheets so we preserve scan-results, needs-review, etc.
    existing_sheets = {}
    with pd.ExcelFile(SCAN_RESULTS_PATH, engine='openpyxl') as xf:
        for sheet_name in xf.sheet_names:
            existing_sheets[sheet_name] = pd.read_excel(xf, sheet_name=sheet_name)

    # Append image changes section to summary
    summary_df = existing_sheets.get('summary', pd.DataFrame({'Metric': [], 'Value': []}))
    image_summary = pd.DataFrame({
        'Metric': [
            '',
            '── Image Changes ─────────────────────────────',
            'Check run date (UTC)',
            'Scenarios checked (all except Skip)',
            'unchanged (image hash matches baseline)',
            'changed (image updated in repo)',
            'new_baseline (first run — hash recorded, no comparison)',
            'image_not_found (file missing from repo)',
            'skipped (status = Skip or no image path)',
            'Scenarios needing action (changed + not found)',
        ],
        'Value': [
            '',
            '',
            datetime.utcnow().isoformat(),
            unchanged_count + changed_count + new_baseline_count + not_found_count,
            unchanged_count,
            changed_count,
            new_baseline_count,
            not_found_count,
            skipped_count,
            changed_count + not_found_count,
        ],
    })
    summary_df = pd.concat([summary_df, image_summary], ignore_index=True)

    with pd.ExcelWriter(SCAN_RESULTS_PATH, engine='openpyxl', mode='w') as writer:
        for sheet_name, df in existing_sheets.items():
            if sheet_name == 'summary':
                continue
            df.to_excel(writer, sheet_name=sheet_name, index=False)
        changes_df.to_excel(writer, sheet_name='image-changes', index=False)
        summary_df.to_excel(writer, sheet_name='summary', index=False)

    print(f'Wrote image-changes tab to {SCAN_RESULTS_PATH}')


if __name__ == '__main__':
    main()
