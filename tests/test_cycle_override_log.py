"""Tests for the out-of-cycle calibration override audit trail.

Using a calibration from another cycle is permitted, but only deliberately
(requireSameCycle=False) and never silently: the decision must outlive the
console session that made it.  These tests cover the recording side --
``_reportCycleOverride`` and ``_write_cycle_override_log`` in snapwrap.utils --
plus the remedy line printWarning offers when a calibration is withheld for
cycle reasons.
"""

import json
from unittest.mock import patch

import pytest

import snapwrap.utils as wrap
import snapwrap.statusPrinter as sp


def _calstatus(runCycleID, calCycleID, *, runCycleStatus="in_cycle", stateID="abc123"):
    return {
        "runCycleID": runCycleID,
        "runCycleStatus": runCycleStatus,
        "runCycleDetail": "test detail",
        "stateID": stateID,
        "latestValidCalibrationDict": {
            "cycleID": calCycleID,
            "runNumber": "64431",
            "version": 3,
        },
    }


def _read_log(tmp_path):
    logPath = tmp_path / ".logs" / "cycle_override_log.jsonl"
    if not logPath.exists():
        return []
    return [json.loads(line) for line in logPath.read_text().splitlines() if line.strip()]


@pytest.fixture
def calhome(tmp_path):
    """Point the calibration home at a temp dir for the duration of a test."""
    with patch.object(wrap, "Config", {"instrument.calibration.home": str(tmp_path)}):
        yield tmp_path


class TestCycleOverrideLog:

    def test_mismatch_is_recorded(self, calhome):
        difcal = _calstatus("2025-B", "2025-A")
        wrap._reportCycleOverride(66785, True, difcal, {})

        entries = _read_log(calhome)
        assert len(entries) == 1
        e = entries[0]
        assert e["runNumber"] == "66785"
        assert e["calType"] == "difcal"
        assert e["runCycleID"] == "2025-B"
        assert e["calibrationCycleID"] == "2025-A"
        assert e["calibrationRunNumber"] == "64431"
        assert e["calibrationVersion"] == 3
        assert e["stateID"] == "abc123"
        # provenance must identify who and when
        assert "timestamp" in e and "linux_user" in e

    def test_matching_cycle_is_not_recorded(self, calhome):
        """Requesting the override does not mean it was exercised."""
        difcal = _calstatus("2025-B", "2025-B")
        wrap._reportCycleOverride(66785, True, difcal, {})
        assert _read_log(calhome) == []

    def test_undecided_run_cycle_is_recorded(self, calhome):
        """An unprovable 'same cycle' counts as a mismatch, not a pass."""
        difcal = _calstatus(None, "2026-A", runCycleStatus="undecided")
        wrap._reportCycleOverride(72367, True, difcal, {})

        entries = _read_log(calhome)
        assert len(entries) == 1
        assert entries[0]["runCycleStatus"] == "undecided"
        assert entries[0]["runCycleID"] is None

    def test_both_caltypes_recorded_separately(self, calhome):
        difcal = _calstatus("2025-B", "2025-A")
        nrmcal = _calstatus("2025-B", "2024-A")
        wrap._reportCycleOverride(66785, True, difcal, nrmcal)

        entries = _read_log(calhome)
        assert {e["calType"] for e in entries} == {"difcal", "normcal"}

    def test_no_calibration_used_is_not_recorded(self, calhome):
        difcal = _calstatus("2025-B", "2025-A")
        difcal["latestValidCalibrationDict"] = {}
        wrap._reportCycleOverride(66785, True, difcal, {})
        assert _read_log(calhome) == []

    def test_log_failure_does_not_raise(self, calhome):
        """An audit-log failure must never take down a reduction."""
        difcal = _calstatus("2025-B", "2025-A")
        with patch("os.makedirs", side_effect=PermissionError("read-only")):
            wrap._reportCycleOverride(66785, True, difcal, {})  # must not raise


class TestCycleRemedyMessage:
    """The refusal must point at the right escape hatch.

    Without this, the only advice on offer is "proceed without a calibration",
    which discards a good calibration whose only fault is its cycle.
    """

    def test_out_of_cycle_offers_requireSameCycle(self):
        remedy = sp._cycleRemedy({
            "statusDetail": "valid calibration exists but is out of cycle (run cycle: 2025-B, ...)"
        })
        assert "requireSameCycle = False" in remedy
        assert "cycle_override_log.jsonl" in remedy

    def test_undecided_offers_requireSameCycle(self):
        remedy = sp._cycleRemedy({
            "statusDetail": "cycle could not be established for run 72367 ..."
        })
        assert "requireSameCycle = False" in remedy

    def test_unrelated_failure_offers_nothing_extra(self):
        remedy = sp._cycleRemedy({
            "statusDetail": "calibrations exist but no matching run range in appliesTo"
        })
        assert remedy == ""

    def test_tolerates_missing_details(self):
        assert sp._cycleRemedy(None) == ""
        assert sp._cycleRemedy({}) == ""
