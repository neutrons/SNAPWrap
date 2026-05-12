"""Tests for snapwrap._inspectrum.peakfinding."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from snapwrap._inspectrum.peakfinding import PeakTable, find_peaks_in_spectrum

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gaussian(
    x: np.ndarray, centre: float, amplitude: float, sigma: float
) -> np.ndarray:
    """Create a Gaussian peak."""
    return amplitude * np.exp(-0.5 * ((x - centre) / sigma) ** 2)


def _synthetic_spectrum(
    n_points: int = 500,
    d_range: tuple[float, float] = (0.8, 2.5),
    peak_params: list[tuple[float, float, float]] | None = None,
    noise_sigma: float = 0.0,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """Build a synthetic d-spacing spectrum with Gaussian peaks.

    Args:
        n_points: Number of data points.
        d_range: (d_min, d_max).
        peak_params: List of (centre, amplitude, sigma) tuples.
        noise_sigma: Gaussian noise standard deviation.
        seed: RNG seed.

    Returns:
        (x, y) arrays.
    """
    x = np.linspace(d_range[0], d_range[1], n_points)
    y = np.zeros_like(x)
    if peak_params is None:
        peak_params = [
            (1.0, 50.0, 0.015),
            (1.5, 30.0, 0.020),
            (2.0, 40.0, 0.018),
        ]
    for centre, amp, sig in peak_params:
        y += _make_gaussian(x, centre, amp, sig)
    if noise_sigma > 0:
        rng = np.random.default_rng(seed)
        y += rng.normal(0, noise_sigma, size=len(y))
    return x, y


# ---------------------------------------------------------------------------
# PeakTable
# ---------------------------------------------------------------------------


class TestPeakTable:

    def test_n_peaks(self):
        pt = PeakTable(
            positions=np.array([1.0, 2.0]),
            heights=np.array([10.0, 20.0]),
            prominences=np.array([5.0, 10.0]),
            fwhm=np.array([0.01, 0.02]),
            indices=np.array([10, 50], dtype=np.intp),
        )
        assert pt.n_peaks == 2

    def test_empty_table(self):
        pt = PeakTable(
            positions=np.array([]),
            heights=np.array([]),
            prominences=np.array([]),
            fwhm=np.array([]),
            indices=np.array([], dtype=np.intp),
        )
        assert pt.n_peaks == 0

    def test_repr(self):
        pt = PeakTable(
            positions=np.array([1.0]),
            heights=np.array([10.0]),
            prominences=np.array([5.0]),
            fwhm=np.array([0.01]),
            indices=np.array([10], dtype=np.intp),
        )
        assert "n_peaks=1" in repr(pt)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:

    def test_mismatched_lengths_raises(self):
        with pytest.raises(ValueError, match="equal length"):
            find_peaks_in_spectrum(np.array([1, 2, 3.0]), np.array([1, 2.0]))

    def test_too_few_points_raises(self):
        with pytest.raises(ValueError, match="at least 3"):
            find_peaks_in_spectrum(np.array([1.0, 2.0]), np.array([1.0, 2.0]))


# ---------------------------------------------------------------------------
# Synthetic spectra — clean
# ---------------------------------------------------------------------------


class TestSyntheticClean:
    """Test peak finding on clean (noiseless) synthetic data."""

    def test_finds_three_peaks(self):
        x, y = _synthetic_spectrum()
        pt = find_peaks_in_spectrum(x, y)
        assert pt.n_peaks == 3

    def test_peak_positions_accurate(self):
        centres = [1.0, 1.5, 2.0]
        x, y = _synthetic_spectrum(peak_params=[(c, 50.0, 0.015) for c in centres])
        pt = find_peaks_in_spectrum(x, y)
        for expected in centres:
            diffs = np.abs(pt.positions - expected)
            assert np.min(diffs) < 0.01, (
                f"Expected peak near {expected}, "
                f"closest was {pt.positions[np.argmin(diffs)]:.4f}"
            )

    def test_sorted_decreasing_d(self):
        x, y = _synthetic_spectrum()
        pt = find_peaks_in_spectrum(x, y)
        assert np.all(np.diff(pt.positions) <= 0)

    def test_heights_positive(self):
        x, y = _synthetic_spectrum()
        pt = find_peaks_in_spectrum(x, y)
        assert np.all(pt.heights > 0)

    def test_fwhm_reasonable(self):
        """FWHM should be close to 2.355 × sigma for Gaussian peaks."""
        sigma = 0.015
        x, y = _synthetic_spectrum(
            peak_params=[(1.5, 50.0, sigma)],
            n_points=2000,  # fine grid for accuracy
        )
        pt = find_peaks_in_spectrum(x, y, min_width_pts=3)
        expected_fwhm = 2.3548 * sigma
        assert pt.n_peaks == 1
        assert (
            abs(pt.fwhm[0] - expected_fwhm) < 0.005
        ), f"FWHM={pt.fwhm[0]:.4f}, expected ≈{expected_fwhm:.4f}"

    def test_centroid_subpixel_accuracy(self):
        """Centroid should be more accurate than grid spacing."""
        # Place peak at 1.503 — between grid points
        centre = 1.503
        x, y = _synthetic_spectrum(
            peak_params=[(centre, 50.0, 0.015)],
            n_points=500,
        )
        pt = find_peaks_in_spectrum(x, y, min_width_pts=3)
        assert pt.n_peaks == 1
        grid_spacing = (2.5 - 0.8) / 500  # 0.0034
        # Centroid error should be much less than grid spacing
        assert abs(pt.positions[0] - centre) < grid_spacing / 2


# ---------------------------------------------------------------------------
# Synthetic spectra — noisy
# ---------------------------------------------------------------------------


class TestSyntheticNoisy:
    """Test peak finding on noisy synthetic data."""

    def test_finds_peaks_in_noise(self):
        x, y = _synthetic_spectrum(noise_sigma=1.0)
        pt = find_peaks_in_spectrum(x, y)
        # Should still find the 3 main peaks despite noise
        assert pt.n_peaks >= 3

    def test_no_spurious_peaks_in_noise_only(self):
        """Pure noise should produce far fewer peaks than signal+noise."""
        rng = np.random.default_rng(99)
        x = np.linspace(0.8, 2.5, 500)
        # Non-negative noise (mimics background-subtracted baseline)
        y = np.abs(rng.normal(0, 1.0, size=500))
        pt = find_peaks_in_spectrum(x, y)
        # Some noise peaks may survive, but far fewer than a real spectrum
        assert pt.n_peaks <= 5

    def test_strong_peaks_found_in_heavy_noise(self):
        x, y = _synthetic_spectrum(
            peak_params=[(1.5, 100.0, 0.02)],
            noise_sigma=5.0,
        )
        pt = find_peaks_in_spectrum(x, y)
        assert pt.n_peaks >= 1
        assert np.min(np.abs(pt.positions - 1.5)) < 0.02


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:

    def test_flat_signal_no_peaks(self):
        x = np.linspace(0.8, 2.5, 100)
        y = np.ones_like(x) * 10.0
        pt = find_peaks_in_spectrum(x, y)
        assert pt.n_peaks == 0

    def test_single_peak(self):
        x, y = _synthetic_spectrum(
            peak_params=[(1.5, 50.0, 0.02)],
        )
        pt = find_peaks_in_spectrum(x, y)
        assert pt.n_peaks == 1
        assert abs(pt.positions[0] - 1.5) < 0.01

    def test_explicit_prominence_threshold(self):
        """Lower prominence threshold should find more peaks."""
        x, y = _synthetic_spectrum(
            peak_params=[
                (1.0, 50.0, 0.015),
                (1.5, 5.0, 0.015),  # weak peak
                (2.0, 50.0, 0.015),
            ],
        )
        # High threshold: miss the weak peak
        pt_high = find_peaks_in_spectrum(x, y, min_prominence=10.0)
        assert pt_high.n_peaks == 2

        # Low threshold: catch it
        pt_low = find_peaks_in_spectrum(x, y, min_prominence=1.0)
        assert pt_low.n_peaks == 3

    def test_closely_spaced_peaks(self):
        x, y = _synthetic_spectrum(
            peak_params=[
                (1.50, 50.0, 0.010),
                (1.55, 40.0, 0.010),
            ],
            n_points=1000,
        )
        pt = find_peaks_in_spectrum(x, y, min_distance_pts=2)
        assert pt.n_peaks == 2

    def test_indices_correspond_to_positions(self):
        """Centroid positions should be close to the apex positions."""
        x, y = _synthetic_spectrum()
        pt = find_peaks_in_spectrum(x, y)
        for i in range(pt.n_peaks):
            # Centroid should be within one local grid spacing of the apex
            local_dx = abs(x[1] - x[0])
            assert abs(pt.positions[i] - x[pt.indices[i]]) < local_dx


# ---------------------------------------------------------------------------
# Real data (SNAP)
# ---------------------------------------------------------------------------


class TestSNAPData:
    """Integration tests on real SNAP diffraction data."""

    @pytest.fixture()
    def snap_data(self):
        from snapwrap._inspectrum.background import estimate_background
        from snapwrap._inspectrum.loaders import load_mantid_csv

        spectra = load_mantid_csv(str(Path(__file__).parent / "test_data" / "SNAP059056_all_test-0.csv"))
        s = spectra[0]
        bg, peaks_y = estimate_background(s.y)
        return s.x, peaks_y

    def test_finds_peaks(self, snap_data):
        x, y = snap_data
        pt = find_peaks_in_spectrum(x, y)
        # Expect several real peaks (tungsten + ice VII)
        assert pt.n_peaks >= 5

    def test_no_excessive_peaks(self, snap_data):
        x, y = snap_data
        pt = find_peaks_in_spectrum(x, y)
        # With 5σ auto-threshold, real SNAP data should produce ≤10
        assert pt.n_peaks <= 10

    def test_positions_within_data_range(self, snap_data):
        x, y = snap_data
        pt = find_peaks_in_spectrum(x, y)
        assert np.all(pt.positions >= x.min())
        assert np.all(pt.positions <= x.max())

    def test_fwhm_positive(self, snap_data):
        x, y = snap_data
        pt = find_peaks_in_spectrum(x, y)
        assert np.all(pt.fwhm > 0)

    def test_sorted_decreasing(self, snap_data):
        x, y = snap_data
        pt = find_peaks_in_spectrum(x, y)
        assert np.all(np.diff(pt.positions) <= 0)
