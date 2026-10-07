"""Tests for retiring a calibration version by invalidation rather than deletion.

The JSON rewriting runs for real against files built in ``tmp_path`` — only
``ssm.checkCalibrationStatus`` and ``ssm._session_backup_dir`` are stubbed,
and those are path-resolution seams (they would otherwise scan the production
calibration home), not the logic under test.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from snapwrap.calibrationManager.constants import is_double_propagated
from snapwrap.indexComments import (
    INVALIDATED_PREFIX,
    NEVER_APPLIES,
    is_invalidated,
    mark_invalidated,
    strip_invalidated,
)


# ═══════════════════════════════════════════════════════════════════════
# The comment/appliesTo vocabulary
# ═══════════════════════════════════════════════════════════════════════


class TestIndexComments:
    def test_marker_round_trips(self):
        marked = mark_invalidated("2026A calibration")
        assert marked == "(INVALIDATED) 2026A calibration"
        assert is_invalidated(marked)
        assert strip_invalidated(marked) == "2026A calibration"

    def test_marking_is_idempotent(self):
        once = mark_invalidated("2026A calibration")
        twice = mark_invalidated(once)
        assert once == twice
        assert twice.count(INVALIDATED_PREFIX) == 1

    def test_empty_and_none_comments(self):
        assert mark_invalidated("") == INVALIDATED_PREFIX
        assert mark_invalidated(None) == INVALIDATED_PREFIX
        assert is_invalidated(None) is False
        assert strip_invalidated(None) is None

    def test_unmarked_comment_untouched(self):
        assert strip_invalidated("measured on site") == "measured on site"
        assert is_invalidated("measured on site") is False

    def test_never_applies_is_negative(self):
        """No run number can satisfy it — snapred compares numerically."""
        assert NEVER_APPLIES.startswith("<")
        assert int(NEVER_APPLIES.lstrip("<")) <= 0


def test_never_applies_passes_snapred_validation():
    """The marker value must survive snapred's own IndexEntry validator."""
    from snapred.backend.dao.indexing.IndexEntry import IndexEntry

    entry = IndexEntry(
        runNumber="72375", useLiteMode=True, version=3,
        appliesTo=NEVER_APPLIES, comments=mark_invalidated("x"), author="test",
    )
    assert entry.appliesTo == NEVER_APPLIES

    symbol, runNumber = IndexEntry.parseConditional(NEVER_APPLIES)
    assert symbol == "<"
    assert int(runNumber) == 0


def test_never_applies_excludes_entry_from_lookup():
    """snapred's applicability check must reject it for a real run number."""
    from snapred.backend.dao.indexing.IndexEntry import IndexEntry

    conditionals = IndexEntry.parseAppliesTo(NEVER_APPLIES)
    assert len(conditionals) == 1
    symbol, bound = conditionals[0]
    # replicate Indexer._compareRunNumbers for '<'
    assert not (int("72375") < int(bound))


# ═══════════════════════════════════════════════════════════════════════
# Marker tolerance in the comment parsers
# ═══════════════════════════════════════════════════════════════════════


_DP_COMMENT = (
    "(copied from run:68979 version:2)  original comments: "
    "(copied from run:12345 version:1)  original comments: measured"
)


def test_double_propagated_still_detected_when_invalidated():
    """Retiring an entry must not hide what it was."""
    assert is_double_propagated(_DP_COMMENT) is True
    assert is_double_propagated(mark_invalidated(_DP_COMMENT)) is True


def test_propagated_entry_still_detected_when_invalidated():
    from snapwrap import utils

    propagated = {"comments": "(copied from run:68979 version:2) original comments: measured"}
    assert utils._is_propagated_entry(propagated) is True

    retired = {"comments": mark_invalidated(propagated["comments"])}
    assert utils._is_propagated_entry(retired) is True


# ═══════════════════════════════════════════════════════════════════════
# invalidateCalibrationVersion against real files
# ═══════════════════════════════════════════════════════════════════════


STATE_ID = "abcd1234abcd1234"


