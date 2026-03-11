#!/usr/bin/env python
"""Validate all states in test calibration home after propagateDifcal."""
import os
import snapwrap.snapStateMgr as ssm

home = ssm.SNAPHome()
calibHome = home.calib
powderHome = home.powder

print(f"Calibration home: {calibHome}")
print(f"Powder home:      {powderHome}")
print()

states = sorted([d for d in os.listdir(powderHome)
                 if os.path.isdir(os.path.join(powderHome, d))
                 and not d.startswith(".")])

print(f"Found {len(states)} states\n")

results = {"difcal": {"PASS": [], "FAIL": []}, "normcal": {"PASS": [], "FAIL": []}}

for stateID in states:
    for calType in ["difcal", "normcal"]:
        # figure out a run number from the index
        subdir = "diffraction" if calType == "difcal" else "normalization"
        indexPath = os.path.join(powderHome, stateID, "lite", subdir, "CalibrationIndex.json")
        if not os.path.exists(indexPath):
            print(f"SKIP  state={stateID}  calType={calType}  (no index file)")
            continue
        import json
        with open(indexPath) as f:
            idx = json.load(f)
        if not idx:
            print(f"SKIP  state={stateID}  calType={calType}  (empty index)")
            continue
        runNumber = idx[0].get("runNumber", None)
        if runNumber is None:
            print(f"SKIP  state={stateID}  calType={calType}  (no runNumber in index)")
            continue

        report = ssm.validateIndex(runNumber=str(runNumber), stateID=stateID, calType=calType)
        ssm.printValidationReport(report)
        status = "PASS" if report["ok"] else "FAIL"
        results[calType][status].append(stateID)

print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
for calType in ["difcal", "normcal"]:
    total = len(results[calType]["PASS"]) + len(results[calType]["FAIL"])
    if total == 0:
        continue
    nfail = len(results[calType]["FAIL"])
    print(f"\n{calType}: {nfail}/{total} FAIL  ({100*nfail/total:.1f}%)")
    if results[calType]["FAIL"]:
        for s in results[calType]["FAIL"]:
            print(f"  FAIL: {s}")
