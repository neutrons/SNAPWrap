#!/usr/bin/env python
"""Identify transient calibration states that can be safely deleted.

Criteria for a transient state:
  a) Only the default v0 calibration exists (no real calibrations) AND
     no normalization index exists.
  b) State has never been used to **manually** reduce data (0 manual runs
     in reductionTally.json).  Auto-reductions are discounted because the
     autoreduction service creates junk output for uncalibrated states.
  c) State has existed for at least one full cycle (i.e. was created before
     the start of the current cycle).

Usage
-----
    python scripts/identify_transient_states.py              # list only
    python scripts/identify_transient_states.py --delete     # delete after confirmation
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime


CALIB_HOME = os.environ.get("CALIB_HOME", "/SNS/SNAP/shared/Calibration")
POWDER_HOME = os.path.join(CALIB_HOME, "Powder")
TALLY_PATH = os.path.join(CALIB_HOME, "reductionTally.json")

# Current cycle start — states created before this are "at least one cycle old"
# Update this when a new cycle begins.
CURRENT_CYCLE_START = datetime(2026, 1, 1)  # 2026-A started Jan 2026

# Abbreviated PV names for human-readable state labels
_PV_ABBREV = {
    "det_arc1": "arc1",
    "det_arc2": "arc2",
    "BL3:Chop:Skf1:WavelengthUserReq": "wav",
    "BL3:Det:TH:BL:Frequency": "freq",
    "BL3:Mot:OpticsPos:Pos": "pos",
    "BL3:Mot:OpticsPos:ExitSlit": "slit",
    # legacy key names
    "vdet_arc1": "arc1",
    "vdet_arc2": "arc2",
    "WavelengthUserReq": "wav",
    "Frequency": "freq",
    "Pos": "pos",
    "slit": "slit",
}


def pull_state_label(state_id):
    """Return a human-readable label for *state_id* from its v0 CalibrationParameters.

    Mirrors the logic of ``pullStateDict`` + ``autoStateName`` in snapStateMgr
    but reads files directly (no mantid dependency).
    """
    params_path = os.path.join(
        POWDER_HOME, state_id, "lite", "diffraction", "v_0000", "CalibrationParameters.json"
    )
    try:
        with open(params_path, "r") as fh:
            params = json.load(fh)
    except Exception:
        return "(unable to read state)"

    det = params.get("instrumentState", {}).get("detectorState", {})

    # SNAPRed ≥ v2.0.0 format: PVs dict
    if "PVs" in det:
        pvs = dict(det["PVs"])
        pvs.pop("det_lin1", None)
        pvs.pop("det_lin2", None)
        if "BL3:Det:TH:BL:Frequency" in pvs:
            pvs["BL3:Det:TH:BL:Frequency"] = float(pvs["BL3:Det:TH:BL:Frequency"])
    else:
        # v1.3.0 format
        pvs = {
            "det_arc1": float(round(det["arc"][0] * 2) / 2),
            "det_arc2": float(round(det["arc"][1] * 2) / 2),
            "BL3:Chop:Skf1:WavelengthUserReq": float(round(det["wav"], 1)),
            "BL3:Det:TH:BL:Frequency": float(round(det["freq"])),
            "BL3:Mot:OpticsPos:Pos": int(det["guideStat"]),
        }

    parts = []
    for key, val in pvs.items():
        abbr = _PV_ABBREV.get(key, key)
        if abbr.startswith("arc"):
            parts.append(f"{abbr}:{val:6.1f}")
        else:
            parts.append(f"{abbr}:{val}")
    return "::".join(parts)


def oldest_file_mtime(directory):
    """Return the earliest mtime of any file under *directory*."""
    oldest = None
    for root, dirs, files in os.walk(directory):
        for f in files:
            fp = os.path.join(root, f)
            try:
                mt = os.path.getmtime(fp)
                if oldest is None or mt < oldest:
                    oldest = mt
            except OSError:
                pass
    return oldest


def main():
    parser = argparse.ArgumentParser(description="Identify (and optionally delete) transient calibration states.")
    parser.add_argument("--delete", action="store_true", help="Delete identified transient states after confirmation.")
    args = parser.parse_args()

    # Load reduction tally
    if not os.path.isfile(TALLY_PATH):
        print(f"ERROR: Reduction tally not found at {TALLY_PATH}")
        print("Run build_reduction_tally.py first.")
        sys.exit(1)

    with open(TALLY_PATH, "r") as fh:
        tally = json.load(fh)

    reduced_states = set(tally.get("states", {}).keys())

    # Enumerate all calibration states
    all_states = sorted(
        d for d in os.listdir(POWDER_HOME)
        if os.path.isdir(os.path.join(POWDER_HOME, d)) and len(d) == 16
    )

    print(f"Calibration home: {CALIB_HOME}")
    print(f"Total states:     {len(all_states)}")
    print(f"Tally generated:  {tally.get('generated', '?')}")
    print(f"Current cycle start: {CURRENT_CYCLE_START.date()}")
    print()

    transient = []
    skipped_reasons = {}

    for sid in all_states:
        state_dir = os.path.join(POWDER_HOME, sid)
        reasons_to_skip = []

        # --- Criterion (a): only default v0 difcal, no normcal ---
        difcal_index_path = os.path.join(state_dir, "lite", "diffraction", "CalibrationIndex.json")
        normcal_index_path = os.path.join(state_dir, "lite", "normalization", "NormalizationIndex.json")

        has_real_difcal = False
        if os.path.isfile(difcal_index_path):
            try:
                with open(difcal_index_path, "r") as fh:
                    idx = json.load(fh)
                if len(idx) > 1:
                    has_real_difcal = True
            except Exception:
                pass

        has_normcal = os.path.isfile(normcal_index_path)

        if has_real_difcal or has_normcal:
            reasons_to_skip.append("has calibrations" if has_real_difcal else "has normcal")

        # --- Criterion (b): never manually reduced ---
        if sid in reduced_states:
            state_info = tally["states"][sid]
            manual_runs = state_info.get("manual_runs", state_info["total_runs"])
            if manual_runs > 0:
                reasons_to_skip.append(f"manually reduced ({manual_runs} manual runs)")
            # else: only auto-reduced — does NOT protect the state

        # --- Criterion (c): at least one cycle old ---
        oldest_mt = oldest_file_mtime(state_dir)
        if oldest_mt is not None:
            created = datetime.fromtimestamp(oldest_mt)
            if created >= CURRENT_CYCLE_START:
                reasons_to_skip.append(f"created this cycle ({created.date()})")
        else:
            reasons_to_skip.append("cannot determine creation date")

        if reasons_to_skip:
            skipped_reasons[sid] = reasons_to_skip
        else:
            # Compute folder size for display
            total_size = 0
            for root, dirs, files in os.walk(state_dir):
                for f in files:
                    try:
                        total_size += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
            created_str = datetime.fromtimestamp(oldest_mt).strftime("%Y-%m-%d") if oldest_mt else "?"
            auto_runs = 0
            if sid in reduced_states:
                auto_runs = tally["states"][sid].get("auto_runs", 0)
            transient.append({
                "stateID": sid,
                "label": pull_state_label(sid),
                "created": created_str,
                "size_mb": total_size / (1024 * 1024),
                "auto_runs": auto_runs,
            })

    # Report
    print(f"States meeting ALL transient criteria: {len(transient)}")
    print()

    if transient:
        total_mb = 0
        for t in transient:
            auto_note = f"  auto_runs={t['auto_runs']}" if t["auto_runs"] > 0 else ""
            print(f"  {t['stateID']}  created={t['created']}  size={t['size_mb']:.1f} MB{auto_note}")
            print(f"    {t['label']}")
            total_mb += t["size_mb"]
        print(f"\n  Total reclaimable: {total_mb:.1f} MB")
    else:
        print("  (none)")

    # Show a few examples of states that were close but didn't qualify
    print(f"\nStates that did NOT qualify ({len(skipped_reasons)}):")
    # Show states that failed on only one criterion (closest to transient)
    near_misses = [(sid, reasons) for sid, reasons in skipped_reasons.items() if len(reasons) == 1]
    if near_misses:
        print(f"  Near-misses (failed on one criterion only): {len(near_misses)}")
        for sid, reasons in sorted(near_misses):
            label = pull_state_label(sid)
            print(f"    {sid}: {reasons[0]}")
            print(f"      {label}")

    # Delete if requested
    if args.delete and transient:
        print(f"\n{'='*60}")
        print(f"About to DELETE {len(transient)} state folders.")
        print(f"This will remove all calibration data for these states.")
        answer = input("Proceed? [y/N]: ").strip().lower()
        if answer == "y":
            for t in transient:
                path = os.path.join(POWDER_HOME, t["stateID"])
                print(f"  Deleting {path} ...")
                shutil.rmtree(path)
                print(f"    deleted.")
            print("Done.")
        else:
            print("Aborted.")


if __name__ == "__main__":
    main()
