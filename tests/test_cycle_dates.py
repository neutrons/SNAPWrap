"""Tests for snapwrap.cycleDates

These tests use tmp_path fixtures and mock ``pd.read_excel`` so neither
the ``odf`` library nor a real instrument calibration directory are needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

import snapwrap.cycleDates as cd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _good_rows() -> list[dict]:
    """Return a valid minimal set of cycle rows (in chronological order)."""
    return [
        {"cycleID": "2024-A", "startDate": "2024-01-15", "stopDate": "2024-06-30", "firstRun": 50000},
        {"cycleID": "2024-B", "startDate": "2024-07-15", "stopDate": "2024-12-31", "firstRun": 52000},
        {"cycleID": "2025-A", "startDate": "2025-01-15", "stopDate": "2025-06-30", "firstRun": 55000},
    ]


def _good_rows_reversed() -> list[dict]:
    """Same data as _good_rows but in reverse order (like the real spreadsheet)."""
    return list(reversed(_good_rows()))


def _good_rows_with_future() -> list[dict]:
    """Rows including a future cycle whose firstRun is NaN."""
    return _good_rows() + [
        {"cycleID": "2025-B", "startDate": "2025-07-15", "stopDate": "2025-12-31", "firstRun": float("nan")},
    ]


def _write_json(path: Path, rows: list[dict], version: int = 1) -> str:
    """Write a cycle-dates JSON file and return its path string."""
    jp = str(path / "cycleDates.json")
    payload = {
        "version": version,
        "generated": "2025-01-01T00:00:00",
        "source": str(path / "cycleDates.ods"),
        "cycles": rows,
    }
    with open(jp, "w") as fh:
        json.dump(payload, fh, indent=2)
    return jp


def _ods_sentinel(path: Path) -> str:
    """Create an empty file to satisfy the os.path.isfile check for the .ods."""
    fp = str(path / "cycleDates.ods")
    Path(fp).touch()
    return fp


def _mock_read_excel(rows: list[dict]):
    """Return a side_effect callable that ignores args and returns a DataFrame."""
    def _read(*args, **kwargs):
        return pd.DataFrame(rows)
    return _read


# ---------------------------------------------------------------------------
# Validation tests  (no I/O needed, just DataFrames)
# ---------------------------------------------------------------------------

class TestValidation:

    def test_missing_column_raises(self):
        df = pd.DataFrame([{"cycleID": "A", "startDate": "2024-01-01", "stopDate": "2024-06-01"}])
        with pytest.raises(ValueError, match="missing required columns"):
            cd._validate_dataframe(df)

    def test_empty_dataframe_raises(self):
        df = pd.DataFrame(columns=["cycleID", "startDate", "stopDate", "firstRun"])
        with pytest.raises(ValueError, match="no data rows"):
            cd._validate_dataframe(df)

    def test_bad_date_raises(self):
        df = pd.DataFrame([{
            "cycleID": "X", "startDate": "not-a-date", "stopDate": "2024-06-01", "firstRun": 1
        }])
        with pytest.raises(ValueError, match="not a valid YYYY-MM-DD"):
            cd._validate_dataframe(df)

    def test_stop_before_start_raises(self):
        df = pd.DataFrame([{
            "cycleID": "X", "startDate": "2024-06-01", "stopDate": "2024-01-01", "firstRun": 1
        }])
        with pytest.raises(ValueError, match="stopDate.*< startDate"):
            cd._validate_dataframe(df)

    def test_non_integer_firstRun_raises(self):
        df = pd.DataFrame([{
            "cycleID": "X", "startDate": "2024-01-01", "stopDate": "2024-06-01", "firstRun": "abc"
        }])
        with pytest.raises(ValueError, match="not a valid integer"):
            cd._validate_dataframe(df)

    def test_negative_firstRun_raises(self):
        df = pd.DataFrame([{
            "cycleID": "X", "startDate": "2024-01-01", "stopDate": "2024-06-01", "firstRun": -5
        }])
        with pytest.raises(ValueError, match="positive integer"):
            cd._validate_dataframe(df)

    def test_duplicate_cycleID_raises(self):
        df = pd.DataFrame([
            {"cycleID": "A", "startDate": "2024-01-01", "stopDate": "2024-06-01", "firstRun": 1},
            {"cycleID": "A", "startDate": "2024-07-01", "stopDate": "2024-12-01", "firstRun": 100},
        ])
        with pytest.raises(ValueError, match="duplicate cycleID"):
            cd._validate_dataframe(df)

    def test_overlapping_dates_raises(self):
        df = pd.DataFrame([
            {"cycleID": "A", "startDate": "2024-01-01", "stopDate": "2024-07-01", "firstRun": 1},
            {"cycleID": "B", "startDate": "2024-07-01", "stopDate": "2024-12-01", "firstRun": 100},
        ])
        with pytest.raises(ValueError, match="overlaps"):
            cd._validate_dataframe(df)

    def test_firstRun_not_increasing_raises(self):
        df = pd.DataFrame([
            {"cycleID": "A", "startDate": "2024-01-01", "stopDate": "2024-06-01", "firstRun": 200},
            {"cycleID": "B", "startDate": "2024-07-01", "stopDate": "2024-12-01", "firstRun": 100},
        ])
        with pytest.raises(ValueError, match="must be greater"):
            cd._validate_dataframe(df)

    def test_valid_data_passes(self):
        df = pd.DataFrame(_good_rows())
        records = cd._validate_dataframe(df)
        assert len(records) == 3
        assert records[0]["cycleID"] == "2024-A"
        assert records[-1]["firstRun"] == 55000

    def test_reverse_order_is_sorted(self):
        """Rows supplied in reverse chronological order are sorted correctly."""
        df = pd.DataFrame(_good_rows_reversed())
        records = cd._validate_dataframe(df)
        assert [r["cycleID"] for r in records] == ["2024-A", "2024-B", "2025-A"]

    def test_nan_firstRun_accepted_for_future_cycle(self):
        """A NaN firstRun is allowed (future cycle) and stored as None."""
        df = pd.DataFrame(_good_rows_with_future())
        records = cd._validate_dataframe(df)
        assert len(records) == 4
        future = records[-1]
        assert future["cycleID"] == "2025-B"
        assert future["firstRun"] is None

    def test_pandas_timestamp_dates_accepted(self):
        """Dates arriving as pandas Timestamps (as from .ods read) are handled."""
        rows = [
            {"cycleID": "X", "startDate": pd.Timestamp("2024-01-15"),
             "stopDate": pd.Timestamp("2024-06-30"), "firstRun": 100},
        ]
        records = cd._validate_dataframe(pd.DataFrame(rows))
        assert records[0]["startDate"] == "2024-01-15"


# ---------------------------------------------------------------------------
# build / load / lookup integration tests
# ---------------------------------------------------------------------------

class TestBuildAndLookup:

    def setup_method(self):
        cd.clear_cache()

    @patch("snapwrap.cycleDates.pd.read_excel", side_effect=_mock_read_excel(_good_rows()))
    def test_build_writes_json(self, _mock_read, tmp_path):
        ods = _ods_sentinel(tmp_path)
        json_path = str(tmp_path / "cycleDates.json")

        records = cd.build_cycle_json(ods_path=ods, json_path=json_path)
        assert len(records) == 3

        with open(json_path, "r") as fh:
            payload = json.load(fh)
        assert payload["version"] == 1
        assert len(payload["cycles"]) == 3
        assert "generated" in payload
        assert "source" in payload

    @patch("snapwrap.cycleDates.pd.read_excel", side_effect=_mock_read_excel(_good_rows()))
    def test_version_bumps_on_rebuild(self, _mock_read, tmp_path):
        ods = _ods_sentinel(tmp_path)
        json_path = str(tmp_path / "cycleDates.json")

        cd.build_cycle_json(ods_path=ods, json_path=json_path)
        cd.build_cycle_json(ods_path=ods, json_path=json_path)

        with open(json_path) as fh:
            payload = json.load(fh)
        assert payload["version"] == 2

    @patch("snapwrap.cycleDates.pd.read_excel", side_effect=_mock_read_excel(_good_rows()))
    def test_load_from_json(self, _mock_read, tmp_path):
        ods = _ods_sentinel(tmp_path)
        json_path = str(tmp_path / "cycleDates.json")
        cd.build_cycle_json(ods_path=ods, json_path=json_path)
        cd.clear_cache()

        data = cd.load_cycle_data(json_path=json_path)
        assert len(data) == 3
        assert isinstance(cd.cache_version(), int)

    @patch("snapwrap.cycleDates.pd.read_excel", side_effect=_mock_read_excel(_good_rows()))
    def test_load_uses_cache(self, _mock_read, tmp_path):
        ods = _ods_sentinel(tmp_path)
        json_path = str(tmp_path / "cycleDates.json")
        cd.build_cycle_json(ods_path=ods, json_path=json_path)

        # delete the json to prove cache is used (not re-read)
        Path(json_path).unlink()
        data = cd.load_cycle_data(json_path=json_path)
        assert len(data) == 3

    def test_load_missing_json_raises(self, tmp_path):
        cd.clear_cache()
        with pytest.raises(FileNotFoundError, match="Cycle JSON not found"):
            cd.load_cycle_data(json_path=str(tmp_path / "nope.json"))

    def test_rebuild_flag(self, tmp_path):
        """rebuild=True re-reads the .ods (mocked) and writes a new JSON."""
        rows = _good_rows()
        validated = cd._validate_dataframe(pd.DataFrame(rows))
        json_path = _write_json(tmp_path, validated, version=1)
        cd.load_cycle_data(json_path=json_path)   # prime the cache

        rows_extended = rows + [
            {"cycleID": "2025-B", "startDate": "2025-07-15", "stopDate": "2025-12-31", "firstRun": 58000}
        ]
        ods = _ods_sentinel(tmp_path)
        with patch("snapwrap.cycleDates.pd.read_excel", side_effect=_mock_read_excel(rows_extended)):
            data = cd.load_cycle_data(json_path=json_path, rebuild=True, ods_path=ods)
        assert len(data) == 4


class TestGetCycleForRun:

    def setup_method(self):
        cd.clear_cache()

    def _setup(self, tmp_path) -> str:
        """Write a pre-validated JSON fixture and prime the cache."""
        validated = cd._validate_dataframe(pd.DataFrame(_good_rows()))
        jp = _write_json(tmp_path, validated)
        cd.load_cycle_data(json_path=jp)
        return jp

    def test_run_in_first_cycle(self, tmp_path):
        jp = self._setup(tmp_path)
        assert cd.get_cycle_for_run(50000, json_path=jp) == "2024-A"
        assert cd.get_cycle_for_run(51999, json_path=jp) == "2024-A"

    def test_run_in_second_cycle(self, tmp_path):
        jp = self._setup(tmp_path)
        assert cd.get_cycle_for_run(52000, json_path=jp) == "2024-B"
        assert cd.get_cycle_for_run(54999, json_path=jp) == "2024-B"

    def test_run_in_last_cycle(self, tmp_path):
        jp = self._setup(tmp_path)
        assert cd.get_cycle_for_run(55000, json_path=jp) == "2025-A"
        assert cd.get_cycle_for_run(99999, json_path=jp) == "2025-A"

    def test_run_before_all_cycles(self, tmp_path):
        jp = self._setup(tmp_path)
        assert cd.get_cycle_for_run(1, json_path=jp) is None
        assert cd.get_cycle_for_run(49999, json_path=jp) is None

    def test_run_at_exact_boundary(self, tmp_path):
        jp = self._setup(tmp_path)
        # firstRun of cycle 2 is 52000 → should be in cycle 2
        assert cd.get_cycle_for_run(52000, json_path=jp) == "2024-B"

    def test_accepts_string_run_number(self, tmp_path):
        jp = self._setup(tmp_path)
        assert cd.get_cycle_for_run("53000", json_path=jp) == "2024-B"

    def test_future_cycle_skipped(self, tmp_path):
        """Cycles with null firstRun are ignored during lookup."""
        cd.clear_cache()
        validated = cd._validate_dataframe(pd.DataFrame(_good_rows_with_future()))
        jp = _write_json(tmp_path, validated)
        cd.load_cycle_data(json_path=jp)
        # run 99999 should still map to 2025-A, not the future 2025-B
        assert cd.get_cycle_for_run(99999, json_path=jp) == "2025-A"
