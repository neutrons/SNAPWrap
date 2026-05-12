"""
Instrument resolution for snapwrap._inspectrum.

Parses the pdabc resolution table from a GSAS-II instrument parameter
file and provides utilities to query the expected peak width (FWHM)
at any d-spacing.

The pdabc table stores per-d-spacing calibration data:

- Col 1: d-spacing (Å)
- Col 2: TOF (µs)
- Col 3–4: zeros (unused)
- Col 5: σ_TOF (µs) — Gaussian sigma of the instrumental peak
  profile in TOF units, measured on a NIST strain-free silicon
  standard

To convert σ_TOF to FWHM in d-spacing::

    FWHM_d = 2·√(2·ln2) · σ_TOF / DIFC

Typical usage::

    from snapwrap._inspectrum.loaders import load_instprm
    from snapwrap._inspectrum.resolution import parse_resolution_curve, fwhm_at_d

    inst = load_instprm("SNAP059056_all.instprm")
    d_curve, fwhm_curve = parse_resolution_curve(inst)

    # FWHM at d = 1.5 Å
    fwhm = fwhm_at_d(1.5, d_curve, fwhm_curve)
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from snapwrap._inspectrum.models import Instrument

# 2 * sqrt(2 * ln(2)) — converts Gaussian sigma to FWHM
_SIGMA_TO_FWHM = 2.0 * np.sqrt(2.0 * np.log(2.0))


def parse_resolution_curve(
    instrument: Instrument,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Extract the instrument resolution curve from pdabc data.

    Parses the ``pdabc`` block stored in ``instrument.raw_params``
    and converts σ_TOF values to FWHM in d-spacing using DIFC.

    Only rows where σ_TOF is finite (not NaN) are returned; the
    arrays are sorted by increasing d-spacing.

    Args:
        instrument: Instrument loaded via :func:`load_instprm`.
            Must have ``raw_params["pdabc"]`` and a nonzero ``difC``.

    Returns:
        Tuple of ``(d_values, fwhm_d)`` where both are 1-D arrays
        of the same length, sorted by increasing d-spacing.

    Raises:
        ValueError: If pdabc data is missing, empty, or DIFC is zero.
    """
    pdabc_str = instrument.raw_params.get("pdabc", "")
    if not pdabc_str.strip():
        raise ValueError("No pdabc data in instrument parameters")

    if instrument.difC == 0:
        raise ValueError("DIFC is zero — cannot convert TOF to d-spacing")

    d_vals: list[float] = []
    sigma_vals: list[float] = []

    for line in pdabc_str.strip().split("\n"):
        parts = line.split(",")
        if len(parts) < 5:
            continue
        try:
            d = float(parts[0].strip())
            sigma_str = parts[4].strip()
            if sigma_str.lower() == "nan":
                continue
            sigma = float(sigma_str)
            if not np.isfinite(sigma):
                continue
            d_vals.append(d)
            sigma_vals.append(sigma)
        except (ValueError, IndexError):
            continue

    if not d_vals:
        raise ValueError("No valid resolution data found in pdabc")

    d_arr = np.array(d_vals, dtype=np.float64)
    sigma_arr = np.array(sigma_vals, dtype=np.float64)

    # Convert sigma_TOF → FWHM_d
    fwhm_d = _SIGMA_TO_FWHM * sigma_arr / instrument.difC

    # Ensure sorted by d-spacing
    order = np.argsort(d_arr)
    return d_arr[order], fwhm_d[order]


def fwhm_at_d(
    d: float | NDArray[np.float64],
    d_curve: NDArray[np.float64],
    fwhm_curve: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Interpolate the expected FWHM at given d-spacing(s).

    Uses linear interpolation within the calibration range and
    linear extrapolation outside it.

    Args:
        d: One or more d-spacing values (Å).
        d_curve: d-spacings from :func:`parse_resolution_curve`.
        fwhm_curve: Corresponding FWHM values (Å).

    Returns:
        Interpolated FWHM value(s), same shape as *d*.
    """
    return np.interp(d, d_curve, fwhm_curve)


def fwhm_to_pts(
    d_values: NDArray[np.float64],
    x: NDArray[np.float64],
    d_curve: NDArray[np.float64],
    fwhm_curve: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Convert expected FWHM at each d-spacing to data-point units.

    For each position in *d_values*, looks up the instrument FWHM
    and divides by the local point spacing from array *x* to get
    the expected width in number of data points.

    Args:
        d_values: d-spacing positions to evaluate (Å).
        x: The full x-axis of the spectrum (d-spacing array).
        d_curve: d-spacings from the resolution curve.
        fwhm_curve: FWHM values from the resolution curve.

    Returns:
        Expected FWHM in data-point units at each position.
    """
    fwhm_d = fwhm_at_d(d_values, d_curve, fwhm_curve)

    # Local point spacing: find nearest index in x for each d
    indices = np.searchsorted(x, d_values)
    indices = np.clip(indices, 1, len(x) - 1)
    local_dx = np.abs(x[indices] - x[indices - 1])

    # Avoid division by zero
    local_dx = np.where(local_dx > 0, local_dx, 1e-10)

    return fwhm_d / local_dx


def recommend_parameters(
    spectrum_x: NDArray[np.float64],
    instrument: Instrument,
) -> dict[str, float | int]:
    """Recommend background and peak-finding parameters from the resolution.

    Uses the instrument resolution curve to compute physics-based
    defaults:

    - ``win_size``: background window ≈ 3× the max expected FWHM in
      points, so the rolling ball doesn't clip peaks
    - ``min_width_pts``: minimum peak width ≈ 0.5× the min expected
      FWHM in points over the spectrum range
    - ``smoothing``: kept at 1.0 (minimal, since the resolution
      sets the real scale)

    Args:
        spectrum_x: The x-axis (d-spacing) of the spectrum.
        instrument: Instrument with pdabc resolution data.

    Returns:
        Dict with keys ``win_size``, ``smoothing``, ``min_width_pts``.

    Raises:
        ValueError: If resolution data is unavailable.
    """
    d_curve, fwhm_curve = parse_resolution_curve(instrument)

    # Evaluate resolution at the endpoints and a few interior points
    d_min, d_max = float(spectrum_x.min()), float(spectrum_x.max())
    sample_d = np.linspace(d_min, d_max, 20)
    fwhm_pts = fwhm_to_pts(sample_d, spectrum_x, d_curve, fwhm_curve)

    max_fwhm_pts = float(np.max(fwhm_pts))
    min_fwhm_pts = float(np.min(fwhm_pts))

    # Background window: ~3× the widest expected peak in points
    win_size = max(2, int(np.ceil(3.0 * max_fwhm_pts)))

    # Minimum peak width: ~0.5× the narrowest expected peak
    min_width_pts = max(2, int(np.floor(0.5 * min_fwhm_pts)))

    return {
        "win_size": win_size,
        "smoothing": 1.0,
        "min_width_pts": min_width_pts,
    }