def _build_state(tmp_path, calType="difcal"):
    """Create an index plus two version folders with all three embedded copies."""
    recordName, paramsName = (
        ("CalibrationRecord.json", "CalibrationParameters.json")
        if calType == "difcal"
        else ("NormalizationRecord.json", "NormalizationParameters.json")
    )

    calFolder = tmp_path / "Powder" / STATE_ID / "lite" / calType
    calFolder.mkdir(parents=True)
    indexPath = calFolder / "CalibrationIndex.json"

    entries = [
        {"version": 0, "runNumber": "66782", "useLiteMode": True, "appliesTo": ">=0",
         "comments": "default", "author": "SNAPRed Internal", "timestamp": "2025-01-01T00:00:00"},
        {"version": 1, "runNumber": "66782", "useLiteMode": True, "appliesTo": ">=66569",
         "comments": "measured on site", "author": "C. Ridley", "timestamp": "2025-09-16T12:45:32"},
        {"version": 2, "runNumber": "72375", "useLiteMode": True, "appliesTo": ">=72368",
         "comments": _DP_COMMENT, "author": "C. Ridley", "timestamp": "2026-08-10T11:24:25"},
    ]
    indexPath.write_text(json.dumps(entries, indent=2))

    for e in entries:
        vdir = calFolder / f"v_{str(e['version']).zfill(4)}"
        vdir.mkdir()
        (vdir / recordName).write_text(json.dumps({
            "version": e["version"],
            "indexEntry": dict(e),
            "runNumber": e["runNumber"],
            "calculationParameters": {"version": e["version"], "indexEntry": dict(e)},
        }, indent=2))
        (vdir / paramsName).write_text(json.dumps({
            "version": e["version"], "indexEntry": dict(e), "seedRun": e["runNumber"],
        }, indent=2))
        # a bulky non-JSON artefact that invalidation must leave alone
        (vdir / f"diffract_consts_v{str(e['version']).zfill(4)}.h5").write_bytes(b"binary")

    return calFolder, indexPath, entries


def _model_with(tmp_path, entries, calFolder, indexPath):
    from snapwrap.calibrationManager.model import CalibrationManagerModel

    backupDir = tmp_path / "Backup" / "session"
    backupDir.mkdir(parents=True, exist_ok=True)

    mock_ssm = MagicMock()
    mock_ssm.checkCalibrationStatus.return_value = {
        "calFolder": str(calFolder),
        "indexPath": str(indexPath),
        "calibIndexList": entries,
    }
    mock_ssm._session_backup_dir.return_value = str(backupDir)
    return CalibrationManagerModel(), patch(
        "snapwrap.calibrationManager.model.ssm", mock_ssm
    ), backupDir


def _read(path):
    return json.loads(path.read_text())


