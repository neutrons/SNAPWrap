"""
Core inspection engine for snapwrap._inspectrum.

Orchestrates the full pre-inspection pipeline: background subtraction,
peak finding, pressure sweep, and per-phase lattice refinement.
The main entry point is :func:`inspect`.

Also provides coordinate-transform utilities :func:`d_to_tof` and
:func:`tof_to_d` used throughout the package.

Typical usage::

    from snapwrap._inspectrum.loaders import (
        load_gsa, load_instprm, load_phase_descriptions,
    )
    from snapwrap._inspectrum.engine import inspect

    spectra = load_gsa("data.gsa")
    instrument = load_instprm("data.instprm")
    experiment = load_phase_descriptions("phases.json")

    result = inspect(spectra[0], instrument, experiment)
    for ref in result.refinements:
        print(ref.phase_name, ref.a, ref.pressure_gpa)
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from snapwrap._inspectrum.background import estimate_background
from snapwrap._inspectrum.crystallography import generate_reflections
from snapwrap._inspectrum.lattice import refine_all_phases
from snapwrap._inspectrum.matching import sweep_pressure
from snapwrap._inspectrum.models import (
    DiffractionSpectrum,
    ExperimentDescription,
    InspectionResult,
    Instrument,
)
from snapwrap._inspectrum.peakfinding import find_peaks_in_spectrum
from snapwrap._inspectrum.resolution import fwhm_at_d, parse_resolution_curve

# ---------------------------------------------------------------------------
# Coordinate transforms
# ---------------------------------------------------------------------------


def d_to_tof(d: NDArray[np.float64], instrument: Instrument) -> NDArray[np.float64]:
    """Convert d-spacing (Å) to time-of-flight (µs).

    Uses the GSAS-II relationship:
        TOF = difA·d² + difC·d + Zero

    Args:
        d: Array of d-spacing values in Angstroms.
        instrument: Instrument with difA, difC, zero parameters.

    Returns:
        Array of TOF values in microseconds.
    """
    return instrument.difA * d**2 + instrument.difC * d + instrument.zero


def tof_to_d(tof: NDArray[np.float64], instrument: Instrument) -> NDArray[np.float64]:
    """Convert time-of-flight (µs) to d-spacing (Å).

    Inverts the GSAS-II relationship.  When difA ≈ 0 (common case)
    this simplifies to d = (TOF - Zero) / difC.

    Args:
        tof: Array of TOF values in microseconds.
        instrument: Instrument with difA, difC, zero parameters.

    Returns:
        Array of d-spacing values in Angstroms.
    """
    if abs(instrument.difA) < 1e-12:
        return (tof - instrument.zero) / instrument.difC

    # Solve quadratic: difA·d² + difC·d + (Zero - TOF) = 0
    a = instrument.difA
    b = instrument.difC
    c = instrument.zero - tof
    discriminant = b**2 - 4 * a * c
    discriminant = np.maximum(discriminant, 0.0)
    return (-b + np.sqrt(discriminant)) / (2 * a)


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------


def inspect(
    spectrum: DiffractionSpectrum,
    instrument: Instrument,
    experiment: ExperimentDescription,
    *,
    P_min: float = 0.0,
    P_max: float | None = None,
    n_coarse: int = 301,
    n_fine: int = 201,
    bg_win_size: int = 40,
    noise_sigma_factor: float = 5.0,
    min_fwhm_factor: float = 0.75,
) -> InspectionResult:
    """Run the full pre-inspection pipeline on a single spectrum.

    Pipeline steps:
        1. Convert TOF → d-spacing (if needed)
        2. Estimate and subtract background
        3. Find peaks (with instrument resolution filtering)
        4. Generate reflections for each phase in the d-range
        5. Pressure sweep to match observed peaks to phases
        6. Per-phase lattice parameter refinement

    Args:
        spectrum: Observed diffraction spectrum (TOF or d-spacing).
        instrument: Instrument description with profile parameters.
        experiment: Experiment description with phase descriptions
            (CIF paths, EOS data, stability ranges).
        P_min: Lower pressure bound for sweep (GPa).
        P_max: Upper pressure bound for sweep (GPa).  Defaults to
            ``experiment.global_max_pressure`` if set, else 100.
        n_coarse: Coarse grid points for pressure sweep.
        n_fine: Fine grid points for pressure sweep.
        bg_win_size: Half-window size for background estimation.
        noise_sigma_factor: SNR threshold for peak finding and
            weak-peak exclusion in lattice refinement.
        min_fwhm_factor: Minimum FWHM ratio for sub-resolution
            peak rejection.

    Returns:
        InspectionResult with matched peaks, refined lattice
        parameters, and diagnostic metadata.

    Raises:
        ValueError: If experiment has no phases with loaded CIF data.
    """
    # Resolve pressure range
    if P_max is None:
        P_max = experiment.global_max_pressure or 100.0

    # --- 1. Convert to d-spacing ---
    if spectrum.x_unit == "TOF":
        d_axis = tof_to_d(spectrum.x, instrument)
    else:
        d_axis = spectrum.x.copy()

    # --- 2. Background subtraction ---
    background, bg_subtracted = estimate_background(
        spectrum.y,
        win_size=bg_win_size,
    )

    # --- 3. Peak finding ---
    d_curve, fwhm_curve = parse_resolution_curve(instrument)
    peak_table = find_peaks_in_spectrum(
        d_axis,
        bg_subtracted,
        resolution=(d_curve, fwhm_curve),
        noise_sigma_factor=noise_sigma_factor,
        min_fwhm_factor=min_fwhm_factor,
    )

    # --- 4. Generate reflections per phase ---
    active_phases = [desc for desc in experiment.phases if desc.phase is not None]
    if not active_phases:
        raise ValueError("No phases with loaded CIF data in the experiment description")

    d_min, d_max = float(d_axis.min()), float(d_axis.max())
    phase_reflections: dict[str, list[dict]] = {}
    for desc in active_phases:
        assert desc.phase is not None  # guarded above
        refs = generate_reflections(desc.phase, d_min, d_max)
        phase_reflections[desc.name] = refs

    # --- 5. Pressure sweep ---
    if len(peak_table.positions) == 0:
        return InspectionResult(
            crystal_phases=[desc.phase.copy() for desc in active_phases if desc.phase],
            instrument=instrument.copy(),
            peak_table=peak_table,
            metadata={"n_peaks_found": 0, "n_phases_matched": 0},
        )

    tol = fwhm_at_d(peak_table.positions, d_curve, fwhm_curve)

    best_P, match_result = sweep_pressure(
        peak_table.positions,
        peak_table.heights,
        peak_table.fwhm,
        active_phases,
        phase_reflections,
        tol,
        P_min=P_min,
        P_max=P_max,
        n_coarse=n_coarse,
        n_fine=n_fine,
    )

    # --- 6. Lattice refinement ---
    # Noise floor from lower quartile of background-subtracted signal
    q25 = float(np.percentile(bg_subtracted, 25))
    lower_quarter = bg_subtracted[bg_subtracted <= q25]
    noise_sigma = float(np.std(lower_quarter)) if len(lower_quarter) > 0 else 0.0
    noise_sigma = max(noise_sigma, 1e-10)

    refinements = refine_all_phases(
        match_result,
        active_phases,
        noise_sigma=noise_sigma,
        min_prominence_sigma=noise_sigma_factor,
    )

    # --- Build result ---
    # Build d-space spectrum for plotting (reused by UI results panel)
    d_spectrum = DiffractionSpectrum(
        x=d_axis,
        y=spectrum.y,
        e=spectrum.e,
        x_unit="d-Spacing",
        label=spectrum.label,
        bank=spectrum.bank,
    )

    return InspectionResult(
        crystal_phases=[desc.phase.copy() for desc in active_phases if desc.phase],
        instrument=instrument.copy(),
        match_result=match_result,
        refinements=refinements,
        peak_table=peak_table,
        sweep_pressure_gpa=best_P,
        metadata={
            "n_peaks_found": len(peak_table.positions),
            "n_phases_matched": sum(
                1 for pm in match_result.phase_matches if pm.n_matched > 0
            ),
            "n_unmatched_peaks": len(match_result.unmatched_indices),
            "noise_sigma": noise_sigma,
            "P_min": P_min,
            "P_max": P_max,
            "bg_subtracted": bg_subtracted,
            "spectrum": d_spectrum,
            "phase_reflections": phase_reflections,
        },
    )
