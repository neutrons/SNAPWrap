#!/usr/bin/env python
"""Scan ALL states in the calibration home and report validation status."""

import snapwrap.snapStateMgr as ssm
import os

home = ssm.SNAPHome()
powder = home.powder

print(f"Calibration home: {home.calib}")
print(f"Powder home:      {powder}")
print()

# Get all state folders
states = ssm.availableStates()
print(f"Total states found: {len(states)}")
print("=" * 80)

results = {"difcal": {"pass": [], "fail": [], "no_index": []},
           "normcal": {"pass": [], "fail": [], "no_index": []}}

for i, sid in enumerate(sorted(states)):
    for ct in ["difcal", "normcal"]:
        try:
            r = ssm.validateIndex(runNumber=None, stateID=sid, isLite=True, calType=ct)
            if r["ok"]:
                # Check if it's a "no index" pass (normcal only)
                has_no_index = any("not been normalized" in iss for iss in r.get("issues", []))
                if has_no_index:
                    results[ct]["no_index"].append(sid)
                else:
                    results[ct]["pass"].append(sid)
            else:
                results[ct]["fail"].append(sid)
                ssm.printValidationReport(r)
                print()
        except Exception as e:
            results[ct]["fail"].append(sid)
            print(f"ERROR  state={sid}  calType={ct}: {e}")
            print()

# Summary
print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

for ct in ["difcal", "normcal"]:
    total = len(states)
    n_pass = len(results[ct]["pass"])
    n_fail = len(results[ct]["fail"])
    n_noidx = len(results[ct]["no_index"])
    pct_pass = 100.0 * n_pass / total if total else 0
    pct_fail = 100.0 * n_fail / total if total else 0
    pct_noidx = 100.0 * n_noidx / total if total else 0

    print(f"\n  {ct}:")
    print(f"    PASS:             {n_pass:4d}  ({pct_pass:5.1f}%)")
    if ct == "normcal":
        print(f"    PASS (no index):  {n_noidx:4d}  ({pct_noidx:5.1f}%)")
    print(f"    FAIL:             {n_fail:4d}  ({pct_fail:5.1f}%)")

    if results[ct]["fail"]:
        print(f"\n    Failed states:")
        for sid in results[ct]["fail"]:
            print(f"      {sid}")

print()