class TestInvalidateCalibrationVersion:

    def test_dry_run_writes_nothing(self, tmp_path):
        calFolder, indexPath, entries = _build_state(tmp_path)
        before = indexPath.read_text()
        model, ctx, _ = _model_with(tmp_path, entries, calFolder, indexPath)

        with ctx:
            result = model.invalidateCalibrationVersion(STATE_ID, "difcal", 2, dryRun=True)

        assert result["ok"] is True
        assert "[DRY RUN]" in result["message"]
        assert indexPath.read_text() == before

    def test_all_four_copies_updated(self, tmp_path):
        calFolder, indexPath, entries = _build_state(tmp_path)
        model, ctx, _ = _model_with(tmp_path, entries, calFolder, indexPath)

        with ctx:
            result = model.invalidateCalibrationVersion(STATE_ID, "difcal", 2, dryRun=False)

        assert result["ok"] is True

        index = _read(indexPath)
        target = next(e for e in index if e["version"] == 2)
        assert target["appliesTo"] == NEVER_APPLIES
        assert target["comments"].startswith(INVALIDATED_PREFIX)

        vdir = calFolder / "v_0002"
        rec = _read(vdir / "CalibrationRecord.json")
        par = _read(vdir / "CalibrationParameters.json")

        assert rec["indexEntry"]["appliesTo"] == NEVER_APPLIES
        assert rec["calculationParameters"]["indexEntry"]["appliesTo"] == NEVER_APPLIES
        assert par["indexEntry"]["appliesTo"] == NEVER_APPLIES

        # every copy must match the index entry exactly, or validateIndex flags it
        assert rec["indexEntry"] == target
        assert rec["calculationParameters"]["indexEntry"] == target
        assert par["indexEntry"] == target

    def test_folder_and_numbering_preserved(self, tmp_path):
        """The provenance guarantee: nothing removed, nothing re-numbered."""
        calFolder, indexPath, entries = _build_state(tmp_path)
        model, ctx, _ = _model_with(tmp_path, entries, calFolder, indexPath)

        with ctx:
            model.invalidateCalibrationVersion(STATE_ID, "difcal", 2, dryRun=False)

        assert (calFolder / "v_0002").is_dir()
        assert (calFolder / "v_0002" / "diffract_consts_v0002.h5").exists()
        assert [e["version"] for e in _read(indexPath)] == [0, 1, 2]

    def test_other_versions_untouched(self, tmp_path):
        calFolder, indexPath, entries = _build_state(tmp_path)
        v1_before = (calFolder / "v_0001" / "CalibrationRecord.json").read_text()
        model, ctx, _ = _model_with(tmp_path, entries, calFolder, indexPath)

        with ctx:
            model.invalidateCalibrationVersion(STATE_ID, "difcal", 2, dryRun=False)

        index = _read(indexPath)
        v1 = next(e for e in index if e["version"] == 1)
        assert v1["appliesTo"] == ">=66569"
        assert v1["comments"] == "measured on site"
        assert (calFolder / "v_0001" / "CalibrationRecord.json").read_text() == v1_before

    def test_version_zero_refused(self, tmp_path):
        calFolder, indexPath, entries = _build_state(tmp_path)
        before = indexPath.read_text()
        model, ctx, _ = _model_with(tmp_path, entries, calFolder, indexPath)

        with ctx:
            result = model.invalidateCalibrationVersion(STATE_ID, "difcal", 0, dryRun=False)

        assert result["ok"] is False
        assert "version 0" in result["message"].lower()
        assert indexPath.read_text() == before

    def test_missing_version_refused(self, tmp_path):
        calFolder, indexPath, entries = _build_state(tmp_path)
        model, ctx, _ = _model_with(tmp_path, entries, calFolder, indexPath)

        with ctx:
            result = model.invalidateCalibrationVersion(STATE_ID, "difcal", 99, dryRun=False)

        assert result["ok"] is False
        assert "not found" in result["message"].lower()

    def test_double_invalidation_refused(self, tmp_path):
        """Second attempt is rejected rather than stacking markers."""
        calFolder, indexPath, entries = _build_state(tmp_path)
        model, ctx, _ = _model_with(tmp_path, entries, calFolder, indexPath)

        with ctx:
            model.invalidateCalibrationVersion(STATE_ID, "difcal", 2, dryRun=False)
            refreshed = _read(indexPath)

        model2, ctx2, _ = _model_with(tmp_path, refreshed, calFolder, indexPath)
        with ctx2:
            result = model2.invalidateCalibrationVersion(STATE_ID, "difcal", 2, dryRun=False)

        assert result["ok"] is False
        assert "already invalidated" in result["message"].lower()
        target = next(e for e in _read(indexPath) if e["version"] == 2)
        assert target["comments"].count(INVALIDATED_PREFIX) == 1

    def test_backup_written(self, tmp_path):
        calFolder, indexPath, entries = _build_state(tmp_path)
        model, ctx, backupDir = _model_with(tmp_path, entries, calFolder, indexPath)

        with ctx:
            model.invalidateCalibrationVersion(STATE_ID, "difcal", 2, dryRun=False)

        saved = backupDir / "v_0002" / "CalibrationRecord.json"
        assert saved.exists()
        # the backup holds the pre-invalidation state
        assert _read(saved)["indexEntry"]["appliesTo"] == ">=72368"
        assert (backupDir / "CalibrationIndex.json").exists()

    def test_normalization_record_names(self, tmp_path):
        """normcal uses Normalization*.json rather than Calibration*.json."""
        calFolder, indexPath, entries = _build_state(tmp_path, calType="normalization")
        model, ctx, _ = _model_with(tmp_path, entries, calFolder, indexPath)

        with ctx:
            result = model.invalidateCalibrationVersion(
                STATE_ID, "normalization", 2, dryRun=False,
            )

        assert result["ok"] is True
        vdir = calFolder / "v_0002"
        assert _read(vdir / "NormalizationRecord.json")["indexEntry"]["appliesTo"] == NEVER_APPLIES
        assert _read(vdir / "NormalizationParameters.json")["indexEntry"]["appliesTo"] == NEVER_APPLIES
        assert set(result["updatedFiles"]) == {
            str(indexPath),
            str(vdir / "NormalizationRecord.json"),
            str(vdir / "NormalizationParameters.json"),
        }

    def test_normcal_version_zero_allowed(self, tmp_path):
        """Only difcal has a protected geometric default at version 0."""
        calFolder, indexPath, entries = _build_state(tmp_path, calType="normalization")
        model, ctx, _ = _model_with(tmp_path, entries, calFolder, indexPath)

        with ctx:
            result = model.invalidateCalibrationVersion(
                STATE_ID, "normalization", 0, dryRun=False,
            )

        assert result["ok"] is True
