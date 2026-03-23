import json
import os
import textwrap
import pytest
from unittest.mock import patch

from snapwrap import snapStateMgr as ssm


def test_pullStateDict_missing_file(tmp_path, capsys):
    # Point Config to a temp calibration home
    with patch.dict(ssm.Config._config, {"instrument": {"calibration": {"home": str(tmp_path)}}}):
        state_id = 'deadbeefdeadbeef'
        out = ssm.pullStateDict(state_id)
    captured = capsys.readouterr()
    assert out == {}, "Expected empty dict when calibration file missing"
    assert 'CalibrationParameters.json not found' in captured.out


def test_pullStateDict_invalid_json(tmp_path, capsys):
    with patch.dict(ssm.Config._config, {"instrument": {"calibration": {"home": str(tmp_path)}}}):
        state_id = 'cafebabecafebabe'
        state_dir = tmp_path / 'Powder' / state_id / 'lite' / 'diffraction' / 'v_0000'
        state_dir.mkdir(parents=True)
        bad_json_path = state_dir / 'CalibrationParameters.json'
        bad_json_path.write_text('{ this is : not valid json }')

        out = ssm.pullStateDict(state_id)
    captured = capsys.readouterr()
    assert out == {}
    assert 'Failed to parse JSON' in captured.out


def test_pullStateDict_valid_json(tmp_path):
    with patch.dict(ssm.Config._config, {"instrument": {"calibration": {"home": str(tmp_path)}}}):
        state_id = '0123456789abcdef'
        state_dir = tmp_path / 'Powder' / state_id / 'lite' / 'diffraction' / 'v_0000'
        state_dir.mkdir(parents=True)

        payload = {
            "instrumentState": {
                "detectorState": {
                    "PVs": {
                        "det_lin1": 1,
                        "det_lin2": 2,
                        "BL3:Det:TH:BL:Frequency": 60
                    }
                }
            }
        }
        (state_dir / 'CalibrationParameters.json').write_text(json.dumps(payload))

        out = ssm.pullStateDict(state_id)
    # det_lin1/det_lin2 should be removed and frequency converted to float
    assert "det_lin1" not in out
    assert "det_lin2" not in out
    assert isinstance(out["BL3:Det:TH:BL:Frequency"], float)


def test_matchingCalibrationIndex_basic():
    # Two entries, the most recent (index 0) should be chosen when it matches
    calIndexList = [
        {"timestamp": "2026-01-02T00:00:00Z", "appliesTo": ">=64400, <=64500"},
        {"timestamp": "2025-12-31T00:00:00Z", "appliesTo": ">=1"},
    ]
    idx = ssm.matchingCalibrationIndex(calIndexList, 64413)
    assert idx == 0

    # if run doesn't match first entry but matches second, index should be returned
    calIndexList2 = [
        {"timestamp": "2026-01-02T00:00:00Z", "appliesTo": ">=70000"},
        {"timestamp": "2025-12-31T00:00:00Z", "appliesTo": "<=64413"},
    ]
    idx2 = ssm.matchingCalibrationIndex(calIndexList2, 64413)
    assert idx2 == 1


def test_matchingCalibrationIndex_requiredCycle():
    # When requiredCycleID provided and entry has mismatched cycleID, it should be skipped
    calIndexList = [
        {"timestamp": "2026-01-02T00:00:00Z", "appliesTo": ">=1", "cycleID": "2025-A"},
    ]
    # requiredCycleID doesn't match, should return None
    idx = ssm.matchingCalibrationIndex(calIndexList, 10, requiredCycleID="2024-B")
    assert idx is None


def test_VBRunNumberFromVersion(tmp_path):
    # Create a fake normalization record
    calFolder = str(tmp_path) + os.sep
    vdir = os.path.join(calFolder, 'v_0003')
    os.makedirs(vdir, exist_ok=True)
    norm_path = os.path.join(vdir, 'NormalizationRecord.json')
    with open(norm_path, 'w') as fh:
        json.dump({"backgroundRunNumber": 12345}, fh)

    calDict = {"version": 3}
    vb = ssm.VBRunNumberFromVersion(calDict, calFolder)
    assert vb == 12345
