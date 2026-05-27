"""Tests for postprocessing.py — pure-Python/numpy layer only.

These tests cover the functions that do not require a live Mantid session:
  _parse_spectra_list  — tokenises spectraLst strings
  _load_notches        — reads swiss-cheese JSON into notch tuples
  _find_zero_runs      — identifies contiguous near-zero regions in a spectrum

Test groups
-----------
P1  _parse_spectra_list
P2  _load_notches
P3  _find_zero_runs
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from snapwrap.reduction_artefacts.postprocessing import (
    _find_zero_runs,
    _load_notches,
    _parse_spectra_list,
)


# ---------------------------------------------------------------------------
# Lightweight workspace stub — no Mantid required
# ---------------------------------------------------------------------------


class _FakeWS:
    """Minimal workspace stub with histogram-style x/y arrays."""

    def __init__(self, x: np.ndarray, y: np.ndarray):
        self._x = np.asarray(x, dtype=float)
        self._y = np.asarray(y, dtype=float)

    def readX(self, i: int) -> np.ndarray:  # noqa: N802
        return self._x

    def readY(self, i: int) -> np.ndarray:  # noqa: N802
        return self._y


# ---------------------------------------------------------------------------
# P1 — _parse_spectra_list
# ---------------------------------------------------------------------------


class TestParseSpectraList:
    def test_empty_string_returns_empty(self):
        assert _parse_spectra_list("") == []

    def test_single_integer(self):
        result = _parse_spectra_list("100")
        assert result == [range(100, 101)]
        assert 100 in result[0]
        assert 99 not in result[0]
        assert 101 not in result[0]

    def test_comma_separated_integers(self):
        result = _parse_spectra_list("7661,7662,7663")
        assert result == [range(7661, 7662), range(7662, 7663), range(7663, 7664)]

    def test_range_notation(self):
        result = _parse_spectra_list("0-18431")
        assert result == [range(0, 18432)]
        assert 0 in result[0]
        assert 18431 in result[0]
        assert 18432 not in result[0]

    def test_mixed_integers_and_ranges(self):
        result = _parse_spectra_list("100,200-205,300")
        assert len(result) == 3
        assert result[0] == range(100, 101)
        assert result[1] == range(200, 206)
        assert result[2] == range(300, 301)

    def test_whitespace_around_tokens(self):
        result = _parse_spectra_list(" 10 , 20 ")
        assert result == [range(10, 11), range(20, 21)]

    def test_malformed_token_skipped(self):
        result = _parse_spectra_list("abc,10,xyz")
        assert result == [range(10, 11)]

    def test_malformed_range_skipped(self):
        result = _parse_spectra_list("a-b,5")
        assert result == [range(5, 6)]


# ---------------------------------------------------------------------------
# P2 — _load_notches
# ---------------------------------------------------------------------------


class TestLoadNotches:
    def test_basic_notches_with_spectra_lsts(self, tmp_path: Path):
        data = {
            "xmins": [0.5, 1.5],
            "xmaxs": [0.8, 2.0],
            "spectraLsts": ["100,200-205", ""],
        }
        mask_file = tmp_path / "mask_Wavelength.json"
        mask_file.write_text(json.dumps(data), encoding="utf-8")

        result = _load_notches(mask_file)

        assert len(result) == 2
        xmin0, xmax0, ranges0 = result[0]
        assert math.isclose(xmin0, 0.5)
        assert math.isclose(xmax0, 0.8)
        assert range(100, 101) in ranges0
        assert range(200, 206) in ranges0

        xmin1, xmax1, ranges1 = result[1]
        assert math.isclose(xmin1, 1.5)
        assert math.isclose(xmax1, 2.0)
        assert ranges1 == []  # empty spectraLst → all detectors

    def test_no_spectra_lsts_key(self, tmp_path: Path):
        data = {"xmins": [0.3], "xmaxs": [0.6]}
        mask_file = tmp_path / "mask_dSpacing.json"
        mask_file.write_text(json.dumps(data), encoding="utf-8")

        result = _load_notches(mask_file)

        assert len(result) == 1
        _, _, ranges = result[0]
        assert ranges == []

    def test_values_are_float(self, tmp_path: Path):
        data = {"xmins": [1], "xmaxs": [2], "spectraLsts": [""]}
        mask_file = tmp_path / "mask_Wavelength.json"
        mask_file.write_text(json.dumps(data), encoding="utf-8")

        xmin, xmax, _ = _load_notches(mask_file)[0]
        assert isinstance(xmin, float)
        assert isinstance(xmax, float)

    def test_range_notation_in_spectra_lst(self, tmp_path: Path):
        data = {"xmins": [0.4], "xmaxs": [0.7], "spectraLsts": ["0-18431"]}
        mask_file = tmp_path / "mask_Wavelength.json"
        mask_file.write_text(json.dumps(data), encoding="utf-8")

        _, _, ranges = _load_notches(mask_file)[0]
        assert ranges == [range(0, 18432)]


# ---------------------------------------------------------------------------
# P3 — _find_zero_runs
# ---------------------------------------------------------------------------


class TestFindZeroRuns:
    def _ws(self, y_vals: list[float], n_bins: int | None = None) -> _FakeWS:
        """Build a FakeWS with uniform x spacing [0, 1, 2, …]."""
        y = np.array(y_vals, dtype=float)
        n = len(y) if n_bins is None else n_bins
        x = np.arange(n + 1, dtype=float)
        return _FakeWS(x, y)

    def test_all_ones_no_gaps(self):
        ws = self._ws([1.0, 1.0, 1.0, 1.0, 1.0])
        assert _find_zero_runs(ws, 0) == []

    def test_interior_gap(self):
        # bins 1 and 2 are zero → gap from x[1]=1.0 to x[3]=3.0
        ws = self._ws([1.0, 0.0, 0.0, 1.0, 1.0])
        gaps = _find_zero_runs(ws, 0)
        assert len(gaps) == 1
        assert math.isclose(gaps[0][0], 1.0)
        assert math.isclose(gaps[0][1], 3.0)

    def test_left_edge_gap(self):
        # bins 0 and 1 are zero
        ws = self._ws([0.0, 0.0, 1.0, 1.0, 1.0])
        gaps = _find_zero_runs(ws, 0)
        assert len(gaps) == 1
        assert math.isclose(gaps[0][0], 0.0)
        assert math.isclose(gaps[0][1], 2.0)

    def test_right_edge_gap(self):
        # bins 3 and 4 are zero
        ws = self._ws([1.0, 1.0, 1.0, 0.0, 0.0])
        gaps = _find_zero_runs(ws, 0)
        assert len(gaps) == 1
        assert math.isclose(gaps[0][0], 3.0)
        assert math.isclose(gaps[0][1], 5.0)

    def test_multiple_disjoint_gaps(self):
        # bins 0, 2, 4 are zero — three single-bin gaps
        ws = self._ws([0.0, 1.0, 0.0, 1.0, 0.0, 1.0])
        gaps = _find_zero_runs(ws, 0)
        assert len(gaps) == 3
        assert math.isclose(gaps[0][0], 0.0) and math.isclose(gaps[0][1], 1.0)
        assert math.isclose(gaps[1][0], 2.0) and math.isclose(gaps[1][1], 3.0)
        assert math.isclose(gaps[2][0], 4.0) and math.isclose(gaps[2][1], 5.0)

    def test_all_zeros(self):
        ws = self._ws([0.0, 0.0, 0.0])
        gaps = _find_zero_runs(ws, 0)
        assert len(gaps) == 1
        assert math.isclose(gaps[0][0], 0.0)
        assert math.isclose(gaps[0][1], 3.0)

    def test_edge_bins_expands_boundaries(self):
        # bins 2,3 are zero: lo=2, hi=4 → with edge_bins=1: x[1], x[5]
        ws = self._ws([1.0, 1.0, 0.0, 0.0, 1.0, 1.0])
        gaps = _find_zero_runs(ws, 0, edge_bins=1)
        assert len(gaps) == 1
        assert math.isclose(gaps[0][0], 1.0)
        assert math.isclose(gaps[0][1], 5.0)

    def test_edge_bins_clamped_at_workspace_boundary(self):
        # bins 0,1 are zero: lo=0, hi=2 → edge_bins=3: x[max(0, -3)] = x[0] = 0.0
        ws = self._ws([0.0, 0.0, 1.0, 1.0, 1.0])
        gaps = _find_zero_runs(ws, 0, edge_bins=3)
        assert len(gaps) == 1
        assert math.isclose(gaps[0][0], 0.0)  # clamped at left
        assert math.isclose(gaps[0][1], 5.0)  # 2+3=5, x[5] = 5.0

    def test_min_coverage_treats_near_zero_as_zero(self):
        # max(y)=10, threshold=0.5*10=5; bins 1,2 have y=0.3 < 5 → treated as zero
        ws = self._ws([10.0, 0.3, 0.3, 10.0, 10.0])
        gaps = _find_zero_runs(ws, 0, min_coverage=0.5)
        assert len(gaps) == 1
        assert math.isclose(gaps[0][0], 1.0)
        assert math.isclose(gaps[0][1], 3.0)

    def test_min_coverage_zero_uses_absolute_threshold(self):
        # With min_coverage=0 (effectively 0), threshold=1e-10; y=0.001 is not zero
        ws = self._ws([1.0, 0.001, 1.0])
        gaps = _find_zero_runs(ws, 0, min_coverage=0.0)
        assert gaps == []

    def test_spectrum_idx_ignored_by_fake_ws(self):
        # _find_zero_runs passes spectrum_idx to readX/readY; FakeWS ignores it.
        # Verify the function works when called with idx != 0.
        ws = self._ws([1.0, 0.0, 1.0])
        gaps = _find_zero_runs(ws, 5)
        assert len(gaps) == 1
