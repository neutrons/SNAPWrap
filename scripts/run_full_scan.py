#!/usr/bin/env python
"""Scan ALL states in the calibration home and report validation status."""

import snapwrap.snapStateMgr as ssm
import os
import re
import json

home = ssm.SNAPHome()
powder = home.powder

print(f"Calibration home: {home.calib}")
print(f"Powder home:      {powder}")
print()

# Get all state folders
states = ssm.availableStates()
print(f"Total states found: {len(states)}")
print("=" * 80)

results = {"difcal": {"pass": [], "fail": [], "no_index": [], "legacy": []},
           "normcal": {"pass": [], "fail": [], "no_index": [], "legacy": []}}
fail_details = {}  # (stateID, calType) -> list of issue strings
fail_reports = {}  # (stateID, calType) -> raw validation report

for i, sid in enumerate(sorted(states)):
    for ct in ["difcal", "normcal"]:
        try:
            r = ssm.validateIndex(runNumber=None, stateID=sid, isLite=True, calType=ct)
            if r["ok"]:
                # Check if it's a "no index" pass (normcal only)
                has_no_index = any("not been normalized" in iss for iss in r.get("issues", []))
                if has_no_index:
                    results[ct]["no_index"].append(sid)
                    continue

                # Check if any entries have legacy-format notes
                has_legacy = False
                for er in r.get("entries", []):
                    if any("legacy" in iss.lower() for iss in er.get("issues", [])):
                        has_legacy = True
                        break
                if has_legacy:
                    results[ct]["legacy"].append(sid)
                    ssm.printValidationReport(r)
                    print()
                else:
                    results[ct]["pass"].append(sid)
            else:
                results[ct]["fail"].append(sid)
                # Collect failure reasons for summary
                details = list(r.get("issues", []))
                for er in r.get("entries", []):
                    for iss in er.get("issues", []):
                        if "legacy" not in iss.lower():
                            details.append(f"v{er.get('version','?')}: {iss}")
                fail_details[(sid, ct)] = details
                fail_reports[(sid, ct)] = r
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
    n_legacy = len(results[ct]["legacy"])
    pct_pass = 100.0 * n_pass / total if total else 0
    pct_fail = 100.0 * n_fail / total if total else 0
    pct_noidx = 100.0 * n_noidx / total if total else 0
    pct_legacy = 100.0 * n_legacy / total if total else 0

    print(f"\n  {ct}:")
    print(f"    PASS:             {n_pass:4d}  ({pct_pass:5.1f}%)")
    print(f"    PASS (legacy):    {n_legacy:4d}  ({pct_legacy:5.1f}%)  [older record format – missing indexEntry]")
    if ct == "normcal":
        print(f"    PASS (no index):  {n_noidx:4d}  ({pct_noidx:5.1f}%)")
    print(f"    FAIL:             {n_fail:4d}  ({pct_fail:5.1f}%)")

    if results[ct]["legacy"]:
        print(f"\n    Legacy-format states:")
        for sid in results[ct]["legacy"]:
            sd = ssm.pullStateDict(sid)
            label = ssm.autoStateName(sd) if sd else "(unable to read state)"
            print(f"      {sid}  {label}")

    if results[ct]["fail"]:
        print(f"\n    Failed states:")
        for sid in results[ct]["fail"]:
            sd = ssm.pullStateDict(sid)
            label = ssm.autoStateName(sd) if sd else "(unable to read state)"
            print(f"      {sid}  {label}")
            for detail in fail_details.get((sid, ct), []):
                print(f"        → {detail}")

            # Check failing entries for propagation origin
            rpt = fail_reports.get((sid, ct))
            if rpt:
                subFolder = "diffraction" if ct == "difcal" else "normalization"
                jsonName = "CalibrationIndex.json" if ct == "difcal" else "NormalizationIndex.json"
                idxPath = os.path.join(powder, sid, "lite", subFolder, jsonName)
                try:
                    with open(idxPath, "r") as fh:
                        indexEntries = json.load(fh)
                    # identify which versions failed
                    failed_versions = set()
                    for er in rpt.get("entries", []):
                        if er.get("issues"):
                            failed_versions.add(er.get("version"))
                    # also check top-level issues for orphaned folders
                    for iss in rpt.get("issues", []):
                        m = re.search(r"Extra version folders.*?(\[.*?\])", iss)
                        if m:
                            for vf in re.findall(r"v_(\d+)", m.group(1)):
                                failed_versions.add(int(vf))
                    # scan entries for propagation comments
                    prop_re = re.compile(r"\(copied from run:(\S+)\s+version:(\S+)\)")
                    for ie in indexEntries:
                        v = ie.get("version")
                        comment = ie.get("comments", "")
                        pm = prop_re.match(comment)
                        if pm:
                            donor_run = pm.group(1)
                            donor_ver = pm.group(2)
                            marker = " ← FAILING" if v in failed_versions else ""
                            print(f"        ↳ v{v} propagated from run:{donor_run} ver:{donor_ver}{marker}")
                except Exception:
                    pass

print()
