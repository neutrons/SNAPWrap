#!/usr/bin/env python
"""Quick smoke-test for validateIndex against suspect states."""

import snapwrap.snapStateMgr as ssm

suspects = [
    "e1512a39893ebc99",
    "22744cf05aaf2a8f",
    "0c66ac0318e26a13",
    "9ea6cc06fe835a1b",
    "fac358b3ffae68af",
    "ca7c742288faf09c",
    "04bd2c53f6bf6754"
]

for sid in suspects:
    for ct in ["difcal", "normcal"]:
        try:
            r = ssm.validateIndex(runNumber=None, stateID=sid, isLite=True, calType=ct)
            ssm.printValidationReport(r)
        except Exception as e:
            print(f"ERROR validating {sid} {ct}: {e}")
        print()
