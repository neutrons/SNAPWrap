#!/usr/bin/env python
"""Crawl all IPTS folders and build a tally of reduced runs per state.

Each reduced run is classified as **auto** or **manual** by comparing the
mtime of the autoreduce log with the mtime of the reduced-run folder.
If the two are within ``AUTO_THRESHOLD_SECONDS`` (default 120 s) the run
is considered an autoreduction; otherwise it is manual.

Output
------
Writes a JSON file to {calibration_home}/reductionTally.json with structure::

    {
        "generated": "2026-03-10T...",
        "ipts_scanned": 546,
        "ipts_with_reductions": 12,
        "states": {
            "<stateID>": {
                "total_runs": 42,
                "auto_runs": 38,
                "manual_runs": 4,
                "ipts": {
                    "37478": {
                        "runs": {
                            "68984": "auto",
                            "68985": "auto",
                            "68986": "manual"
                        }
                    },
                    ...
                }
            },
            ...
        }
    }
"""

import json
import os
import sys
from datetime import datetime

SNAP_ROOT = "/SNS/SNAP"
# Allow override for testing
CALIB_HOME = os.environ.get("CALIB_HOME", "/SNS/SNAP/shared/Calibration")
OUTPUT_PATH = os.path.join(CALIB_HOME, "reductionTally.json")

# Maximum time difference (seconds) between autoreduce log mtime and
# reduced-folder mtime to classify a run as auto-reduced.
AUTO_THRESHOLD_SECONDS = 120


def classify_run(ipts_num, state_id, run_number, run_folder_path):
    """Classify a reduced run as 'auto' or 'manual'.

    Compares the mtime of the autoreduce log file with the mtime of the
    reduced-run folder.  If the difference is within AUTO_THRESHOLD_SECONDS
    the run is classified as 'auto'; otherwise 'manual'.  If the log file
    does not exist the run is classified as 'manual' (no autoreduction
    evidence).
    """
    log_path = os.path.join(
        SNAP_ROOT,
        f"IPTS-{ipts_num}",
        "shared",
        "autoreduce",
        "reduction_log",
        f"SNAP_{run_number}.nxs.h5.log",
    )

    if not os.path.exists(log_path):
        return "manual"

    try:
        log_mtime = os.path.getmtime(log_path)
        folder_mtime = os.path.getmtime(run_folder_path)
        diff = abs(log_mtime - folder_mtime)
        return "auto" if diff <= AUTO_THRESHOLD_SECONDS else "manual"
    except OSError:
        return "manual"


