"""Tests for cycle-aware calibration status in snapwrap.snapStateMgr.

These tests exercise:
1. Annotation of calibration index entries with ``cycleID``.
2. The new ``runCycleID`` key in the returned calStatus dictionary.
3. The cycle-match criterion: ``runIsCalibrated`` is ``False`` when the
   calibration's cycleID differs from the input run's cycleID, even if
   the ``appliesTo`` expression would otherwise be satisfied.
4. ``matchingCalibrationIndex`` with an optional *requiredCycleID*
   parameter.
5. The ``statusDetail`` key explaining *why* a calibration is or isn't valid.

Heavy mocking is used so that no real disk state or SNAPRed services are
needed.
"""

import json
import io
import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

import snapwrap.cycleDates as cd
import snapwrap.snapStateMgr as ssm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _resolution_follows_cycle_mock(monkeypatch):
    """Make ``resolve_cycle_for_run`` follow whatever ``get_cycle_for_run`` is.

    Gating now goes through the stopDate-aware ``resolve_cycle_for_run`` rather
    than the open-ended ``get_cycle_for_run``.  These tests mock the latter to
    control which cycle a run belongs to, so resolution is redirected to read
    it *at call time* -- that way it picks up each test's mock without every
    test having to patch two functions.

    A mocked cycle of ``None`` becomes UNDECIDED, which is the fail-closed
    outcome: the gate refuses rather than waving the run through.
    """

    def _resolve(runNumber, *args, **kwargs):
        cycleID = ssm.get_cycle_for_run(runNumber)
        if cycleID is None:
            return cd.CycleResolution(None, cd.UNDECIDED, "test: cycle undecided")
        return cd.CycleResolution(cycleID, cd.IN_CYCLE, "test: in cycle")

    monkeypatch.setattr(ssm, "resolve_cycle_for_run", _resolve)

def _make_index_entry(
    version: int,
    runNumber: str,
    appliesTo: str,
    timestamp: str,
    useLiteMode: bool = True,
    comments: str = "",
    author: str = "test",
):
    """Return a dict that looks like a CalibrationIndex entry."""
    return {
        "version": version,
        "runNumber": runNumber,
        "useLiteMode": useLiteMode,
        "appliesTo": appliesTo,
        "timestamp": timestamp,
        "comments": comments,
        "author": author,
    }


def _json_file_factory(data):
    """Return a *callable* that produces a fresh StringIO context-manager
    containing *data* serialised as JSON every time it is called.

    Use with ``patch("builtins.open", side_effect=_json_file_factory(data))``.
    Each call to ``open()`` inside the production code will get a brand-new
    StringIO, preventing 'I/O operation on closed file' errors when
    ``checkCalibrationStatus`` opens more than one file.
    """
    content = json.dumps(data)

    def _factory(*args, **kwargs):
        sio = io.StringIO(content)
        sio.__enter__ = lambda s: s
        sio.__exit__ = lambda s, *a: None
        return sio

    return _factory


# ---------------------------------------------------------------------------
# matchingCalibrationIndex
# ---------------------------------------------------------------------------

class TestMatchingCalibrationIndex:
    """Verify existing + new cycle-filter behaviour of matchingCalibrationIndex."""

    def _entries(self):
        return [
            _make_index_entry(1, "50000", ">=50000", "2024-01-15T10:00:00.000"),
            _make_index_entry(2, "60000", ">=60000", "2024-06-15T10:00:00.000"),
            _make_index_entry(3, "70000", ">=70000", "2025-01-15T10:00:00.000"),
        ]

    def test_match_first_entry(self):
        idx = ssm.matchingCalibrationIndex(self._entries(), 55000)
        assert idx == 0

    def test_match_second_entry(self):
        idx = ssm.matchingCalibrationIndex(self._entries(), 65000)
        assert idx == 1

    def test_match_third_entry(self):
        idx = ssm.matchingCalibrationIndex(self._entries(), 75000)
        assert idx == 2

    def test_no_match(self):
        idx = ssm.matchingCalibrationIndex(self._entries(), 40000)
        assert idx is None

    def test_cycle_filter_skips_wrong_cycle(self):
        entries = self._entries()
        entries[0]["cycleID"] = "2024-A"
        entries[1]["cycleID"] = "2024-B"
        entries[2]["cycleID"] = "2025-A"
        idx = ssm.matchingCalibrationIndex(entries, 75000, requiredCycleID="2024-B")
        assert idx == 1

    def test_cycle_filter_no_match_when_no_cycle_matches(self):
        entries = self._entries()
        entries[0]["cycleID"] = "2024-A"
        entries[1]["cycleID"] = "2024-B"
        entries[2]["cycleID"] = "2025-A"
        idx = ssm.matchingCalibrationIndex(entries, 75000, requiredCycleID="2023-B")
        assert idx is None

    def test_cycle_filter_none_means_no_restriction(self):
        entries = self._entries()
        entries[0]["cycleID"] = "2024-A"
        entries[1]["cycleID"] = "2024-B"
        entries[2]["cycleID"] = "2025-A"
        idx = ssm.matchingCalibrationIndex(entries, 75000, requiredCycleID=None)
        assert idx == 2


