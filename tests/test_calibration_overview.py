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


# ═══════════════════════════════════════════════════════════════════════
# Phase 1 — double-propagation detection
# ═══════════════════════════════════════════════════════════════════════


class TestIsDoublePropagated:
    """Unit tests for the pure-function is_double_propagated() helper."""

    from snapwrap.calibrationManager.constants import is_double_propagated as _fn

    # ── should match ────────────────────────────────────────────────
    def test_copy_of_copy_detected(self):
        comment = (
            "(copied from run:68979 version:2) original comments: "
            "(copied from run:12345 version:1) original comments: measured on site"
        )
        from snapwrap.calibrationManager.constants import is_double_propagated
        assert is_double_propagated(comment) is True

    def test_copy_of_copy_no_trailing_text(self):
        """Regex requires the second '(copied from run:' to appear — even mid-string."""
        comment = (
            "(copied from run:99999 version:10) original comments: "
            "(copied from run:11111 version:3)"
        )
        from snapwrap.calibrationManager.constants import is_double_propagated
        assert is_double_propagated(comment) is True

    # ── should NOT match ────────────────────────────────────────────
    def test_normal_propagation_not_flagged(self):
        comment = "(copied from run:68979 version:2) original comments: measured in 2024-B"
        from snapwrap.calibrationManager.constants import is_double_propagated
        assert is_double_propagated(comment) is False

    def test_empty_string_not_flagged(self):
        from snapwrap.calibrationManager.constants import is_double_propagated
        assert is_double_propagated("") is False

    def test_measured_comment_not_flagged(self):
        comment = "standard powder diffraction calibration"
        from snapwrap.calibrationManager.constants import is_double_propagated
        assert is_double_propagated(comment) is False

    def test_partial_prefix_not_flagged(self):
        """The first '(copied from run:…)' prefix must be present, not just the second."""
        comment = "original comments: (copied from run:12345 version:1)"
        from snapwrap.calibrationManager.constants import is_double_propagated
        assert is_double_propagated(comment) is False


class TestCombineCalTypeStatusesDoublePropagated:
    """combine_caltype_statuses() with hasDoublePropagated flag."""

    def test_double_propagated_returns_status(self):
        result = combine_caltype_statuses(
            CalTypeStatus.VALID, CalTypeStatus.VALID,
            hasDoublePropagated=True,
        )
        assert result is CalStatus.DOUBLE_PROPAGATED

    def test_corrupt_overrides_double_propagated(self):
        """CORRUPT must take precedence over DOUBLE_PROPAGATED."""
        result = combine_caltype_statuses(
            CalTypeStatus.VALID, CalTypeStatus.VALID,
            difCorrupt=True,
            hasDoublePropagated=True,
        )
        assert result is CalStatus.CORRUPT

    def test_double_propagated_display_constants(self):
        assert CalStatus.DOUBLE_PROPAGATED in STATUS_LABEL
        assert CalStatus.DOUBLE_PROPAGATED in STATUS_TOOLTIP
        assert STATUS_LABEL[CalStatus.DOUBLE_PROPAGATED] != ""
        assert STATUS_TOOLTIP[CalStatus.DOUBLE_PROPAGATED] != ""


