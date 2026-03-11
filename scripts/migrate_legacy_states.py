#!/usr/bin/env python
"""Migrate legacy calibration states to the new format by injecting indexEntry.

For each legacy state (CalibrationRecord/Parameters missing 'indexEntry'):
  1. Read the CalibrationIndex.json to get the index entry for each version.
  2. Inject 'indexEntry' into CalibrationRecord.json and CalibrationParameters.json.
  3. Also inject into nested 'calculationParameters.indexEntry' if present.

Supports both difcal and normcal.  Backs up originals before modifying.

Usage
-----
    python scripts/migrate_legacy_states.py                # dry run
    python scripts/migrate_legacy_states.py --apply        # apply changes
"""

import argparse
import json
import os
import shutil
import tempfile
from datetime import datetime


CALIB_HOME = os.environ.get("CALIB_HOME", "/SNS/SNAP/shared/Calibration")
POWDER_HOME = os.path.join(CALIB_HOME, "Powder")
BACKUP_DIR = os.path.join(CALIB_HOME, "Backup")


def find_legacy_versions(state_dir, cal_type):
    """Return list of (version, index_entry, files_needing_migration) tuples."""

    if cal_type == "difcal":
        sub = "diffraction"
        idx_name = "CalibrationIndex.json"
        rec_name = "CalibrationRecord.json"
        par_name = "CalibrationParameters.json"
    else:
        sub = "normalization"
        idx_name = "NormalizationIndex.json"
        rec_name = "NormalizationRecord.json"
        par_name = "NormalizationParameters.json"

    base = os.path.join(state_dir, "lite", sub)
    idx_path = os.path.join(base, idx_name)

    if not os.path.isfile(idx_path):
        return []

    with open(idx_path, "r") as fh:
        index_entries = json.load(fh)

    results = []
    for ie in index_entries:
        v = ie["version"]
        folder = os.path.join(base, f"v_{str(v).zfill(4)}")
        if not os.path.isdir(folder):
            continue

        files_to_fix = []
        for fname in [rec_name, par_name]:
            fp = os.path.join(folder, fname)
            if not os.path.isfile(fp):
                continue
            with open(fp, "r") as fh:
                data = json.load(fh)
            if "indexEntry" not in data:
                files_to_fix.append((fp, fname, data))

        if files_to_fix:
            results.append((v, ie, files_to_fix))

    return results


def migrate_file(fp, fname, data, index_entry, dry_run, backup_session):
    """Inject indexEntry into a single JSON file.

    Safety measures:
      - Backs up the original before any modification.
      - Writes to a temp file and renames (atomic on same filesystem).
      - Re-reads the written file and verifies indexEntry round-trips.
    """

    # Add indexEntry at the top level
    data["indexEntry"] = index_entry

    # Also update nested calculationParameters if present (Records have this)
    if "calculationParameters" in data and isinstance(data["calculationParameters"], dict):
        data["calculationParameters"]["indexEntry"] = index_entry
        # Also sync version if present
        if "version" in data["calculationParameters"]:
            data["calculationParameters"]["version"] = index_entry["version"]

    if not dry_run:
        # Backup original
        rel = os.path.relpath(fp, CALIB_HOME)
        bk_path = os.path.join(backup_session, rel)
        os.makedirs(os.path.dirname(bk_path), exist_ok=True)
        shutil.copy2(fp, bk_path)

        # Atomic write: write to temp file in same directory, then rename
        dir_name = os.path.dirname(fp)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp", prefix=".migrate_")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(data, fh, indent=4)
            os.replace(tmp_path, fp)  # atomic on same filesystem
        except Exception:
            # Clean up temp file on failure
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

        # Post-write verification: re-read and confirm indexEntry matches
        with open(fp, "r") as fh:
            written = json.load(fh)
        if written.get("indexEntry") != index_entry:
            raise RuntimeError(
                f"VERIFICATION FAILED for {fp}: "
                f"written indexEntry does not match expected. "
                f"Original backup at: {bk_path}"
            )

    return True


def main():
    parser = argparse.ArgumentParser(description="Migrate legacy states to new index format.")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry run).")
    parser.add_argument("--state", type=str, default=None,
                        help="Migrate only this single stateID (for testing on one state first).")
    args = parser.parse_args()

    dry_run = not args.apply
    prefix = "[DRY RUN] " if dry_run else ""

    print(f"{prefix}Legacy state migration")
    print(f"Calibration home: {CALIB_HOME}")
    if args.state:
        print(f"Filtering to single state: {args.state}")
    print()

    # Enumerate all states
    all_states = sorted(
        d for d in os.listdir(POWDER_HOME)
        if os.path.isdir(os.path.join(POWDER_HOME, d)) and len(d) == 16
    )

    # Apply optional single-state filter
    if args.state:
        if args.state not in all_states:
            print(f"ERROR: state {args.state} not found in {POWDER_HOME}")
            return
        all_states = [args.state]

    # Find all legacy versions across all states
    migration_plan = []  # (stateID, cal_type, version, index_entry, files_to_fix)

    for sid in all_states:
        state_dir = os.path.join(POWDER_HOME, sid)
        for cal_type in ["difcal", "normcal"]:
            legacy_versions = find_legacy_versions(state_dir, cal_type)
            for v, ie, files in legacy_versions:
                migration_plan.append((sid, cal_type, v, ie, files))

    if not migration_plan:
        print("No legacy versions found — nothing to migrate.")
        return

    # Summarise
    states_affected = sorted(set(sid for sid, *_ in migration_plan))
    total_files = sum(len(files) for _, _, _, _, files in migration_plan)

    print(f"Found {len(migration_plan)} legacy version(s) across {len(states_affected)} state(s)")
    print(f"Total files to update: {total_files}")
    print()

    for sid, cal_type, v, ie, files in migration_plan:
        file_names = [fname for _, fname, _ in files]
        print(f"  {prefix}{sid}  {cal_type} v{v}: {', '.join(file_names)}")
        if dry_run:
            # Show exactly what will be injected
            print(f"    indexEntry to inject:")
            for key, val in ie.items():
                print(f"      {key}: {val}")

    print()

    if dry_run:
        print("Run with --apply to perform the migration.")
        if not args.state:
            print("TIP: use --state <stateID> to test on a single state first.")
        return

    # Create backup session
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_session = os.path.join(BACKUP_DIR, f"migrate_legacy_{stamp}")
    os.makedirs(backup_session, exist_ok=True)
    print(f"Backup session: {backup_session}")
    print()

    # Apply
    updated = 0
    for sid, cal_type, v, ie, files in migration_plan:
        for fp, fname, data in files:
            migrate_file(fp, fname, data, ie, dry_run=False, backup_session=backup_session)
            print(f"  Updated: {fp}")
            print(f"    ✓ verified indexEntry round-trips correctly")
            updated += 1

    print(f"\n{updated} file(s) updated.")
    print(f"Backups saved to: {backup_session}")

    # Verify by re-scanning
    print("\nPost-migration check:")
    remaining = 0
    for sid in states_affected:
        state_dir = os.path.join(POWDER_HOME, sid)
        for cal_type in ["difcal", "normcal"]:
            leftovers = find_legacy_versions(state_dir, cal_type)
            if leftovers:
                remaining += len(leftovers)
                for v, ie, files in leftovers:
                    file_names = [fname for _, fname, _ in files]
                    print(f"  STILL LEGACY: {sid} {cal_type} v{v}: {', '.join(file_names)}")

    if remaining == 0:
        print("  All migrated states now have indexEntry. ✓")


if __name__ == "__main__":
    main()
