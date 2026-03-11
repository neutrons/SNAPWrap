#!/usr/bin/env python
"""Run fixIndex interactively against all suspect states (test calibration home)."""

import snapwrap.snapStateMgr as ssm

suspects = [
    "e1512a39893ebc99",
    "22744cf05aaf2a8f",
    "0c66ac0318e26a13",
    "9ea6cc06fe835a1b",
    "fac358b3ffae68af",
    "ca7c742288faf09c",
    "04bd2c53f6bf6754",
]

for sid in suspects:
    print("=" * 72)
    print(f"fixIndex: {sid}  difcal")
    print("=" * 72)
    try:
        result = ssm.fixIndex(stateID=sid, calType="difcal", dryRun=False, autoConfirm=False)
        for a in result["actions"]:
            print(a)
    except Exception as e:
        print(f"ERROR: {e}")
    print()

# Final validation pass
print("\n" + "=" * 72)
print("FINAL VALIDATION OF ALL STATES")
print("=" * 72 + "\n")
for sid in suspects:
    for ct in ["difcal", "normcal"]:
        try:
            r = ssm.validateIndex(runNumber=None, stateID=sid, isLite=True, calType=ct)
            ssm.printValidationReport(r)
        except Exception as e:
            print(f"ERROR validating {sid} {ct}: {e}")
        print()