def main():
    print(f"Scanning IPTS folders under {SNAP_ROOT} ...")
    print(f"Output will be written to: {OUTPUT_PATH}")
    print(f"Auto-threshold: {AUTO_THRESHOLD_SECONDS} seconds")
    print()

    # Gather all IPTS directories
    all_entries = sorted(os.listdir(SNAP_ROOT))
    ipts_dirs = [e for e in all_entries if e.startswith("IPTS-")]
    print(f"Found {len(ipts_dirs)} IPTS folders")

    tally = {}       # stateID -> { "total_runs": int, "auto_runs": int, "manual_runs": int,
                     #               "ipts": { ipts_num: { "runs": { run: "auto"|"manual" } } } }
    ipts_scanned = 0
    ipts_with_reductions = 0
    errors = []
    global_auto = 0
    global_manual = 0

    for i, ipts_name in enumerate(ipts_dirs):
        ipts_num = ipts_name.split("-")[1]
        snapred_dir = os.path.join(SNAP_ROOT, ipts_name, "shared", "SNAPRed")

        ipts_scanned += 1

        if not os.path.isdir(snapred_dir):
            continue

        ipts_with_reductions += 1

        # Each subdirectory of SNAPRed is a stateID (skip 'export' and other non-state dirs)
        try:
            state_dirs = os.listdir(snapred_dir)
        except PermissionError as e:
            errors.append(f"Permission denied: {snapred_dir}")
            continue
        except Exception as e:
            errors.append(f"Error listing {snapred_dir}: {e}")
            continue

        for state_name in state_dirs:
            # State IDs are 16-char hex strings
            if len(state_name) != 16:
                continue

            state_path = os.path.join(snapred_dir, state_name)
            if not os.path.isdir(state_path):
                continue

            # Look inside lite/ for run folders
            lite_path = os.path.join(state_path, "lite")
            use_lite = os.path.isdir(lite_path)
            if not use_lite:
                # Maybe runs are directly inside the state folder?
                # Check for numeric subdirectories
                try:
                    contents = os.listdir(state_path)
                    runs = [c for c in contents if c.isdigit()]
                except PermissionError:
                    errors.append(f"Permission denied: {state_path}")
                    continue
                if not runs:
                    continue
            else:
                try:
                    contents = os.listdir(lite_path)
                    runs = [c for c in contents if c.isdigit()]
                except PermissionError:
                    errors.append(f"Permission denied: {lite_path}")
                    continue

            if not runs:
                continue

            if state_name not in tally:
                tally[state_name] = {"total_runs": 0, "auto_runs": 0, "manual_runs": 0, "ipts": {}}

            # Classify each run and determine its folder path
            run_classifications = {}
            for run in sorted(runs):
                # Determine the actual folder path for the run
                if use_lite:
                    run_folder = os.path.join(lite_path, run)
                else:
                    run_folder = os.path.join(state_path, run)
                kind = classify_run(ipts_num, state_name, run, run_folder)
                run_classifications[run] = kind

            auto_count = sum(1 for v in run_classifications.values() if v == "auto")
            manual_count = len(run_classifications) - auto_count

            tally[state_name]["ipts"][ipts_num] = {"runs": run_classifications}
            tally[state_name]["total_runs"] += len(run_classifications)
            tally[state_name]["auto_runs"] += auto_count
            tally[state_name]["manual_runs"] += manual_count
            global_auto += auto_count
            global_manual += manual_count

        # Progress
        if (i + 1) % 50 == 0 or (i + 1) == len(ipts_dirs):
            print(f"  scanned {i + 1}/{len(ipts_dirs)} IPTS folders "
                  f"({ipts_with_reductions} with reductions, "
                  f"{len(tally)} states seen so far)")

    print()
    print(f"Scan complete.")
    print(f"  IPTS scanned:          {ipts_scanned}")
    print(f"  IPTS with reductions:  {ipts_with_reductions}")
    print(f"  Unique states found:   {len(tally)}")

    total_runs = sum(s["total_runs"] for s in tally.values())
    print(f"  Total reduced runs:    {total_runs}")
    print(f"    Auto-reduced:        {global_auto}")
    print(f"    Manually reduced:    {global_manual}")

    if errors:
        print(f"\n  Errors ({len(errors)}):")
        for e in errors:
            print(f"    {e}")

    # Sort by total_runs descending for readability
    sorted_states = dict(sorted(tally.items(), key=lambda x: x[1]["total_runs"], reverse=True))

    output = {
        "generated": datetime.now().isoformat(),
        "ipts_scanned": ipts_scanned,
        "ipts_with_reductions": ipts_with_reductions,
        "unique_states": len(tally),
        "total_reduced_runs": total_runs,
        "total_auto_runs": global_auto,
        "total_manual_runs": global_manual,
        "auto_threshold_seconds": AUTO_THRESHOLD_SECONDS,
        "states": sorted_states,
    }

    with open(OUTPUT_PATH, "w") as fh:
        json.dump(output, fh, indent=2)
    print(f"\nTally written to: {OUTPUT_PATH}")

    # Print top-15 summary
    print("\nTop states by reduction count:")
    print(f"  {'stateID':>16s}  {'total':>5s} {'auto':>5s} {'manual':>6s}  IPTS")
    for sid, info in list(sorted_states.items())[:15]:
        n_ipts = len(info["ipts"])
        print(f"  {sid}  {info['total_runs']:5d} {info['auto_runs']:5d} {info['manual_runs']:6d}  {n_ipts}")

    # States with only auto-reduced runs (never manually reduced)
    auto_only = sorted(
        [(sid, info) for sid, info in tally.items() if info["manual_runs"] == 0 and info["total_runs"] > 0],
        key=lambda x: x[1]["total_runs"],
        reverse=True,
    )
    if auto_only:
        print(f"\nStates with ONLY auto-reduced runs (0 manual): {len(auto_only)}")
        for sid, info in auto_only:
            print(f"  {sid}  {info['total_runs']:5d} auto runs across {len(info['ipts'])} IPTS")

    # Print states with 0 reductions (from calibration home)
    calib_powder = os.path.join(CALIB_HOME, "Powder")
    if os.path.isdir(calib_powder):
        all_calib_states = {
            d for d in os.listdir(calib_powder)
            if os.path.isdir(os.path.join(calib_powder, d)) and len(d) == 16
        }
        never_reduced = sorted(all_calib_states - set(tally.keys()))
        print(f"\nCalibration states with ZERO reductions: {len(never_reduced)}")
        for sid in never_reduced:
            print(f"  {sid}")


if __name__ == "__main__":
    main()
