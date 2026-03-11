#!/usr/bin/env python
"""Test fixIndex in dry-run mode against known-corrupt states."""

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
    print(f"DRY RUN: fixIndex for {sid} difcal")
    print("=" * 72)
    result = ssm.fixIndex(stateID=sid, calType="difcal", dryRun=True)
    for a in result["actions"]:
        print(a)
    print()
