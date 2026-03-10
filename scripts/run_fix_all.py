#!/usr/bin/env python
"""Run fixIndex on all 16 failing states (for real, not dry-run).

Groups:
  - 1 appliesTo mismatch
  - 3 orphaned folders
  - 12 wrong-run-number (corrupt data files)
"""

import snapwrap.snapStateMgr as ssm

# All 16 failing states from the post-legacy-delete scan
failing_states = [
    # Type 1: appliesTo mismatch
    "04bd2c53f6bf6754",
    # Type 2: orphaned folders (v_0001 with no index entry)
    "22744cf05aaf2a8f",
    "e1512a39893ebc99",
    "fac358b3ffae68af",
    # Type 3: wrong run number in data files (12 states)
    "03c116b0df7506d9",
    "0c66ac0318e26a13",
    "0f78eb70a1c029b7",
    "17fcca13ece67241",
    "19b4f7d9436b3d40",
    "6e421ac5d65ee355",
    "702ba297516db7bf",
    "7a68989468eb04f0",
    "9ea6cc06fe835a1b",
    "c073719d9101e8f2",
    "d3e0c2862e8d3ad7",
    "f4c4c8cd3e9fdfd4",
]

passed = []
failed = []

for i, sid in enumerate(failing_states, 1):
    print(f"\n{'='*72}")
    print(f"[{i}/{len(failing_states)}]  Fixing state: {sid}")
    print(f"{'='*72}")

    try:
        result = ssm.fixIndex(stateID=sid, calType="difcal",
                              dryRun=False, autoConfirm=True)
        for a in result["actions"]:
            print(a)

        # Post-fix validation
        print(f"\n--- Post-fix validation ---")
        report = ssm.validateIndex(stateID=sid, calType="difcal")
        ssm.printValidationReport(report)

        if report["ok"]:
            passed.append(sid)
        else:
            failed.append(sid)

    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        failed.append(sid)

print(f"\n{'='*72}")
print(f"COMPLETE")
print(f"{'='*72}")
print(f"  Fixed & validated: {len(passed)}/{len(failing_states)}")
print(f"  Still failing:     {len(failed)}/{len(failing_states)}")
if failed:
    print(f"  Failed states: {failed}")
