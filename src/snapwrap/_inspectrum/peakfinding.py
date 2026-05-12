"""
Peak finding for snapwrap._inspectrum.

Detects peaks in background-subtracted diffraction data and returns
their positions, intensities, and widths in d-spacing units.

Uses :func:`scipy.signal.find_peaks` internally, with defaults tuned
for neutron powder diffraction on SNAP-like instruments (~863 points,
d ~ 0.8–2.5 Å).

Typical usage::

    from snapwrap._inspectrum.loaders import load_mantid_csv
    from snapwrap._inspectrum.background import estimate_background
    from snapwrap._inspectrum.peakfinding import find_peaks_in_spectrum

    spectra = load_mantid_csv("SNAP059056_all_test-0.csv")
    s = spectra[0]
    bg, peaks_y = estimate_background(s.y)
    peak_table = find_peaks_in_spectrum(s.x, peaks_y)

    for i in range(peak_table.n_peaks):
        print(f"d={peak_table.positions[i]:.4f}  "
              f"height={peak_table.heights[i]:.1f}  "
              f"fwhm={peak_table.fwhm[i]:.4f}")
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.signal import find_peaks, peak_prominences, peak_widths

# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

# TODO: Create an ObservedPeak class to hold per-peak data including
# centroid position, FWHM, height, prominence, and (once Rietveld
# matching is implemented) assigned (h,k,l) indices.


@dataclass
class PeakTable:
    """Container for detected peaks.

    All arrays have length ``n_peaks`` and are sorted by decreasing
    d-spacing (lowest-angle first, matching reflection list order).

    Attributes:
        positions: d-spacing (Å) of each peak centre, computed as the
            intensity-weighted centroid within the half-max boundaries.
        heights: Intensity at each peak apex.
        prominences: Prominence of each peak (height above surrounding
            baseline — a robust measure of peak significance).
        fwhm: Full width at half-maximum in d-spacing units (Å).
        indices: Index into the original x/y arrays for each peak.
    """

    positions: NDArray[np.float64]
    heights: NDArray[np.float64]
    prominences: NDArray[np.float64]
    fwhm: NDArray[np.float64]
    indices: NDArray[np.intp]

    @property
    def n_peaks(self) -> int:
        """Number of detected peaks."""
        return len(self.positions)

    def __repr__(self) -> str:
        return f"PeakTable(n_peaks={self.n_peaks})"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_peaks_in_spectrum(
    x: NDArray[np.float64],
    y: NDArray[np.float64],
    *,
    min_prominence: float | None = None,
    noise_sigma_factor: float = 5.0,
    min_width_pts: int = 5,
    min_distance_pts: int = 3,
    resolution: tuple[NDArray[np.float64], NDArray[np.float64]] | None = None,
    max_fwhm_factor: float = 5.0,
    min_fwhm_factor: float = 0.75,
) -> PeakTable:
    """Find peaks in a background-subtracted spectrum.

    Args:
        x: Independent variable (d-spacing in Å).  Must be
            monotonically increasing or decreasing.
        y: Background-subtracted intensity (peak-only signal).
            Same length as *x*.
        min_prominence: Minimum peak prominence (absolute).  Peaks
            below this are rejected.  If ``None`` (default), a
            threshold is estimated automatically as
            *noise_sigma_factor* × the standard deviation of the
            lower quartile of *y*.
        noise_sigma_factor: Multiplier for the automatic prominence
            threshold.  Only used when *min_prominence* is ``None``.
            Default 5.0 (≈ 5 σ above the counting-noise floor).
        min_width_pts: Minimum full-width at half-maximum in data
            points.  Rejects noise spikes narrower than this.
            Default 5 points.
        min_distance_pts: Minimum separation between neighbouring
            peaks in data points.  Default 3.
        resolution: Optional instrument resolution curve as a tuple
            ``(d_curve, fwhm_curve)`` from
            :func:`~snapwrap._inspectrum.resolution.parse_resolution_curve`.
            When provided, peaks are checked against the expected
            instrument FWHM in both directions: too-wide peaks
            (> *max_fwhm_factor* ×) and too-narrow peaks
            (< *min_fwhm_factor* ×) are rejected.
        max_fwhm_factor: Maximum ratio of observed FWHM to
            instrument FWHM.  Only used when *resolution* is
            provided.  Default 5.0.
        min_fwhm_factor: Minimum ratio of observed FWHM to
            instrument FWHM.  Peaks narrower than this are
            rejected as sub-resolution noise spikes.  Only used
            when *resolution* is provided.  Default 0.75.

    Returns:
        :class:`PeakTable` sorted by decreasing d-spacing.

    Raises:
        ValueError: If *x* and *y* have different lengths or fewer
            than 3 points.
    """
    if len(x) != len(y):
        raise ValueError(f"x and y must have equal length, got {len(x)} and {len(y)}")
    if len(x) < 3:
        raise ValueError(f"Need at least 3 data points, got {len(x)}")

    # Ensure we work on a positive-upward signal
    y_work = np.asarray(y, dtype=np.float64)

    # Auto-threshold: noise σ from the lower quartile of the signal.
    # After background subtraction, peak-free regions cluster in the
    # lower quartile.  Their standard deviation is a robust estimate
    # of the counting-noise floor.  We multiply by noise_sigma_factor
    # (default 5) so that only peaks well above the noise survive.
    if min_prominence is None:
        q25 = float(np.percentile(y_work, 25))
        lower_quarter = y_work[y_work <= q25]
        noise_sigma = float(np.std(lower_quarter)) if len(lower_quarter) > 1 else 1.0
        min_prominence = max(noise_sigma_factor * noise_sigma, 1e-10)

    # ---- Find candidate peaks ----
    idx, _ = find_peaks(
        y_work,
        prominence=min_prominence,
        distance=min_distance_pts,
    )

    if len(idx) == 0:
        return _empty_table()

    # ---- Compute properties ----
    proms, _, _ = peak_prominences(y_work, idx)
    widths_pts, _, left_ips, right_ips = peak_widths(y_work, idx, rel_height=0.5)

    # ---- Filter by width ----
    keep = widths_pts >= min_width_pts
    idx = idx[keep]
    proms = proms[keep]
    widths_pts = widths_pts[keep]
    left_ips = left_ips[keep]
    right_ips = right_ips[keep]

    if len(idx) == 0:
        return _empty_table()

    # ---- Convert widths from points to d-spacing ----
    # Use local point spacing at each peak for accurate conversion
    dx = np.abs(np.diff(x))
    # For each peak index, use the local spacing (clamped to valid range)
    local_dx = dx[np.clip(idx, 0, len(dx) - 1)]
    fwhm = widths_pts * local_dx

    # ---- Filter by resolution ----
    # Reject peaks that are unphysically wide (background artefacts)
    # or unphysically narrow (sub-resolution noise spikes).
    if resolution is not None:
        d_curve, fwhm_curve = resolution
        positions_tmp = x[idx]
        expected_fwhm = np.interp(positions_tmp, d_curve, fwhm_curve)
        keep_res = (fwhm <= max_fwhm_factor * expected_fwhm) & (
            fwhm >= min_fwhm_factor * expected_fwhm
        )
        idx = idx[keep_res]
        proms = proms[keep_res]
        widths_pts = widths_pts[keep_res]
        fwhm = fwhm[keep_res]
        left_ips = left_ips[keep_res]
        right_ips = right_ips[keep_res]

    if len(idx) == 0:
        return _empty_table()

    # ---- Compute center-of-mass positions ----
    positions = _centroid_positions(x, y_work, left_ips, right_ips)
    heights = y_work[idx]

    # Sort by decreasing d-spacing (to match reflection list convention)
    order = np.argsort(-positions)
    return PeakTable(
        positions=positions[order],
        heights=heights[order],
        prominences=proms[order],
        fwhm=fwhm[order],
        indices=idx[order],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _centroid_positions(
    x: NDArray[np.float64],
    y: NDArray[np.float64],
    left_ips: NDArray[np.float64],
    right_ips: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Compute intensity-weighted centroid for each peak.

    Uses the half-max boundaries from ``peak_widths`` to define the
    integration window.  Only positive-intensity points contribute,
    preventing noise in the tails from pulling the centroid off-centre.

    Args:
        x: d-spacing array.
        y: Background-subtracted intensity.
        left_ips: Left half-max crossing (fractional index) per peak.
        right_ips: Right half-max crossing (fractional index) per peak.

    Returns:
        Array of centroid d-spacings, one per peak.
    """
    centroids = np.empty(len(left_ips), dtype=np.float64)

    for i in range(len(left_ips)):
        lo = max(0, int(np.floor(left_ips[i])))
        hi = min(len(x), int(np.ceil(right_ips[i])) + 1)

        x_win = x[lo:hi]
        y_win = y[lo:hi]

        # Only positive intensities contribute to the centroid
        mask = y_win > 0
        if np.any(mask):
            centroids[i] = np.sum(x_win[mask] * y_win[mask]) / np.sum(y_win[mask])
        else:
            # Fallback to apex position
            centroids[i] = x_win[len(x_win) // 2]

    return centroids


def _empty_table() -> PeakTable:
    """Return an empty PeakTable."""
    empty = np.array([], dtype=np.float64)
    return PeakTable(
        positions=empty,
        heights=empty,
        prominences=empty,
        fwhm=empty,
        indices=np.array([], dtype=np.intp),
    )
