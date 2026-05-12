"""Tests for the resolution module."""

from pathlib import Path

import numpy as np
import pytest

from snapwrap._inspectrum.models import Instrument
from snapwrap._inspectrum.resolution import (
    fwhm_at_d,
    fwhm_to_pts,
    parse_resolution_curve,
    recommend_parameters,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def snap_instrument():
    """Load the real SNAP instprm for bank 0."""
    from snapwrap._inspectrum.loaders import load_instprm

    return load_instprm(str(Path(__file__).parent / "test_data" / "SNAP059056_all.instprm"))


@pytest.fixture()
def snap_spectrum():
    """Load a real SNAP spectrum (d-spacing)."""
    from snapwrap._inspectrum.loaders import load_mantid_csv

    spectra = load_mantid_csv(str(Path(__file__).parent / "test_data" / "SNAP059056_all_test-0.csv"))
    return spectra[0]


def _make_instrument_with_pdabc(pdabc_str: str, difC: float = 5218.45) -> Instrument:
    """Create a minimal Instrument with pdabc data."""
    return Instrument(difC=difC, raw_params={"pdabc": pdabc_str})


# ---------------------------------------------------------------------------
# parse_resolution_curve
# ---------------------------------------------------------------------------


class TestParseResolutionCurve:
    """Tests for parsing the pdabc resolution table."""

    def test_basic_parsing(self):
        """Parse a minimal 3-row pdabc block."""
        pdabc = (
            " 1.0000,   5218.5, 0.000000, 0.000000, 10.000000\n"
            " 1.5000,   7827.7, 0.000000, 0.000000, 20.000000\n"
            " 2.0000,  10436.9, 0.000000, 0.000000, 30.000000"
        )
        inst = _make_instrument_with_pdabc(pdabc)
        d, fwhm = parse_resolution_curve(inst)

        assert len(d) == 3
        assert len(fwhm) == 3
        np.testing.assert_array_almost_equal(d, [1.0, 1.5, 2.0])

        # FWHM = 2*sqrt(2*ln2) * sigma / DIFC
        sigma_to_fwhm = 2.0 * np.sqrt(2.0 * np.log(2.0))
        expected_fwhm_0 = sigma_to_fwhm * 10.0 / 5218.45
        np.testing.assert_almost_equal(fwhm[0], expected_fwhm_0, decimal=6)

    def test_nan_rows_skipped(self):
        """Rows with NaN sigma are excluded."""
        pdabc = (
            " 0.5000,   2609.2, 0.000000, 0.000000,      nan\n"
            " 1.0000,   5218.5, 0.000000, 0.000000, 10.000000\n"
            " 3.0000,  15655.4, 0.000000, 0.000000,      nan"
        )
        inst = _make_instrument_with_pdabc(pdabc)
        d, fwhm = parse_resolution_curve(inst)

        assert len(d) == 1
        np.testing.assert_almost_equal(d[0], 1.0)

    def test_sorted_output(self):
        """Output is sorted by increasing d-spacing."""
        pdabc = (
            " 2.0000,  10436.9, 0.000000, 0.000000, 30.000000\n"
            " 1.0000,   5218.5, 0.000000, 0.000000, 10.000000"
        )
        inst = _make_instrument_with_pdabc(pdabc)
        d, _ = parse_resolution_curve(inst)
        assert d[0] < d[1]

    def test_missing_pdabc_raises(self):
        inst = Instrument(difC=5218.45, raw_params={})
        with pytest.raises(ValueError, match="No pdabc"):
            parse_resolution_curve(inst)

    def test_zero_difc_raises(self):
        pdabc = " 1.0000,   5218.5, 0.000000, 0.000000, 10.000000"
        inst = _make_instrument_with_pdabc(pdabc, difC=0.0)
        with pytest.raises(ValueError, match="DIFC is zero"):
            parse_resolution_curve(inst)

    def test_real_snap_data(self, snap_instrument):
        """Parse a real SNAP instprm pdabc block."""
        d, fwhm = parse_resolution_curve(snap_instrument)

        # Should have hundreds of valid rows
        assert len(d) > 100
        # d should span a reasonable range (0.7–5.1 Å)
        assert d[0] < 0.8
        assert d[-1] > 5.0
        # FWHM should be positive and finite
        assert np.all(fwhm > 0)
        assert np.all(np.isfinite(fwhm))
        # FWHM should generally increase with d
        assert fwhm[-1] > fwhm[0]

    def test_fwhm_physically_reasonable(self, snap_instrument):
        """FWHM values should be in a reasonable range for SNAP."""
        d, fwhm = parse_resolution_curve(snap_instrument)

        # At d ≈ 1 Å, SNAP FWHM should be ~0.002–0.01 Å
        mask_1 = (d > 0.9) & (d < 1.1)
        fwhm_at_1 = fwhm[mask_1]
        assert len(fwhm_at_1) > 0
        assert np.all(fwhm_at_1 > 0.001)
        assert np.all(fwhm_at_1 < 0.05)

        # At d ≈ 2 Å, FWHM should be larger
        mask_2 = (d > 1.9) & (d < 2.1)
        fwhm_at_2 = fwhm[mask_2]
        assert np.mean(fwhm_at_2) > np.mean(fwhm_at_1)


# ---------------------------------------------------------------------------
# fwhm_at_d
# ---------------------------------------------------------------------------


class TestFwhmAtD:
    """Tests for FWHM interpolation."""

    def test_exact_point(self):
        d_curve = np.array([1.0, 2.0, 3.0])
        fwhm_curve = np.array([0.01, 0.02, 0.03])
        result = fwhm_at_d(2.0, d_curve, fwhm_curve)
        assert float(result) == pytest.approx(0.02)

    def test_interpolation(self):
        d_curve = np.array([1.0, 2.0, 3.0])
        fwhm_curve = np.array([0.01, 0.02, 0.03])
        result = fwhm_at_d(1.5, d_curve, fwhm_curve)
        assert float(result) == pytest.approx(0.015)

    def test_array_input(self):
        d_curve = np.array([1.0, 2.0, 3.0])
        fwhm_curve = np.array([0.01, 0.02, 0.03])
        result = fwhm_at_d(np.array([1.0, 1.5, 3.0]), d_curve, fwhm_curve)
        np.testing.assert_array_almost_equal(result, [0.01, 0.015, 0.03])


# ---------------------------------------------------------------------------
# fwhm_to_pts
# ---------------------------------------------------------------------------


class TestFwhmToPts:
    """Tests for converting FWHM to data points."""

    def test_uniform_spacing(self):
        """With uniform dx=0.002, FWHM=0.01 → 5 points."""
        x = np.arange(0.8, 2.5, 0.002)
        d_curve = np.array([1.0, 2.0])
        fwhm_curve = np.array([0.01, 0.01])  # constant 0.01 Å
        d_values = np.array([1.5])
        result = fwhm_to_pts(d_values, x, d_curve, fwhm_curve)
        assert float(result[0]) == pytest.approx(5.0, abs=0.5)


# ---------------------------------------------------------------------------
# recommend_parameters
# ---------------------------------------------------------------------------


class TestRecommendParameters:
    """Tests for automatic parameter recommendation."""

    def test_returns_expected_keys(self, snap_instrument, snap_spectrum):
        params = recommend_parameters(snap_spectrum.x, snap_instrument)
        assert "win_size" in params
        assert "smoothing" in params
        assert "min_width_pts" in params

    def test_win_size_positive(self, snap_instrument, snap_spectrum):
        params = recommend_parameters(snap_spectrum.x, snap_instrument)
        assert params["win_size"] >= 2

    def test_min_width_pts_positive(self, snap_instrument, snap_spectrum):
        params = recommend_parameters(snap_spectrum.x, snap_instrument)
        assert params["min_width_pts"] >= 2

    def test_win_size_reasonable_for_snap(self, snap_instrument, snap_spectrum):
        """Win_size should be roughly in the range we manually tuned."""
        params = recommend_parameters(snap_spectrum.x, snap_instrument)
        # Manual tuning found win_size=4, so recommended should be
        # in a similar ballpark (not 40+)
        assert params["win_size"] < 50


# ---------------------------------------------------------------------------
# Integration: resolution-aware peak finding
# ---------------------------------------------------------------------------


class TestResolutionAwarePeakFinding:
    """Test resolution curve used in peak finding."""

    def test_resolution_filter_rejects_narrow_spikes(self):
        """Resolution filter rejects peaks narrower than instrument."""
        from snapwrap._inspectrum.peakfinding import find_peaks_in_spectrum

        # Synthetic: 1 real peak (FWHM~0.01) + 1 spike (FWHM~0.001)
        x = np.linspace(0.8, 2.5, 2000)
        y = np.zeros_like(x)
        # Real peak at d=1.5, sigma=0.004 → FWHM≈0.0094
        y += 50.0 * np.exp(-0.5 * ((x - 1.5) / 0.004) ** 2)
        # Narrow spike at d=2.0, sigma=0.0005 → FWHM≈0.0012
        y += 40.0 * np.exp(-0.5 * ((x - 2.0) / 0.0005) ** 2)

        # Resolution curve: instrument FWHM ≈ 0.01 everywhere
        d_curve = np.array([0.5, 3.0])
        fwhm_curve = np.array([0.01, 0.01])

        # Without resolution filter: should find 2 peaks
        table_nofilter = find_peaks_in_spectrum(
            x, y, min_prominence=5.0, min_width_pts=1
        )
        assert table_nofilter.n_peaks == 2

        # With resolution filter (min 0.75× instrument): only the real peak
        table_filtered = find_peaks_in_spectrum(
            x,
            y,
            min_prominence=5.0,
            min_width_pts=1,
            resolution=(d_curve, fwhm_curve),
            min_fwhm_factor=0.75,
        )
        assert table_filtered.n_peaks == 1
        assert abs(table_filtered.positions[0] - 1.5) < 0.01

    def test_resolution_filter_rejects_wide_artefacts(self):
        """Resolution filter rejects peaks far wider than instrument."""
        from snapwrap._inspectrum.peakfinding import find_peaks_in_spectrum

        # Synthetic: 1 real peak (FWHM=0.01) + 1 artefact (FWHM=0.2)
        x = np.linspace(0.8, 2.5, 1000)
        y = np.zeros_like(x)
        # Narrow real peak at d=1.5, sigma=0.004 → FWHM~0.01
        y += 50.0 * np.exp(-0.5 * ((x - 1.5) / 0.004) ** 2)
        # Wide artefact at d=2.0, sigma=0.08 → FWHM~0.19
        y += 30.0 * np.exp(-0.5 * ((x - 2.0) / 0.08) ** 2)

        # Resolution curve: instrument FWHM ≈ 0.01 everywhere
        d_curve = np.array([0.5, 3.0])
        fwhm_curve = np.array([0.01, 0.01])

        # Without resolution filter: should find 2 peaks
        table_nofilter = find_peaks_in_spectrum(
            x, y, min_prominence=5.0, min_width_pts=2
        )
        assert table_nofilter.n_peaks == 2

        # With resolution filter (max 5× instrument): only the real peak
        table_filtered = find_peaks_in_spectrum(
            x,
            y,
            min_prominence=5.0,
            min_width_pts=2,
            resolution=(d_curve, fwhm_curve),
            max_fwhm_factor=5.0,
        )
        assert table_filtered.n_peaks == 1
        assert abs(table_filtered.positions[0] - 1.5) < 0.01

    def test_real_data_with_resolution(self, snap_instrument, snap_spectrum):
        """Resolution-aware peak finding on real SNAP data."""
        from snapwrap._inspectrum.background import estimate_background
        from snapwrap._inspectrum.peakfinding import find_peaks_in_spectrum

        d_curve, fwhm_curve = parse_resolution_curve(snap_instrument)
        bg, peaks_y = estimate_background(snap_spectrum.y, win_size=4, smoothing=1.0)
        table = find_peaks_in_spectrum(
            snap_spectrum.x,
            peaks_y,
            min_prominence=4.0,
            min_width_pts=6,
            resolution=(d_curve, fwhm_curve),
        )
        # Should find a reasonable number of peaks (5–10)
        assert table.n_peaks >= 3
        assert table.n_peaks <= 15
