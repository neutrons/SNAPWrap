"""
Lattice parameter refinement from matched peaks.

Fits lattice parameters to observed d-spacings using least-squares
minimisation of 1/d² residuals.  This is NOT Rietveld refinement —
it fits only lattice parameters (and hence peak positions in
d-spacing) to the subset of peaks that were matched in the
peak-matching step.

The fitting functions are organised by crystal system.  Each system
has a ``d2_inv`` calculator and a corresponding weighted residual
function suitable for :func:`scipy.optimize.least_squares`.

Ported from ``snapwrap.sampleMeta.latticeFittingFunctions`` and
extended to all seven crystal systems.

Typical usage::

    from snapwrap._inspectrum.lattice import refine_lattice_parameters

    result = refine_lattice_parameters(phase_match, phase_description)
    print(result.a, result.pressure_gpa)
"""

from __future__ import annotations

from dataclasses import dataclass

import cryspy
import numpy as np
from scipy.optimize import least_squares

from snapwrap._inspectrum.eos import pressure_at
from snapwrap._inspectrum.matching import MatchResult, PhaseMatch
from snapwrap._inspectrum.models import CrystalPhase, PhaseDescription

# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class LatticeRefinementResult:
    """Result of lattice parameter refinement for one phase.

    Attributes:
        phase_name: Name of the phase.
        crystal_system: Crystal system string (e.g. "cubic").
        a: Refined lattice parameter a (Å).
        b: Refined lattice parameter b (Å).
        c: Refined lattice parameter c (Å).
        alpha: Lattice angle α (degrees).
        beta: Lattice angle β (degrees).
        gamma: Lattice angle γ (degrees).
        volume: Refined unit cell volume (ų).
        pressure_gpa: Pressure derived from EOS, or None.
        residual_sum_sq: Sum of squared weighted residuals.
        n_peaks_used: Number of peaks used in the fit.
        n_peaks_excluded: Number of matched peaks excluded (weak).
        success: Whether the least-squares fit converged.
    """

    phase_name: str = ""
    crystal_system: str = ""
    a: float = 0.0
    b: float = 0.0
    c: float = 0.0
    alpha: float = 90.0
    beta: float = 90.0
    gamma: float = 90.0
    volume: float = 0.0
    pressure_gpa: float | None = None
    residual_sum_sq: float = 0.0
    n_peaks_used: int = 0
    n_peaks_excluded: int = 0
    success: bool = False

    def __repr__(self) -> str:
        p_str = (
            f", P={self.pressure_gpa:.2f} GPa" if self.pressure_gpa is not None else ""
        )
        return (
            f"LatticeRefinementResult({self.phase_name!r}, "
            f"{self.crystal_system}, a={self.a:.5f}"
            f"{p_str}, n={self.n_peaks_used})"
        )

    def d_spacing(self, h: int, k: int, l: int) -> float:
        """Compute d-spacing for (h, k, l) from refined lattice parameters."""
        sys = self.crystal_system
        if sys == "cubic":
            inv = (h * h + k * k + l * l) / (self.a**2)
        elif sys in ("tetragonal",):
            inv = (h * h + k * k) / (self.a**2) + (l * l) / (self.c**2)
        elif sys in ("hexagonal", "trigonal"):
            inv = (4.0 / 3.0) * (h * h + h * k + k * k) / (self.a**2) + (l * l) / (
                self.c**2
            )
        elif sys == "orthorhombic":
            inv = (h * h) / (self.a**2) + (k * k) / (self.b**2) + (l * l) / (self.c**2)
        else:
            # monoclinic / triclinic: use the general triclinic formula
            al = np.radians(self.alpha)
            be = np.radians(self.beta)
            ga = np.radians(self.gamma)
            inv = d2_inv_triclinic(h, k, l, self.a, self.b, self.c, al, be, ga)
        return 1.0 / np.sqrt(inv) if inv > 0 else 0.0


# ---------------------------------------------------------------------------
# Crystal system identification
# ---------------------------------------------------------------------------


def crystal_system_from_sg(space_group_number: int) -> str:
    """Determine crystal system from space group number.

    Args:
        space_group_number: International Tables number (1–230).

    Returns:
        Crystal system string: "cubic", "hexagonal", "trigonal",
        "tetragonal", "orthorhombic", "monoclinic", or "triclinic".
    """
    return str(cryspy.get_crystal_system_by_it_number(space_group_number)).lower()


# ---------------------------------------------------------------------------
# 1/d² calculators per crystal system
# ---------------------------------------------------------------------------