# ---------------------------------------------------------------------------
# checkCalibrationStatus -- cycle annotation & runCycleID
# ---------------------------------------------------------------------------

class TestCheckCalibrationStatusCycleAnnotation:

    def _make_difcal_index(self):
        default = _make_index_entry(0, "50000", ">=0", "2024-01-01T00:00:00.000")
        v1 = _make_index_entry(1, "55000", ">=50000", "2024-06-01T10:00:00.000")
        v2 = _make_index_entry(2, "62000", ">=60000", "2025-01-01T10:00:00.000")
        return [default, v1, v2]

    @patch("snapwrap.snapStateMgr.get_cycle_for_run")
    @patch("snapwrap.snapStateMgr.checkStateExists", return_value=True)
    @patch("snapwrap.snapStateMgr.stateDef", return_value=["abc123", {}])
    def test_index_entries_annotated_with_cycleID(
        self, mock_stateDef, mock_stateExists, mock_gcfr
    ):
        index_data = self._make_difcal_index()

        def cycle_side_effect(rn):
            rn = int(rn)
            if rn < 62000:
                return "2024-A"
            return "2024-B"

        mock_gcfr.side_effect = cycle_side_effect

        with patch("builtins.open", side_effect=_json_file_factory(index_data)), \
             patch("os.path.isfile", return_value=True):
            result = ssm.checkCalibrationStatus(
                runNumber=63000, stateID=None, isLite=True, calType="difcal"
            )

        for entry in result["calibIndexList"]:
            assert "cycleID" in entry, f"Entry v{entry['version']} missing cycleID"

    @patch("snapwrap.snapStateMgr.get_cycle_for_run")
    @patch("snapwrap.snapStateMgr.checkStateExists", return_value=True)
    @patch("snapwrap.snapStateMgr.stateDef", return_value=["abc123", {}])
    def test_runCycleID_present(
        self, mock_stateDef, mock_stateExists, mock_gcfr
    ):
        index_data = self._make_difcal_index()
        mock_gcfr.return_value = "2024-B"

        with patch("builtins.open", side_effect=_json_file_factory(index_data)), \
             patch("os.path.isfile", return_value=True):
            result = ssm.checkCalibrationStatus(
                runNumber=63000, stateID=None, isLite=True, calType="difcal"
            )

        assert "runCycleID" in result
        assert result["runCycleID"] == "2024-B"


# ---------------------------------------------------------------------------
# checkCalibrationStatus -- cycle validity criterion
# ---------------------------------------------------------------------------

