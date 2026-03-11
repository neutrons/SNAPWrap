#!/usr/bin/env python
"""Fix e1512a39893ebc99 in test env."""
import snapwrap.snapStateMgr as ssm
ssm.fixIndex(stateID="e1512a39893ebc99", calType="difcal", dryRun=False, autoConfirm=True)
