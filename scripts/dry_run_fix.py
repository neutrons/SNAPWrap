#!/usr/bin/env python
"""Dry-run fixIndex on one example of each failure type."""

import snapwrap.snapStateMgr as ssm

# Type 1: appliesTo mismatch (04bd2c53f6bf6754)
print("=== TYPE 1: appliesTo mismatch ===")
print("State: 04bd2c53f6bf6754")
print()
result = ssm.fixIndex(stateID="04bd2c53f6bf6754", calType="difcal", dryRun=True, autoConfirm=True)
for a in result["actions"]:
    print(a)
print()
print("=" * 72)
print()

# Type 2: orphaned folder (22744cf05aaf2a8f)
print("=== TYPE 2: orphaned folder ===")
print("State: 22744cf05aaf2a8f")
print()
result = ssm.fixIndex(stateID="22744cf05aaf2a8f", calType="difcal", dryRun=True, autoConfirm=True)
for a in result["actions"]:
    print(a)
print()
print("=" * 72)
print()

# Type 3: wrong filename / corrupt data (03c116b0df7506d9)
print("=== TYPE 3: wrong filename (corrupt data) ===")
print("State: 03c116b0df7506d9")
print()
result = ssm.fixIndex(stateID="03c116b0df7506d9", calType="difcal", dryRun=True, autoConfirm=True)
for a in result["actions"]:
    print(a)