def d2_inv_cubic(h: int, k: int, l: int, a: float) -> float:
    """1/d² for cubic: (h² + k² + l²) / a²."""
    return (h * h + k * k + l * l) / (a * a)


def d2_inv_tetragonal(h: int, k: int, l: int, a: float, c: float) -> float:
    """1/d² for tetragonal: (h² + k²) / a² + l² / c²."""
    return (h * h + k * k) / (a * a) + (l * l) / (c * c)


def d2_inv_hexagonal(h: int, k: int, l: int, a: float, c: float) -> float:
    """1/d² for hexagonal/trigonal: 4/3·(h² + hk + k²) / a² + l² / c²."""
    return (4.0 / 3.0) * (h * h + h * k + k * k) / (a * a) + (l * l) / (c * c)


def d2_inv_orthorhombic(
    h: int,
    k: int,
    l: int,
    a: float,
    b: float,
    c: float,
) -> float:
    """1/d² for orthorhombic: h²/a² + k²/b² + l²/c²."""
    return (h * h) / (a * a) + (k * k) / (b * b) + (l * l) / (c * c)


def d2_inv_monoclinic(
    h: int,
    k: int,
    l: int,
    a: float,
    b: float,
    c: float,
    beta: float,
) -> float:
    """1/d² for monoclinic (unique axis b, β ≠ 90°).

    Args:
        beta: Angle β in **radians**.
    """
    sin_b = np.sin(beta)
    cos_b = np.cos(beta)
    return (
        (h * h) / (a * a * sin_b * sin_b)
        + (k * k) / (b * b)
        + (l * l) / (c * c * sin_b * sin_b)
        - 2.0 * h * l * cos_b / (a * c * sin_b * sin_b)
    )


def d2_inv_triclinic(
    h: int,
    k: int,
    l: int,
    a: float,
    b: float,
    c: float,
    alpha: float,
    beta: float,
    gamma: float,
) -> float:
    """1/d² for triclinic (general case).

    Uses the reciprocal metric tensor.

    Args:
        alpha, beta, gamma: Angles in **radians**.
    """
    ca, cb, cg = np.cos(alpha), np.cos(beta), np.cos(gamma)
    sa, sb, sg = np.sin(alpha), np.sin(beta), np.sin(gamma)

    vol_factor = 1.0 - ca * ca - cb * cb - cg * cg + 2.0 * ca * cb * cg
    if vol_factor <= 0:
        return 0.0
    V_sq = (a * b * c) ** 2 * vol_factor

    s11 = b * b * c * c * sa * sa
    s22 = a * a * c * c * sb * sb
    s33 = a * a * b * b * sg * sg
    s12 = a * b * c * c * (ca * cb - cg)
    s13 = a * b * b * c * (cg * ca - cb)
    s23 = a * a * b * c * (cb * cg - ca)

    return (
        s11 * h * h
        + s22 * k * k
        + s33 * l * l
        + 2.0 * s12 * h * k
        + 2.0 * s23 * k * l
        + 2.0 * s13 * h * l
    ) / V_sq


# ---------------------------------------------------------------------------
# Residual functions for least_squares
# ---------------------------------------------------------------------------


def _residuals_cubic(
    params: np.ndarray,
    hkl_list: list[tuple[int, int, int]],
    d_obs: np.ndarray,
    weights: np.ndarray,
) -> np.ndarray:
    """Weighted residuals in 1/d² space for cubic."""
    a = params[0]
    resid = np.empty(len(d_obs))
    for i, (h, k, l) in enumerate(hkl_list):
        resid[i] = weights[i] * (d2_inv_cubic(h, k, l, a) - 1.0 / (d_obs[i] ** 2))
    return resid


def _residuals_tetragonal(
    params: np.ndarray,
    hkl_list: list[tuple[int, int, int]],
    d_obs: np.ndarray,
    weights: np.ndarray,
) -> np.ndarray:
    """Weighted residuals in 1/d² space for tetragonal."""
    a, c = params
    resid = np.empty(len(d_obs))
    for i, (h, k, l) in enumerate(hkl_list):
        resid[i] = weights[i] * (
            d2_inv_tetragonal(h, k, l, a, c) - 1.0 / (d_obs[i] ** 2)
        )
    return resid


def _residuals_hexagonal(
    params: np.ndarray,
    hkl_list: list[tuple[int, int, int]],
    d_obs: np.ndarray,
    weights: np.ndarray,
) -> np.ndarray:
    """Weighted residuals in 1/d² space for hexagonal/trigonal."""
    a, c = params
    resid = np.empty(len(d_obs))
    for i, (h, k, l) in enumerate(hkl_list):
        resid[i] = weights[i] * (
            d2_inv_hexagonal(h, k, l, a, c) - 1.0 / (d_obs[i] ** 2)
        )
    return resid


