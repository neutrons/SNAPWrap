"""wrap supplies ``cycleID`` to SNAPRed's record getters only when SNAPRed asks for it.

SNAPRed after PR #678 made ``cycleID`` a required argument of
``DataFactoryService.getCalibrationRecord`` and ``getNormalizationRecord``, and
raises unless it equals SNAPRed's own ``getCycle(runId).cycleID``. SNAPRed 2.3.1
has no such parameter. ``reduce`` calls both getters, so without this every
reduction against SNAPRed ``next`` failed with a pydantic ``missing_argument``
before it started. Found by the snapwrap2.4 CIS harness.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

from snapred.backend.data.DataFactoryService import DataFactoryService

from snapwrap.utils import _recordCycleArgs


class _Pre678:
    """SNAPRed 2.3.1 shape: no cycleID, and no getCycle to call."""

    def getCalibrationRecord(self, runId, useLiteMode, version=None, state=None):
        pass


class _Post678:
    """SNAPRed next shape: cycleID required, validated against getCycle."""

    def __init__(self, cycleID):
        self.cycleID = cycleID
        self.asked = []

    def getCalibrationRecord(self, runId, useLiteMode, cycleID, version=None, state=None):
        pass

    def getCycle(self, runId):
        self.asked.append(runId)
        return SimpleNamespace(cycleID=self.cycleID)


def test_nothing_extra_for_snapred_without_cycleID():
    assert _recordCycleArgs(_Pre678(), 68979) == {}


def test_cycleID_comes_from_snapreds_own_lookup():
    """It must be SNAPRed's value, or SNAPRed's equality check raises."""
    dfs = _Post678("2026-A")
    assert _recordCycleArgs(dfs, 68979) == {"cycleID": "2026-A"}
    assert dfs.asked == ["68979"]  # run numbers reach SNAPRed as strings


def test_no_cycle_sentinel_is_passed_through():
    """A run in no cycle still gets SNAPRed's sentinel, which then matches."""
    assert _recordCycleArgs(_Post678("noCycle"), 66500) == {"cycleID": "noCycle"}


def test_installed_snapred_getters_agree():
    """wrap inspects only getCalibrationRecord; the normalization getter must match it."""
    params = lambda name: inspect.signature(getattr(DataFactoryService, name)).parameters
    assert ("cycleID" in params("getCalibrationRecord")) == ("cycleID" in params("getNormalizationRecord"))