class TestGetStateSummaryDoublePropagated:
    """getStateSummary() correctly detects double-propagated difcal entries.

    ``snapwrap.calibrationManager.model`` uses ``ssm`` as a module-level
    alias for ``snapwrap.snapStateMgr``.  We patch its attributes directly
    so no real calibration home is touched.
    """

    # ── constants reused across tests ────────────────────────────────
    _STATE_ID = "abcd1234abcd1234"
    _DP_COMMENT = (
        "(copied from run:68979 version:2) original comments: "
        "(copied from run:12345 version:1) original comments: measured"
    )

    @staticmethod
    def _cal_status(entries, status_detail="no run number provided; general state info only"):
        """Return a fake checkCalibrationStatus response with given calibIndexList."""
        return {
            "statusDetail": status_detail,
            "calibIndexList": entries,
        }

    @staticmethod
    def _patch_ssm(difcal_entries, normcal_entries=None):
        """Return a context-manager that patches the model's ssm module reference."""
        from unittest.mock import MagicMock, patch

        _nrm = normcal_entries or []

        def _check_cal_status(runNumber, stateID, isLite, calType):
            entries = difcal_entries if calType == "difcal" else _nrm
            return {
                "statusDetail": "no run number provided; general state info only",
                "calibIndexList": entries,
                "numberCalibrations": len(entries),
                "latestCalibrationDate": "never",
            }

        mock_ssm = MagicMock()
        mock_ssm.checkCalibrationStatus.side_effect = _check_cal_status
        mock_ssm.validateIndex.return_value = {"ok": True}
        mock_ssm.pullStateDict.return_value = {}
        mock_ssm.autoStateName.return_value = "test-state"
        return patch("snapwrap.calibrationManager.model.ssm", mock_ssm)

    @staticmethod
    def _model():
        import sys
        from unittest.mock import MagicMock
        for mod in (
            "qtpy", "qtpy.QtCore", "qtpy.QtGui", "qtpy.QtWidgets",
            "snapwrap.cycleDates",
        ):
            sys.modules.setdefault(mod, MagicMock())
        from snapwrap.calibrationManager.model import CalibrationManagerModel
        return CalibrationManagerModel()

    # ── getStateSummary tests ────────────────────────────────────────

    def test_no_double_propagated(self):
        entries = [
            {"version": "1", "comments": "measured on site"},
            {"version": "2", "comments": "(copied from run:68979 version:1) original comments: measured on site"},
        ]
        model = self._model()
        with self._patch_ssm(entries):
            summary = model.getStateSummary(self._STATE_ID)
        assert summary["hasDoublePropagated"] is False
        assert summary["doublePropagatedVersions"] == []

    def test_one_double_propagated(self):
        entries = [
            {"version": "1", "comments": "measured on site"},
            {"version": "3", "comments": self._DP_COMMENT},
        ]
        model = self._model()
        with self._patch_ssm(entries):
            summary = model.getStateSummary(self._STATE_ID)
        assert summary["hasDoublePropagated"] is True
        assert summary["doublePropagatedVersions"] == [3]

    def test_multiple_double_propagated(self):
        entries = [
            {"version": "1", "comments": "measured on site"},
            {"version": "2", "comments": self._DP_COMMENT},
            {"version": "4", "comments": self._DP_COMMENT},
        ]
        model = self._model()
        with self._patch_ssm(entries):
            summary = model.getStateSummary(self._STATE_ID)
        assert summary["hasDoublePropagated"] is True
        assert set(summary["doublePropagatedVersions"]) == {2, 4}

    def test_version_zero_skipped(self):
        """Version 0 (geometric default) must never be flagged as double-propagated."""
        entries = [
            {"version": "0", "comments": self._DP_COMMENT},
            {"version": "1", "comments": "measured on site"},
        ]
        model = self._model()
        with self._patch_ssm(entries):
            summary = model.getStateSummary(self._STATE_ID)
        assert summary["hasDoublePropagated"] is False

    # ── getCalibrationDetails tests ──────────────────────────────────

    def test_getCalibrationDetails_annotates_entries(self):
        """getCalibrationDetails() must set isDoublePropagated on each entry."""
        raw_entries = [
            {"version": "1", "comments": "measured on site", "runNumber": "68979"},
            {"version": "2", "comments": self._DP_COMMENT, "runNumber": "68979"},
        ]
        model = self._model()
        with self._patch_ssm(raw_entries):
            details = model.getCalibrationDetails(self._STATE_ID, calType="difcal")
        # getCalibrationDetails returns a list sorted by version
        assert details[0]["isDoublePropagated"] is False
        assert details[1]["isDoublePropagated"] is True


# ═══════════════════════════════════════════════════════════════════════
# Phase 2 — removeDoublePropagatedEntries()
# ═══════════════════════════════════════════════════════════════════════


