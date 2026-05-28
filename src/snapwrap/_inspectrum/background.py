"""
Background estimation and removal for snapwrap._inspectrum.

Implements the rolling-ball peak-clipping technique for estimating
structured backgrounds in powder diffraction data.  The estimated
background can be subtracted from the observed spectrum to expose
peaks for subsequent peak-finding.

The algorithm iteratively replaces each point with the minimum of
a symmetric rolling window average, tracing the lower envelope of
the spectrum (i.e. the background).

Typical usage::

    from snapwrap._inspectrum.background import estimate_background
    from snapwrap._inspectrum.loaders import load_mantid_csv

    spectra = load_mantid_csv("SNAP059056_all_test-0.csv")
    spectrum = spectra[0]

    background, peaks = estimate_background(spectrum.y)
    # background: estimated structured background
    # peaks: spectrum.y - background (the peak-only signal)
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def estimate_background(
    data: NDArray[np.float64],
    win_size: int = 40,
    decrease: bool = True,
    lls: bool = True,
    smoothing: float = 5.0,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Estimate the structured background using peak clipping.

    Args:
        data: 1D array of intensity values (observed spectrum).
        win_size: Maximum half-window size for the rolling ball.
            Larger values remove broader features.  A good starting
            point is ~5% of the number of data points.
        decrease: If True, scan window sizes from large to small
            (coarse-to-fine); if False, scan small to large.
        lls: If True, apply the Log-Log-Square transformation before
            clipping.  This compresses dynamic range and improves
            background estimation for data with large intensity
            variations.
        smoothing: Width of the Gaussian smoothing kernel applied
            before clipping.  Set to 0 to disable.  Reduces noise
            sensitivity.

    Returns:
        Tuple of (background, peaks) where:
            - background: estimated background signal (same length as data)
            - peaks: data - background (the peak-only component)
    """
    background = _peak_clip(data, win_size, decrease, lls, smoothing)
    peaks = data - background
    return background, peaks


def _peak_clip(
    data: NDArray[np.float64],
    win_size: int,
    decrease: bool,
    lls: bool,
    smoothing: float,
) -> NDArray[np.float64]:
    """Core peak-clipping algorithm (rolling ball background estimator).

    Returns the estimated background — the input spectrum with peaks
    clipped away.  Subtract from the original to isolate peaks.
    """
    start_data = np.copy(data)
    working = np.copy(data).astype(np.float64)

    if smoothing > 0:
        working = _smooth(working, smoothing)

    if lls:
        working = _lls_transform(working)

    temp = working.copy()

    # Scan window sizes: large→small (coarse-to-fine) or small→large
    scan = (
        list(range(win_size + 1, 0, -1)) if decrease else list(range(1, win_size + 1))
    )

    for w in scan:
        for i in range(len(temp)):
            if i < w or i > (len(temp) - w - 1):
                continue
            win_array = temp[i - w : i + w + 1].copy()
            win_reversed = win_array[::-1]
            average = (win_array + win_reversed) / 2.0
            temp[i] = np.min(average[: len(average) // 2])

    if lls:
        temp = _inv_lls_transform(temp)

    # Normalise so the background matches the original at the
    # point of minimum difference (where peak contribution is smallest).
    # Only consider bins where both start_data and temp are finite and positive
    # so that zero-filled gap bins cannot corrupt the reference point.
    diff = start_data - temp
    valid = np.isfinite(diff) & (start_data > 0) & (temp > 0)
    if valid.any():
        index = int(np.argmin(np.where(valid, diff, np.inf)))
    else:
        finite_diff = np.where(np.isfinite(diff), diff, np.inf)
        index = int(np.argmin(finite_diff))
    if temp[index] != 0:
        output = temp * (start_data[index] / temp[index])
    else:
        output = temp

    return output


def _smooth(data: NDArray[np.float64], order: float) -> NDArray[np.float64]:
    """Triangle-weighted smoothing with edge-aware window sizing.

    Uses a triangular kernel of half-width ``int(order / 2)``.
    At the edges the window shrinks to fit, so no zero-padding
    artifacts are introduced.

    This matches the smoothing in SNAPRed's
    ``CreateArtificialNormalizationAlgo`` so the ``smoothing``
    parameter has identical semantics.

    Args:
        data: Input array.
        order: Controls the smoothing width.  The triangle kernel
            half-width is ``int(order / 2)``.  A value of 1.0 gives
            half-width 0 (no smoothing).  5.0 gives half-width 2.

    Returns:
        Smoothed array (same length as input).
    """
    n = len(data)
    sm = np.empty(n, dtype=np.float64)
    half = int(order / 2)
    factor = order / 2 + 1

    for i in range(n):
        lo = max(0, i - half)
        hi = min(i + half, n - 1)
        weights = 0.0
        total = 0.0
        for r in range(lo, hi + 1):
            w = factor - abs(r - i)
            total += w * data[r]
            weights += w
        sm[i] = total / weights

    return sm


def _lls_transform(data: NDArray[np.float64]) -> NDArray[np.float64]:
    r"""Log-Log-Square transformation for dynamic range compression.

    .. math::
        \text{LLS}(x) = \log(\log(\sqrt{x + 1} + 1) + 1)

    This compresses the large intensity range typical of diffraction
    data, making the peak-clipping algorithm more effective across
    both strong and weak features.
    """
    return np.log(np.log(np.sqrt(np.abs(data) + 1) + 1) + 1)


def _inv_lls_transform(data: NDArray[np.float64]) -> NDArray[np.float64]:
    r"""Inverse of the Log-Log-Square transformation.

    .. math::
        \text{LLS}^{-1}(y) = (\exp(\exp(y) - 1) - 1)^2 - 1
    """
    return (np.exp(np.exp(data) - 1) - 1) ** 2 - 1