class TestCheckCalibrationStatusCycleValidity:

    def _make_difcal_index(self):
        default = _make_index_entry(0, "50000", ">=0", "2024-01-01T00:00:00.000")
        v1 = _make_index_entry(1, "55000", ">=50000", "2024-03-01T10:00:00.000")
        return [default, v1]

    @patch("snapwrap.snapStateMgr.get_cycle_for_run")
    @patch("snapwrap.snapStateMgr.checkStateExists", return_value=True)
    @patch("snapwrap.snapStateMgr.stateDef", return_value=["abc123", {}])
    def test_same_cycle_is_calibrated(
        self, mock_stateDef, mock_stateExists, mock_gcfr
    ):
        index_data = self._make_difcal_index()
        mock_gcfr.return_value = "2024-A"

        with patch("builtins.open", side_effect=_json_file_factory(index_data)), \
             patch("os.path.isfile", return_value=True):
            result = ssm.checkCalibrationStatus(
                runNumber=56000, stateID=None, isLite=True, calType="difcal"
            )

        assert result["runIsCalibrated"] is True
        assert result["statusDetail"] == "valid calibration found"

    @patch("snapwrap.snapStateMgr.get_cycle_for_run")
    @patch("snapwrap.snapStateMgr.checkStateExists", return_value=True)
    @patch("snapwrap.snapStateMgr.stateDef", return_value=["abc123", {}])
    def test_cross_cycle_not_calibrated(
        self, mock_stateDef, mock_stateExists, mock_gcfr
    ):
        index_data = self._make_difcal_index()

        def cycle_side_effect(rn):
            rn = int(rn)
            if rn < 60000:
                return "2024-A"
            return "2024-B"

        mock_gcfr.side_effect = cycle_side_effect

        with patch("builtins.open", side_effect=_json_file_factory(index_data)), \
             patch("os.path.isfile", return_value=True):
            result = ssm.checkCalibrationStatus(
                runNumber=62000, stateID=None, isLite=True, calType="difcal"
            )

        assert result["runIsCalibrated"] is False
        assert "out of cycle" in result["statusDetail"]

    @patch("snapwrap.snapStateMgr.get_cycle_for_run")
    @patch("snapwrap.snapStateMgr.checkStateExists", return_value=True)
    @patch("snapwrap.snapStateMgr.stateDef", return_value=["abc123", {}])
    def test_cross_cycle_falls_back_to_same_cycle_entry(
        self, mock_stateDef, mock_stateExists, mock_gcfr
    ):
        default = _make_index_entry(0, "50000", ">=0", "2024-01-01T00:00:00.000")
        v1 = _make_index_entry(1, "55000", ">=50000", "2024-03-01T10:00:00.000")
        v2 = _make_index_entry(2, "62000", ">=50000", "2024-09-01T10:00:00.000")
        index_data = [default, v1, v2]

        def cycle_side_effect(rn):
            rn = int(rn)
            if rn < 60000:
                return "2024-A"
            return "2024-B"

        mock_gcfr.side_effect = cycle_side_effect

        with patch("builtins.open", side_effect=_json_file_factory(index_data)), \
             patch("os.path.isfile", return_value=True):
            result = ssm.checkCalibrationStatus(
                runNumber=56000, stateID=None, isLite=True, calType="difcal"
            )

        assert result["runIsCalibrated"] is True
        assert result["latestValidCalibrationDict"]["version"] == 1
        assert result["statusDetail"] == "valid calibration found"

    @patch("snapwrap.snapStateMgr.get_cycle_for_run")
    @patch("snapwrap.snapStateMgr.checkStateExists", return_value=True)
    @patch("snapwrap.snapStateMgr.stateDef", return_value=["abc123", {}])
    def test_runNumber_none_skips_cycle_check(
        self, mock_stateDef, mock_stateExists, mock_gcfr
    ):
        default = _make_index_entry(0, "50000", ">=0", "2024-01-01T00:00:00.000")
        v1 = _make_index_entry(1, "55000", ">=50000", "2024-03-01T10:00:00.000")
        index_data = [default, v1]
        mock_gcfr.return_value = "2024-A"

        with patch("builtins.open", side_effect=_json_file_factory(index_data)), \
             patch("os.path.isfile", return_value=True):
            result = ssm.checkCalibrationStatus(
                runNumber=None, stateID="abc123", isLite=True, calType="difcal"
            )

        assert result.get("runCycleID") is None
        for entry in result["calibIndexList"]:
            assert "cycleID" in entry
        assert result["statusDetail"] == "no run number provided; general state info only"

    @patch("snapwrap.snapStateMgr.get_cycle_for_run")
    @patch("snapwrap.snapStateMgr.checkStateExists", return_value=True)
    @patch("snapwrap.snapStateMgr.stateDef", return_value=["abc123", {}])
    def test_unresolvable_cycle_fails_closed(
        self, mock_stateDef, mock_stateExists, mock_gcfr
    ):
        """A run whose cycle cannot be established must NOT be calibrated.

        This inverts the previous behaviour, where an unresolvable cycle
        disabled the cycle filter entirely -- so the case we were least sure
        about was the one that got waved through.  Per the 2026-08-05 decision
        (MG), using an out-of-cycle calibration requires an explicit opt-in, and
        "cycle undecided" is a refusal rather than a free pass.
        """
        default = _make_index_entry(0, "50000", ">=0", "2024-01-01T00:00:00.000")
        v1 = _make_index_entry(1, "55000", ">=50000", "2024-03-01T10:00:00.000")
        index_data = [default, v1]

        def cycle_side_effect(rn):
            rn = int(rn)
            if rn == 56000:
                return None
            return "2024-A"

        mock_gcfr.side_effect = cycle_side_effect

        with patch("builtins.open", side_effect=_json_file_factory(index_data)), \
             patch("os.path.isfile", return_value=True):
            result = ssm.checkCalibrationStatus(
                runNumber=56000, stateID=None, isLite=True, calType="difcal"
            )

        assert result["runIsCalibrated"] is False
        assert "cycle could not be established" in result["statusDetail"]
        # the message must point at the way out
        assert "requireSameCycle=False" in result["statusDetail"]

    @patch("snapwrap.snapStateMgr.get_cycle_for_run")
    @patch("snapwrap.snapStateMgr.checkStateExists", return_value=True)
    @patch("snapwrap.snapStateMgr.stateDef", return_value=["abc123", {}])
    def test_unresolvable_cycle_overridable(
        self, mock_stateDef, mock_stateExists, mock_gcfr
    ):
        """requireSameCycle=False is the explicit opt-in that restores access."""
        default = _make_index_entry(0, "50000", ">=0", "2024-01-01T00:00:00.000")
        v1 = _make_index_entry(1, "55000", ">=50000", "2024-03-01T10:00:00.000")
        index_data = [default, v1]

        mock_gcfr.side_effect = lambda rn: None if int(rn) == 56000 else "2024-A"

        with patch("builtins.open", side_effect=_json_file_factory(index_data)), \
             patch("os.path.isfile", return_value=True):
            result = ssm.checkCalibrationStatus(
                runNumber=56000, stateID=None, isLite=True, calType="difcal",
                requireSameCycle=False,
            )

        assert result["runIsCalibrated"] is True

    @patch("snapwrap.snapStateMgr.get_cycle_for_run")
    @patch("snapwrap.snapStateMgr.checkStateExists", return_value=True)
    @patch("snapwrap.snapStateMgr.stateDef", return_value=["abc123", {}])
    def test_requireSameCycle_false_allows_cross_cycle(
        self, mock_stateDef, mock_stateExists, mock_gcfr
    ):
        default = _make_index_entry(0, "50000", ">=0", "2024-01-01T00:00:00.000")
        v1 = _make_index_entry(1, "55000", ">=50000", "2024-03-01T10:00:00.000")
        index_data = [default, v1]

        def cycle_side_effect(rn):
            rn = int(rn)
            if rn < 60000:
                return "2024-A"
            return "2024-B"

        mock_gcfr.side_effect = cycle_side_effect

        with patch("builtins.open", side_effect=_json_file_factory(index_data)), \
             patch("os.path.isfile", return_value=True):
            result = ssm.checkCalibrationStatus(
                runNumber=62000, stateID=None, isLite=True, calType="difcal",
                requireSameCycle=False
            )

        assert result["runIsCalibrated"] is True
        assert result["latestValidCalibrationDict"]["version"] == 1
        assert result["statusDetail"] == "valid calibration found"

    @patch("snapwrap.snapStateMgr.get_cycle_for_run")
    @patch("snapwrap.snapStateMgr.checkStateExists", return_value=True)
    @patch("snapwrap.snapStateMgr.stateDef", return_value=["abc123", {}])
    def test_requireSameCycle_true_rejects_cross_cycle(
        self, mock_stateDef, mock_stateExists, mock_gcfr
    ):
        default = _make_index_entry(0, "50000", ">=0", "2024-01-01T00:00:00.000")
        v1 = _make_index_entry(1, "55000", ">=50000", "2024-03-01T10:00:00.000")
        index_data = [default, v1]

        def cycle_side_effect(rn):
            rn = int(rn)
            if rn < 60000:
                return "2024-A"
            return "2024-B"

        mock_gcfr.side_effect = cycle_side_effect

        with patch("builtins.open", side_effect=_json_file_factory(index_data)), \
             patch("os.path.isfile", return_value=True):
            result = ssm.checkCalibrationStatus(
                runNumber=62000, stateID=None, isLite=True, calType="difcal",
                requireSameCycle=True
            )

        assert result["runIsCalibrated"] is False
        assert "out of cycle" in result["statusDetail"]