class TestRemoveDoublePropagatedEntries:
    """Unit tests for model.removeDoublePropagatedEntries().

    ``deleteCalibrationVersion`` does real filesystem work; we patch it
    on the model class so no files are touched.
    """

    _STATE_ID = "abcd1234abcd1234"
    _DP_COMMENT = (
        "(copied from run:68979 version:2)  original comments: "
        "(copied from run:12345 version:1)  original comments: measured"
    )

    @staticmethod
    def _model():
        import sys
        from unittest.mock import MagicMock
        for mod in (
            "qtpy", "qtpy.QtCore", "qtpy.QtGui", "qtpy.QtWidgets",
            "snapwrap.cycleDates",
        ):
            sys.modules.setdefault(mod, MagicMock())
        from snapwrap.calibrationManager.model import CalibrationManagerModel
        return CalibrationManagerModel()

    @staticmethod
    def _patch_ssm(entries):
        from unittest.mock import MagicMock, patch

        def _check(runNumber, stateID, isLite, calType):
            return {
                "statusDetail": "no run number provided; general state info only",
                "calibIndexList": entries if calType == "difcal" else [],
                "numberCalibrations": len(entries),
                "latestCalibrationDate": "never",
            }

        mock_ssm = MagicMock()
        mock_ssm.checkCalibrationStatus.side_effect = _check
        mock_ssm.validateIndex.return_value = {"ok": True}
        mock_ssm.pullStateDict.return_value = {}
        mock_ssm.autoStateName.return_value = "test-state"
        return patch("snapwrap.calibrationManager.model.ssm", mock_ssm)

    def test_no_double_propagated_entries(self):
        """Returns ok=True with empty versions list when nothing to do."""
        entries = [
            {"version": "1", "comments": "measured on site"},
            {"version": "2", "comments": "(copied from run:68979 version:1)  original comments: measured"},
        ]
        model = self._model()
        with self._patch_ssm(entries):
            result = model.removeDoublePropagatedEntries(self._STATE_ID, dryRun=True)
        assert result["ok"] is True
        assert result["versions"] == []
        assert "No double-propagated" in result["summary"]

    def test_dry_run_reports_versions_without_deleting(self):
        """Dry-run returns the correct version list; deleteCalibrationVersion not called live."""
        entries = [
            {"version": "1", "comments": "measured on site"},
            {"version": "3", "comments": self._DP_COMMENT},
        ]
        model = self._model()
        from unittest.mock import patch as _patch
        with self._patch_ssm(entries):
            with _patch.object(
                model.__class__, "deleteCalibrationVersion",
                return_value={"ok": True, "message": "[DRY RUN] Would delete…"},
            ) as mock_delete:
                result = model.removeDoublePropagatedEntries(
                    self._STATE_ID, dryRun=True,
                )
        assert result["ok"] is True
        assert result["versions"] == [3]
        assert "[DRY RUN]" in result["summary"]
        # deleteCalibrationVersion should have been called once (dry-run=True)
        mock_delete.assert_called_once_with(
            self._STATE_ID, "difcal", 3, isLite=True, dryRun=True,
        )

    def test_live_run_calls_delete_for_each_version(self):
        """Live run calls deleteCalibrationVersion for each DP version."""
        entries = [
            {"version": "1", "comments": "measured on site"},
            {"version": "2", "comments": self._DP_COMMENT},
            {"version": "4", "comments": self._DP_COMMENT},
        ]
        model = self._model()
        from unittest.mock import patch as _patch, call
        with self._patch_ssm(entries):
            with _patch.object(
                model.__class__, "deleteCalibrationVersion",
                return_value={"ok": True, "message": "Deleted."},
            ) as mock_delete:
                result = model.removeDoublePropagatedEntries(
                    self._STATE_ID, dryRun=False,
                )
        assert result["ok"] is True
        assert set(result["versions"]) == {2, 4}
        # Should be called highest-first (4 then 2) so re-numbering is safe
        calls = mock_delete.call_args_list
        assert calls[0] == call(self._STATE_ID, "difcal", 4, isLite=True, dryRun=False)
        assert calls[1] == call(self._STATE_ID, "difcal", 2, isLite=True, dryRun=False)

    def test_partial_failure_propagates_ok_false(self):
        """If any deletion fails, ok=False is returned."""
        entries = [
            {"version": "1", "comments": "measured on site"},
            {"version": "2", "comments": self._DP_COMMENT},
        ]
        model = self._model()
        from unittest.mock import patch as _patch
        with self._patch_ssm(entries):
            with _patch.object(
                model.__class__, "deleteCalibrationVersion",
                return_value={"ok": False, "message": "File not found."},
            ):
                result = model.removeDoublePropagatedEntries(
                    self._STATE_ID, dryRun=False,
                )
        assert result["ok"] is False
        assert result["versions"] == [2]

    def test_version_zero_never_deleted(self):
        """Version 0 must never be targeted even if its comment matches."""
        entries = [
            {"version": "0", "comments": self._DP_COMMENT},
            {"version": "1", "comments": "measured on site"},
        ]
        model = self._model()
        with self._patch_ssm(entries):
            result = model.removeDoublePropagatedEntries(self._STATE_ID, dryRun=True)
        assert result["versions"] == []

