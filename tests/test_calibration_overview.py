"""Unit tests for Phase 2: StateOverviewPanel and the two-mode UX.

These tests exercise the *non-Qt* parts (StateTableModel data access,
tooltip logic, mode switching) plus the widget wiring where feasible.

Run with::

    pixi run pytest --noconftest tests/test_calibration_overview.py -v --tb=long
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# ── Ensure the mock-free constants module is importable ─────────────
# We mock qtpy before importing the panel so we don't need a real
# display server.  We also mock the snapwrap backend modules that
# chain into mantid.
#
# IMPORTANT: We must save any real modules that were already imported
# and restore them after our imports are done, otherwise these mocks
# leak into other test files (e.g. test_calibration_status.py) and
# cause every ssm function call to return a MagicMock.

_qt_core_mock = MagicMock()
_qt_core_mock.Qt.DisplayRole = 0
_qt_core_mock.Qt.UserRole = 256
_qt_core_mock.Qt.ToolTipRole = 3
_qt_core_mock.Qt.Horizontal = 1
_qt_core_mock.Qt.CaseInsensitive = 1
_qt_core_mock.Qt.NoPen = 0
_qt_core_mock.Qt.ItemIsEditable = 2

_MOCK_MODULES = {
    "qtpy": MagicMock(),
    "qtpy.QtCore": _qt_core_mock,
    "qtpy.QtGui": MagicMock(),
    "qtpy.QtWidgets": MagicMock(),
    "snapwrap.snapStateMgr": MagicMock(),
    "snapwrap.cycleDates": MagicMock(),
}

# Save originals so we can restore after import
_saved = {name: sys.modules.get(name) for name in _MOCK_MODULES}

# Inject mocks for the imports below
for name, mock in _MOCK_MODULES.items():
    sys.modules.setdefault(name, mock)


from snapwrap.calibrationManager.constants import (
    CalStatus,
    CalTypeStatus,
    MODE_A_TOOLTIP,
    STATUS_LABEL,
    STATUS_TOOLTIP,
    caltype_status_for_cycle,
    caltype_status_from_detail,
    combine_caltype_statuses,
)

# ── Restore original modules so other test files are not affected ───
for name, original in _saved.items():
    if original is not None:
        sys.modules[name] = original
    else:
        sys.modules.pop(name, None)


# ═══════════════════════════════════════════════════════════════════════
# Constants / classification tests
# ═══════════════════════════════════════════════════════════════════════


class TestCalTypeStatusFromDetail:
    """Test the centralized statusDetail → CalTypeStatus mapping."""

    def test_state_missing(self):
        result = caltype_status_from_detail({"statusDetail": "state does not exist"})
        assert result is CalTypeStatus.STATE_MISSING

    def test_corrupt_json(self):
        result = caltype_status_from_detail(
            {"statusDetail": "calibration index exists but contains invalid JSON: /foo"}
        )
        assert result is CalTypeStatus.CORRUPT_INDEX

    def test_unexpected_error(self):
        result = caltype_status_from_detail(
            {"statusDetail": "unexpected error reading calibration index: /foo"}
        )
        assert result is CalTypeStatus.CORRUPT_INDEX

    def test_no_normalization(self):
        result = caltype_status_from_detail(
            {"statusDetail": "state exists but has no normalization index"}
        )
        assert result is CalTypeStatus.UNCALIBRATED

    def test_default_only(self):
        result = caltype_status_from_detail(
            {"statusDetail": "state exists but only has default (geometric) difcal"}
        )
        assert result is CalTypeStatus.UNCALIBRATED

    def test_no_run_provided(self):
        result = caltype_status_from_detail(
            {"statusDetail": "no run number provided; general state info only"}
        )
        assert result is CalTypeStatus.EXISTS_NO_RUN

    def test_valid(self):
        result = caltype_status_from_detail(
            {"statusDetail": "valid calibration found", "runIsCalibrated": True}
        )
        assert result is CalTypeStatus.VALID

    def test_out_of_cycle(self):
        result = caltype_status_from_detail(
            {
                "statusDetail": (
                    "valid calibration exists but is out of cycle "
                    "(run cycle: 2025-A, calibration cycle: 2024-B)"
                ),
                "runIsCalibrated": False,
            }
        )
        assert result is CalTypeStatus.OUT_OF_CYCLE

    def test_unmatched(self):
        result = caltype_status_from_detail(
            {
                "statusDetail": "calibrations exist but no matching run range in appliesTo",
                "runIsCalibrated": False,
            }
        )
        assert result is CalTypeStatus.UNMATCHED


class TestCalTypeStatusForCycle:
    """Test the cycle-only classification function."""

    def test_state_missing(self):
        result = caltype_status_for_cycle(
            {"statusDetail": "state does not exist"}, "2025-A",
        )
        assert result is CalTypeStatus.STATE_MISSING

    def test_corrupt_json(self):
        result = caltype_status_for_cycle(
            {"statusDetail": "calibration index exists but contains invalid JSON: /foo"},
            "2025-A",
        )
        assert result is CalTypeStatus.CORRUPT_INDEX

    def test_unexpected_error(self):
        result = caltype_status_for_cycle(
            {"statusDetail": "unexpected error reading calibration index: /foo"},
            "2025-A",
        )
        assert result is CalTypeStatus.CORRUPT_INDEX

    def test_no_normalization(self):
        result = caltype_status_for_cycle(
            {"statusDetail": "state exists but has no normalization index"},
            "2025-A",
        )
        assert result is CalTypeStatus.UNCALIBRATED

    def test_default_only(self):
        result = caltype_status_for_cycle(
            {"statusDetail": "state exists but only has default (geometric) difcal"},
            "2025-A",
        )
        assert result is CalTypeStatus.UNCALIBRATED

    def test_matching_cycle(self):
        """An entry whose cycleID matches → VALID."""
        result = caltype_status_for_cycle(
            {
                "statusDetail": "no run number provided; general state info only",
                "calibIndexList": [
                    {"cycleID": "2024-B", "version": "1"},
                    {"cycleID": "2025-A", "version": "2"},
                ],
            },
            "2025-A",
        )
        assert result is CalTypeStatus.VALID

    def test_no_matching_cycle(self):
        """Entries exist but none from the selected cycle → OUT_OF_CYCLE."""
        result = caltype_status_for_cycle(
            {
                "statusDetail": "no run number provided; general state info only",
                "calibIndexList": [
                    {"cycleID": "2024-A", "version": "1"},
                    {"cycleID": "2024-B", "version": "2"},
                ],
            },
            "2025-A",
        )
        assert result is CalTypeStatus.OUT_OF_CYCLE

    def test_empty_index_list(self):
        """calibIndexList is empty (shouldn't normally happen) → UNCALIBRATED."""
        result = caltype_status_for_cycle(
            {
                "statusDetail": "no run number provided; general state info only",
                "calibIndexList": [],
            },
            "2025-A",
        )
        assert result is CalTypeStatus.UNCALIBRATED

    def test_missing_index_list(self):
        """calibIndexList key absent → UNCALIBRATED."""
        result = caltype_status_for_cycle(
            {"statusDetail": "no run number provided; general state info only"},
            "2025-A",
        )
        assert result is CalTypeStatus.UNCALIBRATED


class TestCombineCalTypeStatuses:
    """Test the per-calType → overall CalStatus combiner."""

    def test_both_valid(self):
        assert (
            combine_caltype_statuses(CalTypeStatus.VALID, CalTypeStatus.VALID)
            is CalStatus.FULL
        )

    def test_both_exist_no_run(self):
        assert (
            combine_caltype_statuses(CalTypeStatus.EXISTS_NO_RUN, CalTypeStatus.EXISTS_NO_RUN)
            is CalStatus.FULL
        )

    def test_one_valid_one_uncalibrated(self):
        assert (
            combine_caltype_statuses(CalTypeStatus.VALID, CalTypeStatus.UNCALIBRATED)
            is CalStatus.PARTIAL
        )

    def test_both_uncalibrated(self):
        assert (
            combine_caltype_statuses(CalTypeStatus.UNCALIBRATED, CalTypeStatus.UNCALIBRATED)
            is CalStatus.UNCALIBRATED
        )

    def test_corruption_overrides(self):
        assert (
            combine_caltype_statuses(
                CalTypeStatus.VALID, CalTypeStatus.VALID,
                difCorrupt=True,
            )
            is CalStatus.CORRUPT
        )

    def test_out_of_cycle(self):
        assert (
            combine_caltype_statuses(CalTypeStatus.VALID, CalTypeStatus.OUT_OF_CYCLE)
            is CalStatus.OUT_OF_CYCLE
        )

    def test_unmatched(self):
        assert (
            combine_caltype_statuses(CalTypeStatus.UNMATCHED, CalTypeStatus.VALID)
            is CalStatus.UNMATCHED
        )

    def test_corrupt_index_status(self):
        assert (
            combine_caltype_statuses(CalTypeStatus.CORRUPT_INDEX, CalTypeStatus.VALID)
            is CalStatus.CORRUPT
        )


class TestDisplayConstants:
    """Ensure every CalStatus has a label, colour, and tooltip."""

    @pytest.mark.parametrize("status", list(CalStatus))
    def test_label_exists(self, status):
        assert status in STATUS_LABEL

    @pytest.mark.parametrize("status", list(CalStatus))
    def test_tooltip_exists(self, status):
        assert status in STATUS_TOOLTIP

    def test_mode_a_tooltip_is_nonempty(self):
        assert MODE_A_TOOLTIP


# ═══════════════════════════════════════════════════════════════════════
# StateTableModel tooltip logic (tested without actual Qt)
# ═══════════════════════════════════════════════════════════════════════


class TestTooltipLogic:
    """Test the _build_status_tooltip module-level function."""

    @staticmethod
    def _call(hasContext, row_dict, status):
        from snapwrap.calibrationManager.stateOverviewPanel import _build_status_tooltip
        return _build_status_tooltip(hasContext, row_dict, status)

    def test_mode_a_returns_generic_prompt(self):
        tip = self._call(False, {}, CalStatus.FULL)
        assert tip == MODE_A_TOOLTIP

    def test_mode_b_returns_rich_tooltip(self):
        row = {
            "difcalDetail": "valid calibration found",
            "normcalDetail": "out of cycle (run cycle: 2025-A, calibration cycle: 2024-B)",
        }
        tip = self._call(True, row, CalStatus.OUT_OF_CYCLE)
        assert "Status: Out of Cycle" in tip
        assert "difcal: valid calibration found" in tip
        assert "normcal: out of cycle" in tip

    def test_mode_b_no_details_still_shows_label(self):
        tip = self._call(True, {}, CalStatus.UNCALIBRATED)
        assert "Status: Uncalibrated" in tip
