#!/usr/bin/env python
"""Validate e1512a39893ebc99 after fix."""
import snapwrap.snapStateMgr as ssm
report = ssm.validateIndex(runNumber="68975", stateID="e1512a39893ebc99", calType="difcal")
ssm.printValidationReport(report)
