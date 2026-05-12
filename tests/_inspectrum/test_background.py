"""
Tests for the background estimation module.

Tests the rolling-ball peak-clipping technique using both synthetic
data (where the true background is known) and real SNAP fixtures.
"""

from pathlib import Path

import numpy as np
import pytest

from snapwrap._inspectrum.background import (
    _inv_lls_transform,
    _lls_transform,
    _smooth,
    estimate_background,
)

TEST_DATA = Path(__file__).parent / "test_data"


# ---------------------------------------------------------------------------
# LLS transformation
# ---------------------------------------------------------------------------


class TestLLSTransform:
    """Tests for the Log-Log-Square transformation and its inverse."""

    def test_round_trip_small_values(self):
        """LLS → inv_LLS should recover original data."""
        data = np.array([0.0, 1.0, 10.0, 100.0])
        result = _inv_lls_transform(_lls_transform(data))
        np.testing.assert_allclose(result, data, atol=1e-10)

    def test_round_trip_large_values(self):
        """Round-trip works for large values (dynamic range test)."""
        data = np.array([1e2, 1e4, 1e6])
        result = _inv_lls_transform(_lls_transform(data))
        np.testing.assert_allclose(result, data, rtol=1e-8)

    def test_lls_is_monotonic(self):
        """LLS transform preserves ordering."""
        data = np.array([1.0, 10.0, 100.0, 1000.0])
        transformed = _lls_transform(data)
        assert np.all(np.diff(transformed) > 0)

    def test_lls_compresses_range(self):
        """LLS should reduce the dynamic range."""
        data = np.array([1.0, 1000.0])
        transformed = _lls_transform(data)
        original_range = data[-1] - data[0]
        compressed_range = transformed[-1] - transformed[0]
        assert compressed_range < original_range


# ---------------------------------------------------------------------------
# Smoothing
# ---------------------------------------------------------------------------


class TestSmooth:
    """Tests for triangle-weighted smoothing."""

    def test_smooth_preserves_length(self):
        data = np.random.default_rng(42).normal(100.0, 5.0, 200)
        result = _smooth(data, order=5.0)
        assert len(result) == len(data)

    def test_smooth_reduces_noise(self):
        """Smoothed data should have lower variance than noisy input."""
        rng = np.random.default_rng(42)
        data = 100.0 + rng.normal(0, 10.0, 500)
        result = _smooth(data, order=5.0)
        assert np.std(result) < np.std(data)

    def test_smooth_order_one_is_identity(self):
        """order=1.0 gives half-width 0, so output == input."""
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = _smooth(data, order=1.0)
        np.testing.assert_array_almost_equal(result, data)

    def test_smooth_preserves_mean(self):
        """Smoothing should approximately preserve the mean."""
        rng = np.random.default_rng(42)
        data = 100.0 + rng.normal(0, 5.0, 500)
        result = _smooth(data, order=5.0)
        np.testing.assert_allclose(
            np.mean(result[50:-50]), np.mean(data[50:-50]), rtol=0.05
        )


# ---------------------------------------------------------------------------
# estimate_background — synthetic data
# ---------------------------------------------------------------------------


class TestEstimateBackgroundSynthetic:
    """Tests with synthetic data where the true background is known."""

    def test_flat_background_with_peaks(self):
        """Peaks on a flat background should be cleanly separated."""
        n = 500
        x = np.linspace(0, 10, n)
        true_bg = np.full(n, 50.0)
        # Add three Gaussian peaks
        peaks_true = (
            20.0 * np.exp(-0.5 * ((x - 3.0) / 0.1) ** 2)
            + 30.0 * np.exp(-0.5 * ((x - 5.0) / 0.15) ** 2)
            + 15.0 * np.exp(-0.5 * ((x - 7.0) / 0.1) ** 2)
        )
        data = true_bg + peaks_true

        bg, peaks = estimate_background(data, win_size=30, lls=False, smoothing=0)

        # Background should be close to 50 away from peaks
        away_from_peaks = (x < 2.5) | ((x > 3.5) & (x < 4.5)) | (x > 7.5)
        np.testing.assert_allclose(bg[away_from_peaks], 50.0, atol=5.0)

    def test_sloped_background(self):
        """Should track a linearly sloped background."""
        n = 400
        x = np.linspace(0, 10, n)
        true_bg = 30.0 + 4.0 * x  # slope from 30 to 70
        peaks_true = 20.0 * np.exp(-0.5 * ((x - 5.0) / 0.2) ** 2)
        data = true_bg + peaks_true

        bg, peaks = estimate_background(data, win_size=25, lls=False, smoothing=0)

        # Check background tracks the slope at the endpoints
        assert bg[10] == pytest.approx(true_bg[10], abs=8.0)
        assert bg[-10] == pytest.approx(true_bg[-10], abs=8.0)

    def test_output_shapes_match_input(self):
        """Background and peaks arrays have same shape as input."""
        data = np.random.default_rng(42).normal(100.0, 5.0, 300)
        bg, peaks = estimate_background(data, win_size=20)
        assert bg.shape == data.shape
        assert peaks.shape == data.shape

    def test_background_plus_peaks_close_to_original(self):
        """bg + peaks should approximately equal the original data."""
        data = np.random.default_rng(42).normal(100.0, 5.0, 300)
        bg, peaks = estimate_background(data, win_size=20, lls=False, smoothing=0)
        np.testing.assert_allclose(bg + peaks, data, atol=1e-8)


# ---------------------------------------------------------------------------
# estimate_background — real SNAP data
# ---------------------------------------------------------------------------


class TestEstimateBackgroundSNAP:
    """Tests with real SNAP high-pressure diffraction data."""

    @pytest.fixture
    def snap_y(self):
        from snapwrap._inspectrum.loaders import load_mantid_csv

        spectra = load_mantid_csv(TEST_DATA / "SNAP059056_all_test-0.csv")
        return spectra[0].y

    def test_background_is_finite(self, snap_y):
        bg, peaks = estimate_background(snap_y)
        assert np.all(np.isfinite(bg))
        assert np.all(np.isfinite(peaks))

    def test_background_below_data(self, snap_y):
        """Background should not exceed the data (within tolerance)."""
        bg, _ = estimate_background(snap_y)
        excess = np.sum(bg > snap_y * 1.05)
        assert excess == 0

    def test_peaks_are_non_negative_mostly(self, snap_y):
        """Most peak values should be non-negative."""
        _, peaks = estimate_background(snap_y)
        negative_fraction = np.sum(peaks < -1.0) / len(peaks)
        assert negative_fraction < 0.05

    def test_bg_plus_peaks_equals_data(self, snap_y):
        """bg + peaks should exactly equal the original."""
        bg, peaks = estimate_background(snap_y)
        np.testing.assert_allclose(bg + peaks, snap_y, atol=1e-8)
