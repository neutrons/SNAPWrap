"""Tests for postprocessing.py — pure-Python/numpy layer only.

These tests cover the functions that do not require a live Mantid session:
  _parse_spectra_list       — tokenises spectraLst strings
  _load_notches             — reads swiss-cheese JSON into notch tuples
  _find_zero_runs           — identifies contiguous near-zero regions in a spectrum
  compute_clip_background   — ClipPeaks background estimator (per-spectrum)

Test groups
-----------
P1  _parse_spectra_list
P2  _load_notches
P3  _find_zero_runs
P4  compute_clip_background
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
    compute_clip_background,
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

    def getNumberHistograms(self) -> int:  # noqa: N802
        return 1


class _FakeMultiWS:
    """Stub supporting multiple spectra with independent x/y arrays."""

    def __init__(self, spectra: list[tuple[np.ndarray, np.ndarray]]):
        self._spectra = [
            (np.asarray(x, dtype=float), np.asarray(y, dtype=float))
            for x, y in spectra
        ]

    def getNumberHistograms(self) -> int:  # noqa: N802
        return len(self._spectra)

    def readX(self, i: int) -> np.ndarray:  # noqa: N802
        return self._spectra[i][0]

    def readY(self, i: int) -> np.ndarray:  # noqa: N802
        return self._spectra[i][1]


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

    def test_edge_dspacing_expands_boundaries(self):
        # bins 2,3 are zero (x∈[2,4]); edge_dspacing=1.0 Å expands to x∈[1,5]
        ws = self._ws([1.0, 1.0, 0.0, 0.0, 1.0, 1.0])
        gaps = _find_zero_runs(ws, 0, edge_dspacing=1.0)
        assert len(gaps) == 1
        assert math.isclose(gaps[0][0], 1.0)
        assert math.isclose(gaps[0][1], 5.0)

    def test_edge_dspacing_clamped_at_workspace_boundary(self):
        # bins 0,1 are zero (x∈[0,2]); edge_dspacing=3.0 Å: left clamped at 0.0
        ws = self._ws([0.0, 0.0, 1.0, 1.0, 1.0])
        gaps = _find_zero_runs(ws, 0, edge_dspacing=3.0)
        assert len(gaps) == 1
        assert math.isclose(gaps[0][0], 0.0)  # clamped at left edge
        assert math.isclose(gaps[0][1], 5.0)  # 2.0 + 3.0 = 5.0

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


# ---------------------------------------------------------------------------
# P4 — compute_clip_background
# ---------------------------------------------------------------------------


class TestComputeClipBackground:
    """Tests for the ClipPeaks background estimator.

    All tests use _FakeWS / _FakeMultiWS — no Mantid required.
    The win_dspacing→win_size conversion is exercised implicitly through the
    searchsorted midpoint logic.
    """

    def _ws(self, y_vals: list[float], n_bins: int | None = None) -> _FakeWS:
        """Build a FakeWS with uniform x spacing [0, 1, 2, …]."""
        y = np.array(y_vals, dtype=float)
        n = len(y) if n_bins is None else n_bins
        x = np.arange(n + 1, dtype=float)
        return _FakeWS(x, y)

    def test_returns_one_array_per_spectrum(self):
        ws = _FakeMultiWS([
            (np.arange(51, dtype=float), np.ones(50, dtype=float)),
            (np.arange(51, dtype=float), np.ones(50, dtype=float) * 2.0),
        ])
        bgs = compute_clip_background(ws, win_dspacing=5.0)
        assert len(bgs) == 2
        assert len(bgs[0]) == 50
        assert len(bgs[1]) == 50

    def test_flat_spectrum_background_approximates_level(self):
        # Flat data at level 1.0 — background should be close to 1.0 everywhere
        ws = self._ws([1.0] * 100)
        bgs = compute_clip_background(ws, win_dspacing=10.0)
        assert np.allclose(bgs[0], 1.0, atol=0.05)

    def test_peak_is_clipped(self):
        # Background level 1.0 with a narrow peak; ClipPeaks should return ~1.0
        y = np.ones(200, dtype=float)
        y[95:105] = 20.0
        ws = self._ws(list(y))
        bgs = compute_clip_background(ws, win_dspacing=15.0)
        # Background outside the peak region should still be close to 1.0
        bg = bgs[0]
        assert np.allclose(bg[:90], 1.0, atol=0.1)
        assert np.allclose(bg[110:], 1.0, atol=0.1)

    def test_win_dspacing_zero_raises_or_uses_min_window(self):
        # win_dspacing=0.0 → searchsorted gives right==mid → win_size=max(1,0)=1
        # Should not crash; win_size is clamped to 1
        ws = self._ws([1.0] * 50)
        bgs = compute_clip_background(ws, win_dspacing=0.0)
        assert len(bgs) == 1

    def test_win_dspacing_converts_to_bins_at_midpoint(self):
        # Uniform x=[0,1,...,100], midpoint=50, win_dspacing=10 → win_size=10
        # Verify the function runs and returns correct length
        x = np.arange(101, dtype=float)
        y = np.ones(100, dtype=float)
        ws = _FakeMultiWS([(x, y)])
        bgs = compute_clip_background(ws, win_dspacing=10.0)
        assert len(bgs[0]) == 100

    def test_background_bounded_by_data_maximum(self):
        # The rolling-sphere background should not exceed the overall data maximum
        # (point-wise exceedances can occur due to the normalisation step in the
        # algorithm, but the global maximum should be respected)
        rng = np.random.default_rng(42)
        y = rng.uniform(0.5, 2.0, 150) + np.sin(np.linspace(0, 4 * np.pi, 150))
        y = np.clip(y, 0.1, None)
        ws = self._ws(list(y))
        bgs = compute_clip_background(ws, win_dspacing=10.0)
        assert float(np.max(bgs[0])) <= float(np.max(y)) + 0.01

    def test_nan_gap_bins_do_not_produce_zero_background(self):
        # Regression: when interior bins are NaN (gap regions after cropping),
        # the background must still reflect the true signal level, not collapse
        # to zero because the normalisation index landed on a zero bin.
        y = np.ones(200, dtype=float)
        y[95:105] = np.nan  # interior NaN gap (notch)
        ws = self._ws(list(y))
        bgs = compute_clip_background(ws, win_dspacing=10.0)
        bg = bgs[0]
        # Background at valid bins should be close to 1.0, NOT zero
        valid = np.isfinite(y)
        assert np.allclose(bg[valid], 1.0, atol=0.1), (
            f"Background collapsed to near-zero: max={np.max(bg[valid]):.4f}"
        )

    def test_nan_only_spectrum_returns_zeros(self):
        # All-NaN spectrum (degenerate case) → zeros background, no crash
        y = np.full(50, np.nan)
        ws = self._ws(list(y))
        bgs = compute_clip_background(ws, win_dspacing=5.0)
        assert np.all(bgs[0] == 0.0)