# ---------------------------------------------------------------------------
# checkCalibrationStatus -- statusDetail key
# ---------------------------------------------------------------------------

class TestCheckCalibrationStatusStatusDetail:

    @patch("snapwrap.snapStateMgr.checkStateExists", return_value=False)
    @patch("snapwrap.snapStateMgr.stateDef", return_value=["abc123", {}])
    def test_state_does_not_exist(self, mock_stateDef, mock_stateExists):
        result = ssm.checkCalibrationStatus(
            runNumber=55000, stateID=None, isLite=True, calType="difcal"
        )
        assert result["statusDetail"] == "state does not exist"

    @patch("snapwrap.snapStateMgr.checkStateExists", return_value=True)
    @patch("snapwrap.snapStateMgr.stateDef", return_value=["abc123", {}])
    def test_normcal_no_index_file(self, mock_stateDef, mock_stateExists):
        with patch("os.path.isfile", return_value=False):
            result = ssm.checkCalibrationStatus(
                runNumber=55000, stateID=None, isLite=True, calType="normcal"
            )
        assert result["statusDetail"] == "state exists but has no normalization index"

    @patch("snapwrap.snapStateMgr.get_cycle_for_run", return_value="2024-A")
    @patch("snapwrap.snapStateMgr.checkStateExists", return_value=True)
    @patch("snapwrap.snapStateMgr.stateDef", return_value=["abc123", {}])
    def test_difcal_only_default(self, mock_stateDef, mock_stateExists, mock_gcfr):
        default = _make_index_entry(0, "50000", ">=0", "2024-01-01T00:00:00.000")
        index_data = [default]

        with patch("builtins.open", side_effect=_json_file_factory(index_data)), \
             patch("os.path.isfile", return_value=True):
            result = ssm.checkCalibrationStatus(
                runNumber=55000, stateID=None, isLite=True, calType="difcal"
            )
        assert result["statusDetail"] == "state exists but only has default (geometric) difcal"

    @patch("snapwrap.snapStateMgr.VBRunNumberFromVersion", return_value="99999")
    @patch("snapwrap.snapStateMgr.get_cycle_for_run")
    @patch("snapwrap.snapStateMgr.checkStateExists", return_value=True)
    @patch("snapwrap.snapStateMgr.stateDef", return_value=["abc123", {}])
    def test_appliesTo_mismatch(self, mock_stateDef, mock_stateExists, mock_gcfr, mock_vb):
        """Use normcal (no catch-all default) with thresholds above the query run."""
        mock_gcfr.return_value = "2024-A"

        v1 = _make_index_entry(1, "55000", ">=55000", "2024-03-01T10:00:00.000")
        v2 = _make_index_entry(2, "60000", ">=60000", "2024-06-01T10:00:00.000")
        index_data = [v1, v2]

        with patch("builtins.open", side_effect=_json_file_factory(index_data)), \
             patch("os.path.isfile", return_value=True):
            result = ssm.checkCalibrationStatus(
                runNumber=52000, stateID=None, isLite=True, calType="normcal"
            )
        assert result["runIsCalibrated"] is False
        assert result["statusDetail"] == "calibrations exist but no matching run range in appliesTo"

    @patch("snapwrap.snapStateMgr.get_cycle_for_run")
    @patch("snapwrap.snapStateMgr.checkStateExists", return_value=True)
    @patch("snapwrap.snapStateMgr.stateDef", return_value=["abc123", {}])
    def test_out_of_cycle_detail_contains_both_cycles(
        self, mock_stateDef, mock_stateExists, mock_gcfr
    ):
        default = _make_index_entry(0, "50000", ">=0", "2024-01-01T00:00:00.000")
        v1 = _make_index_entry(1, "55000", ">=50000", "2024-03-01T10:00:00.000")
        index_data = [default, v1]

        def cycle_side_effect(rn):
            rn = int(rn)
            if rn < 60000:
                return "2024-A"
            return "2024-B"

        mock_gcfr.side_effect = cycle_side_effect

        with patch("builtins.open", side_effect=_json_file_factory(index_data)), \
             patch("os.path.isfile", return_value=True):
            result = ssm.checkCalibrationStatus(
                runNumber=62000, stateID=None, isLite=True, calType="difcal"
            )

        detail = result["statusDetail"]
        assert "out of cycle" in detail
        assert "2024-B" in detail
        assert "2024-A" in detail

    @patch("snapwrap.snapStateMgr.VBRunNumberFromVersion", return_value="99999")
    @patch("snapwrap.snapStateMgr.get_cycle_for_run")
    @patch("snapwrap.snapStateMgr.checkStateExists", return_value=True)
    @patch("snapwrap.snapStateMgr.stateDef", return_value=["abc123", {}])
    def test_requireSameCycle_false_appliesTo_mismatch(
        self, mock_stateDef, mock_stateExists, mock_gcfr, mock_vb
    ):
        """Use normcal (no catch-all default) so query run genuinely fails appliesTo."""
        mock_gcfr.return_value = "2024-A"

        v1 = _make_index_entry(1, "55000", ">=55000", "2024-03-01T10:00:00.000")
        v2 = _make_index_entry(2, "60000", ">=60000", "2024-06-01T10:00:00.000")
        index_data = [v1, v2]

        with patch("builtins.open", side_effect=_json_file_factory(index_data)), \
             patch("os.path.isfile", return_value=True):
            result = ssm.checkCalibrationStatus(
                runNumber=52000, stateID=None, isLite=True, calType="normcal",
                requireSameCycle=False
            )
        assert result["runIsCalibrated"] is False
        assert result["statusDetail"] == "calibrations exist but no matching run range in appliesTo"