def _residuals_orthorhombic(
    params: np.ndarray,
    hkl_list: list[tuple[int, int, int]],
    d_obs: np.ndarray,
    weights: np.ndarray,
) -> np.ndarray:
    """Weighted residuals in 1/d² space for orthorhombic."""
    a, b, c = params
    resid = np.empty(len(d_obs))
    for i, (h, k, l) in enumerate(hkl_list):
        resid[i] = weights[i] * (
            d2_inv_orthorhombic(h, k, l, a, b, c) - 1.0 / (d_obs[i] ** 2)
        )
    return resid


def _residuals_monoclinic(
    params: np.ndarray,
    hkl_list: list[tuple[int, int, int]],
    d_obs: np.ndarray,
    weights: np.ndarray,
) -> np.ndarray:
    """Weighted residuals in 1/d² space for monoclinic."""
    a, b, c, beta_deg = params
    beta = np.radians(beta_deg)
    resid = np.empty(len(d_obs))
    for i, (h, k, l) in enumerate(hkl_list):
        resid[i] = weights[i] * (
            d2_inv_monoclinic(h, k, l, a, b, c, beta) - 1.0 / (d_obs[i] ** 2)
        )
    return resid


def _residuals_triclinic(
    params: np.ndarray,
    hkl_list: list[tuple[int, int, int]],
    d_obs: np.ndarray,
    weights: np.ndarray,
) -> np.ndarray:
    """Weighted residuals in 1/d² space for triclinic."""
    a, b, c, alpha_deg, beta_deg, gamma_deg = params
    alpha = np.radians(alpha_deg)
    beta = np.radians(beta_deg)
    gamma = np.radians(gamma_deg)
    resid = np.empty(len(d_obs))
    for i, (h, k, l) in enumerate(hkl_list):
        resid[i] = weights[i] * (
            d2_inv_triclinic(h, k, l, a, b, c, alpha, beta, gamma)
            - 1.0 / (d_obs[i] ** 2)
        )
    return resid


# Map crystal system → (residual_fn, param_names)
_SYSTEM_RESIDUALS = {
    "cubic": (_residuals_cubic, ["a"]),
    "tetragonal": (_residuals_tetragonal, ["a", "c"]),
    "hexagonal": (_residuals_hexagonal, ["a", "c"]),
    "trigonal": (_residuals_hexagonal, ["a", "c"]),
    "orthorhombic": (_residuals_orthorhombic, ["a", "b", "c"]),
    "monoclinic": (_residuals_monoclinic, ["a", "b", "c", "beta"]),
    "triclinic": (_residuals_triclinic, ["a", "b", "c", "alpha", "beta", "gamma"]),
}


# ---------------------------------------------------------------------------
# Volume calculation
# ---------------------------------------------------------------------------


def cell_volume(
    a: float,
    b: float,
    c: float,
    alpha_deg: float,
    beta_deg: float,
    gamma_deg: float,
) -> float:
    """Compute unit cell volume from lattice parameters.

    Args:
        a, b, c: Lattice parameters (Å).
        alpha_deg, beta_deg, gamma_deg: Lattice angles (degrees).

    Returns:
        Volume in ų.
    """
    al = np.radians(alpha_deg)
    be = np.radians(beta_deg)
    ga = np.radians(gamma_deg)
    ca, cb, cg = np.cos(al), np.cos(be), np.cos(ga)
    return a * b * c * np.sqrt(1 - ca**2 - cb**2 - cg**2 + 2 * ca * cb * cg)


# ---------------------------------------------------------------------------
# Initial guess extraction from CIF phase
# ---------------------------------------------------------------------------


def _initial_guess(phase: CrystalPhase, system: str) -> np.ndarray:
    """Extract initial lattice parameters from a CrystalPhase.

    Uses the CIF lattice parameters scaled by the matched strain
    as the starting point for refinement.
    """
    if system == "cubic":
        return np.array([phase.a])
    elif system in ("tetragonal", "hexagonal", "trigonal"):
        return np.array([phase.a, phase.c])
    elif system == "orthorhombic":
        return np.array([phase.a, phase.b, phase.c])
    elif system == "monoclinic":
        return np.array([phase.a, phase.b, phase.c, phase.beta])
    else:  # triclinic
        return np.array(
            [phase.a, phase.b, phase.c, phase.alpha, phase.beta, phase.gamma]
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def refine_lattice_parameters(
    phase_match: PhaseMatch,
    phase_desc: PhaseDescription,
    *,
    min_prominence_sigma: float = 5.0,
    noise_sigma: float | None = None,
) -> LatticeRefinementResult:
    """Refine lattice parameters from matched peak positions.

    Fits the minimum number of free lattice parameters for the
    crystal system using least-squares in 1/d² space.  Optionally
    excludes weak peaks whose prominence is below a threshold.

    When the phase has an EOS, the refined volume is converted to
    a pressure estimate.

    Args:
        phase_match: Matching result for this phase (from
            :func:`~snapwrap._inspectrum.matching.sweep_pressure`).
        phase_desc: Phase description with CIF phase and optional EOS.
        min_prominence_sigma: Exclude matched peaks with prominence
            < ``min_prominence_sigma`` × *noise_sigma*.
            Default 5.0.  Set to 0 to use all matched peaks.
        noise_sigma: Noise floor estimate.  Required for weak-peak
            exclusion.  If None, all matched peaks are used.

    Returns:
        :class:`LatticeRefinementResult` with refined parameters.

    Raises:
        ValueError: If no peaks survive filtering or crystal system
            is unsupported.
    """
    if phase_desc.phase is None:
        raise ValueError(f"Phase {phase_desc.name!r} has no loaded CrystalPhase")

    phase = phase_desc.phase
    system = crystal_system_from_sg(phase.space_group_number)

    # Collect matched peaks, applying weak-peak exclusion
    hkl_list: list[tuple[int, int, int]] = []
    d_obs_list: list[float] = []
    fwhm_list: list[float] = []
    n_excluded = 0

    prom_threshold = 0.0
    if noise_sigma is not None and min_prominence_sigma > 0:
        prom_threshold = min_prominence_sigma * noise_sigma

    for mp in phase_match.matched_peaks:
        # Apply weak-peak exclusion
        if prom_threshold > 0 and mp.obs_height < prom_threshold:
            n_excluded += 1
            continue
        hkl_list.append(mp.hkl)
        d_obs_list.append(mp.obs_d)
        fwhm_list.append(mp.obs_fwhm)

    n_used = len(hkl_list)
    result = LatticeRefinementResult(
        phase_name=phase_match.phase_name,
        crystal_system=system,
        n_peaks_used=n_used,
        n_peaks_excluded=n_excluded,
    )

    if system not in _SYSTEM_RESIDUALS:
        raise ValueError(f"Unsupported crystal system: {system!r}")

    residual_fn, param_names = _SYSTEM_RESIDUALS[system]
    n_params = len(param_names)

    if n_used < n_params:
        # Not enough peaks to constrain the fit
        result.success = False
        return result

    d_obs = np.array(d_obs_list, dtype=np.float64)
    fwhm = np.array(fwhm_list, dtype=np.float64)

    # Weights: inverse of FWHM as proxy for uncertainty
    weights = np.where(fwhm > 0, 1.0 / fwhm, 1.0)

    # Initial guess: CIF params scaled by matched strain
    strain = phase_match.strain
    guess = _initial_guess(phase, system)
    # Scale the length params by the strain
    n_lengths = {
        "cubic": 1,
        "tetragonal": 2,
        "hexagonal": 2,
        "trigonal": 2,
        "orthorhombic": 3,
        "monoclinic": 3,
        "triclinic": 3,
    }[system]
    guess[:n_lengths] *= strain

    # Run least-squares
    fit = least_squares(
        residual_fn,
        guess,
        args=(hkl_list, d_obs, weights),
        method="lm",
    )

    result.success = fit.success
    result.residual_sum_sq = float(np.sum(fit.fun**2))

    # Unpack fitted params
    p = fit.x
    if system == "cubic":
        result.a = result.b = result.c = p[0]
        result.alpha = result.beta = result.gamma = 90.0
    elif system in ("tetragonal",):
        result.a = result.b = p[0]
        result.c = p[1]
        result.alpha = result.beta = result.gamma = 90.0
    elif system in ("hexagonal", "trigonal"):
        result.a = result.b = p[0]
        result.c = p[1]
        result.alpha = result.beta = 90.0
        result.gamma = 120.0
    elif system == "orthorhombic":
        result.a, result.b, result.c = p[0], p[1], p[2]
        result.alpha = result.beta = result.gamma = 90.0
    elif system == "monoclinic":
        result.a, result.b, result.c = p[0], p[1], p[2]
        result.beta = p[3]
        result.alpha = result.gamma = 90.0
    else:  # triclinic
        result.a, result.b, result.c = p[0], p[1], p[2]
        result.alpha, result.beta, result.gamma = p[3], p[4], p[5]

    # Compute volume
    result.volume = cell_volume(
        result.a,
        result.b,
        result.c,
        result.alpha,
        result.beta,
        result.gamma,
    )

    # Derive pressure from EOS if available
    if phase_desc.eos is not None:
        v_ratio = result.volume / phase_desc.eos.V_0
        try:
            result.pressure_gpa = pressure_at(phase_desc.eos, v_ratio)
        except (ValueError, ZeroDivisionError):
            result.pressure_gpa = None

    return result


def refine_all_phases(
    match_result: MatchResult,
    phase_descriptions: list[PhaseDescription],
    *,
    noise_sigma: float | None = None,
    min_prominence_sigma: float = 5.0,
) -> list[LatticeRefinementResult]:
    """Refine lattice parameters for all matched phases.

    Args:
        match_result: Combined matching result from
            :func:`~snapwrap._inspectrum.matching.sweep_pressure`.
        phase_descriptions: Phase descriptions (with loaded CIF phases).
        noise_sigma: Noise floor for weak-peak exclusion.
        min_prominence_sigma: SNR threshold for weak-peak exclusion.

    Returns:
        List of refinement results, one per phase with matches.
    """
    # Build name → description lookup
    desc_by_name = {d.name: d for d in phase_descriptions}

    results = []
    for pm in match_result.phase_matches:
        if pm.n_matched == 0:
            continue
        desc = desc_by_name.get(pm.phase_name)
        if desc is None:
            continue
        result = refine_lattice_parameters(
            pm,
            desc,
            noise_sigma=noise_sigma,
            min_prominence_sigma=min_prominence_sigma,
        )
        results.append(result)

    return results


def format_refinement_report(
    results: list[LatticeRefinementResult],
    sweep_pressure_gpa: float | None = None,
) -> str:
    """Format a human-readable report of lattice refinement results.

    Args:
        results: Refinement results from :func:`refine_all_phases`.
        sweep_pressure_gpa: Pressure from the initial sweep (for
            comparison).

    Returns:
        Multi-line string report.
    """
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("Lattice Parameter Refinement Report")
    lines.append("=" * 60)

    if sweep_pressure_gpa is not None:
        lines.append(f"Initial sweep pressure: {sweep_pressure_gpa:.2f} GPa")
        lines.append("")

    for r in results:
        lines.append(f"Phase: {r.phase_name} ({r.crystal_system})")
        lines.append("-" * 40)
        if not r.success:
            lines.append(f"  FIT FAILED (peaks used: {r.n_peaks_used})")
            lines.append("")
            continue

        # Lattice parameters
        if r.crystal_system == "cubic":
            lines.append(f"  a = {r.a:.5f} Å")
        elif r.crystal_system in ("tetragonal", "hexagonal", "trigonal"):
            lines.append(f"  a = {r.a:.5f} Å")
            lines.append(f"  c = {r.c:.5f} Å")
        elif r.crystal_system == "orthorhombic":
            lines.append(f"  a = {r.a:.5f} Å")
            lines.append(f"  b = {r.b:.5f} Å")
            lines.append(f"  c = {r.c:.5f} Å")
        else:
            lines.append(f"  a = {r.a:.5f} Å")
            lines.append(f"  b = {r.b:.5f} Å")
            lines.append(f"  c = {r.c:.5f} Å")
            lines.append(f"  α = {r.alpha:.2f}°  β = {r.beta:.2f}°  γ = {r.gamma:.2f}°")

        lines.append(f"  V = {r.volume:.3f} ų")
        lines.append(f"  Peaks used: {r.n_peaks_used} (excluded: {r.n_peaks_excluded})")
        lines.append(f"  Residual: {r.residual_sum_sq:.2e}")

        if r.pressure_gpa is not None:
            lines.append(f"  Pressure (from EOS): {r.pressure_gpa:.2f} GPa")

        lines.append("")

    # Pressure comparison
    pressures = [
        (r.phase_name, r.pressure_gpa) for r in results if r.pressure_gpa is not None
    ]
    if len(pressures) > 1:
        lines.append("Pressure comparison:")
        for name, p in pressures:
            lines.append(f"  {name}: {p:.2f} GPa")
        p_values = [p for _, p in pressures]
        lines.append(f"  Spread: {max(p_values) - min(p_values):.2f} GPa")

    lines.append("=" * 60)
    return "\n".join(lines)
