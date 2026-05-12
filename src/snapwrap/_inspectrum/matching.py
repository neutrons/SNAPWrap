"""
Peak matching engine for phase identification and strain estimation.

Matches observed peaks (from :mod:`peakfinding`) to calculated
reflections (from :mod:`crystallography`) by sweeping an isotropic
linear strain factor *s*.  Under uniform strain, every d-spacing
scales as d_obs ≈ s × d_calc.

The pipeline:
1. For each candidate phase, generate reflections in the data range.
2. Determine the strain search window (from EOS or a blind range).
3. Sweep trial strain values, counting how many observed peaks
   fall within tolerance of a strained reflection.
4. Report the best strain and matched peak assignments per phase.

This module does NOT refine anything — it only estimates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------


@dataclass
class MatchedPeak:
    """A single observed peak matched to a calculated reflection.

    Attributes:
        obs_idx: Index into the observed PeakTable arrays.
        obs_d: Observed d-spacing (Å).
        obs_height: Observed peak height.
        obs_fwhm: Observed FWHM (Å).
        calc_d: Reference d-spacing from CIF (unstrained, Å).
        strained_d: calc_d × strain (Å).
        hkl: Miller indices of the matched reflection.
        multiplicity: Symmetry multiplicity.
        F_sq: Structure factor |F|² (neutron).
        residual: obs_d − strained_d (Å).
    """

    obs_idx: int
    obs_d: float
    obs_height: float
    obs_fwhm: float
    calc_d: float
    strained_d: float
    hkl: tuple[int, int, int]
    multiplicity: int
    F_sq: float
    residual: float


@dataclass
class PhaseMatch:
    """Result of matching one phase against observed peaks.

    Attributes:
        phase_name: Name of the matched phase.
        strain: Best-fit isotropic strain factor.
        n_matched: Number of observed peaks matched to reflections.
        n_expected: Total reflections in the data range.
        matched_peaks: Details of each matched peak.
        score: Weighted match quality (higher is better).
    """

    phase_name: str
    strain: float
    n_matched: int
    n_expected: int
    matched_peaks: list[MatchedPeak] = field(default_factory=list)
    score: float = 0.0

    def __repr__(self) -> str:
        return (
            f"PhaseMatch({self.phase_name!r}, s={self.strain:.6f}, "
            f"matched={self.n_matched}/{self.n_expected}, "
            f"score={self.score:.2f})"
        )


@dataclass
class MatchResult:
    """Combined result of multi-phase peak matching.

    Attributes:
        phase_matches: Per-phase matching results, sorted by score.
        unmatched_indices: Indices of observed peaks not assigned
            to any phase.
    """

    phase_matches: list[PhaseMatch] = field(default_factory=list)
    unmatched_indices: list[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core matching
# ---------------------------------------------------------------------------


def match_peaks_at_strain(
    obs_d: NDArray[np.float64],
    obs_heights: NDArray[np.float64],
    obs_fwhm: NDArray[np.float64],
    reflections: list[dict],
    strain: float,
    tolerance: NDArray[np.float64] | float,
) -> list[MatchedPeak]:
    """Match observed peaks to reflections at a given strain.

    For each calculated reflection, finds the closest observed peak
    and accepts the match if the distance is within ``tolerance``.
    Each observed peak is matched to at most one reflection (the
    closest).

    Args:
        obs_d: Observed peak d-spacings (Å), sorted decreasing.
        obs_heights: Observed peak heights.
        obs_fwhm: Observed peak FWHM (Å).
        reflections: List of dicts from
            :func:`~snapwrap._inspectrum.crystallography.generate_reflections`.
            Each has keys ``d``, ``hkl``, ``multiplicity``, ``F_sq``.
        strain: Isotropic linear strain factor (d_obs ≈ s × d_calc).
        tolerance: Matching tolerance (Å).  Either a scalar or an
            array of per-peak tolerances matching ``obs_d``.

    Returns:
        List of :class:`MatchedPeak` for accepted matches.
    """
    if len(obs_d) == 0 or len(reflections) == 0:
        return []

    # Precompute strained positions and per-peak tolerances
    tol = np.broadcast_to(np.asarray(tolerance, dtype=np.float64), obs_d.shape)
    used_obs: set[int] = set()
    matches: list[MatchedPeak] = []

    # Sort reflections by expected intensity (F² × mult) descending
    # so strong reflections get first pick of observed peaks
    sorted_refs = sorted(
        reflections,
        key=lambda r: r["F_sq"] * r["multiplicity"],
        reverse=True,
    )

    for ref in sorted_refs:
        d_strained = strain * ref["d"]
        # Find closest observed peak
        diffs = np.abs(obs_d - d_strained)
        order = np.argsort(diffs)
        for idx in order:
            idx_int = int(idx)
            if idx_int in used_obs:
                continue
            if diffs[idx_int] <= tol[idx_int]:
                used_obs.add(idx_int)
                matches.append(
                    MatchedPeak(
                        obs_idx=idx_int,
                        obs_d=float(obs_d[idx_int]),
                        obs_height=float(obs_heights[idx_int]),
                        obs_fwhm=float(obs_fwhm[idx_int]),
                        calc_d=ref["d"],
                        strained_d=d_strained,
                        hkl=tuple(ref["hkl"]),
                        multiplicity=ref["multiplicity"],
                        F_sq=ref["F_sq"],
                        residual=float(obs_d[idx_int] - d_strained),
                    )
                )
                break  # move to next reflection

    return matches


def _score_matches(
    matches: list[MatchedPeak],
    tolerance: NDArray[np.float64] | float | None = None,
) -> float:
    """Score a set of matches by intensity-weighted count with residual penalty.

    Combines the number of matched peaks with the total expected
    intensity of matched reflections, then penalises for how far
    each match is from the predicted position (normalised by the
    local tolerance).

    Args:
        matches: List of matched peaks.
        tolerance: Per-peak or scalar tolerance used during matching.
            When provided, each match's score is scaled by how well
            it is centred (1 at zero residual, 0 at the tolerance
            boundary).  If None, no positional penalty is applied.

    Returns:
        Score (higher is better).
    """
    if not matches:
        return 0.0

    score = 0.0
    for m in matches:
        weight = 1.0 + np.log1p(m.F_sq * m.multiplicity)
        # Positional quality: Gaussian-like penalty based on residual
        if tolerance is not None:
            tol_arr = np.atleast_1d(np.asarray(tolerance, dtype=np.float64))
            local_tol = (
                float(tol_arr[m.obs_idx]) if tol_arr.size > 1 else float(tol_arr[0])
            )
            if local_tol > 0:
                # Gaussian: 1.0 at centre, ~0.01 at tol boundary
                weight *= np.exp(-2.0 * (m.residual / local_tol) ** 2)
        score += weight
    return score


def sweep_strain(
    obs_d: NDArray[np.float64],
    obs_heights: NDArray[np.float64],
    obs_fwhm: NDArray[np.float64],
    reflections: list[dict],
    tolerance: NDArray[np.float64] | float,
    s_min: float = 0.90,
    s_max: float = 1.10,
    n_coarse: int = 201,
    n_fine: int = 101,
    fine_half_width: float | None = None,
) -> tuple[float, list[MatchedPeak], float]:
    """Sweep strain factors to find the best match.

    Two-pass search: a coarse grid over [s_min, s_max], then a
    finer grid centred on the coarse best.

    Args:
        obs_d: Observed peak d-spacings (Å).
        obs_heights: Observed peak heights.
        obs_fwhm: Observed peak FWHM (Å).
        reflections: Calculated reflections from CIF.
        tolerance: Matching tolerance (Å), scalar or per-peak.
        s_min: Lower bound of strain search.
        s_max: Upper bound of strain search.
        n_coarse: Number of coarse grid points.
        n_fine: Number of fine grid points.
        fine_half_width: Half-width of fine search window.
            Defaults to 2× coarse step.

    Returns:
        Tuple of (best_strain, matched_peaks, score).
    """
    if len(obs_d) == 0 or len(reflections) == 0:
        return 1.0, [], 0.0

    # --- Coarse pass ---
    coarse_strains = np.linspace(s_min, s_max, n_coarse)
    best_score = -1.0
    best_strain = 1.0
    best_matches: list[MatchedPeak] = []

    for s in coarse_strains:
        matches = match_peaks_at_strain(
            obs_d,
            obs_heights,
            obs_fwhm,
            reflections,
            s,
            tolerance,
        )
        score = _score_matches(matches, tolerance)
        if score > best_score:
            best_score = score
            best_strain = s
            best_matches = matches

    # --- Fine pass ---
    coarse_step = (s_max - s_min) / max(n_coarse - 1, 1)
    hw = fine_half_width if fine_half_width is not None else 2 * coarse_step
    fine_lo = max(s_min, best_strain - hw)
    fine_hi = min(s_max, best_strain + hw)
    fine_strains = np.linspace(fine_lo, fine_hi, n_fine)

    for s in fine_strains:
        matches = match_peaks_at_strain(
            obs_d,
            obs_heights,
            obs_fwhm,
            reflections,
            s,
            tolerance,
        )
        score = _score_matches(matches, tolerance)
        if score > best_score:
            best_score = score
            best_strain = s
            best_matches = matches

    return best_strain, best_matches, best_score


def identify_phases(
    obs_d: NDArray[np.float64],
    obs_heights: NDArray[np.float64],
    obs_fwhm: NDArray[np.float64],
    phase_reflections: dict[str, list[dict]],
    tolerance: NDArray[np.float64] | float,
    strain_ranges: dict[str, tuple[float, float]] | None = None,
    n_coarse: int = 201,
    n_fine: int = 101,
) -> MatchResult:
    """Identify phases by matching observed peaks to multiple phases.

    For each phase, sweeps strain to find the best match.  Then
    assigns each observed peak to at most one phase (the one with
    the smallest residual if contested).

    Args:
        obs_d: Observed peak d-spacings (Å).
        obs_heights: Observed peak heights.
        obs_fwhm: Observed peak FWHM (Å).
        phase_reflections: Dict mapping phase name → reflection list
            (from :func:`~snapwrap._inspectrum.crystallography.generate_reflections`).
        tolerance: Matching tolerance (Å), scalar or per-peak array.
        strain_ranges: Optional dict mapping phase name →
            ``(s_min, s_max)``.  If not provided or a phase is
            missing, defaults to ``(0.90, 1.10)``.
        n_coarse: Coarse grid points per phase sweep.
        n_fine: Fine grid points per phase sweep.

    Returns:
        :class:`MatchResult` with per-phase matches and unmatched indices.
    """
    if strain_ranges is None:
        strain_ranges = {}

    # --- Per-phase sweep ---
    phase_matches: list[PhaseMatch] = []
    for name, refs in phase_reflections.items():
        s_min, s_max = strain_ranges.get(name, (0.90, 1.10))
        best_s, matches, score = sweep_strain(
            obs_d,
            obs_heights,
            obs_fwhm,
            refs,
            tolerance,
            s_min=s_min,
            s_max=s_max,
            n_coarse=n_coarse,
            n_fine=n_fine,
        )
        phase_matches.append(
            PhaseMatch(
                phase_name=name,
                strain=best_s,
                n_matched=len(matches),
                n_expected=len(refs),
                matched_peaks=matches,
                score=score,
            )
        )

    # --- Resolve contested observed peaks ---
    # If an observed peak is claimed by multiple phases, give it to
    # the phase where the match has the smallest |residual|
    obs_assignments: dict[int, tuple[int, float]] = {}
    # obs_assignments[obs_idx] = (phase_idx, |residual|)

    for pi, pm in enumerate(phase_matches):
        for mp in pm.matched_peaks:
            abs_res = abs(mp.residual)
            if (
                mp.obs_idx not in obs_assignments
                or abs_res < obs_assignments[mp.obs_idx][1]
            ):
                obs_assignments[mp.obs_idx] = (pi, abs_res)

    # Rebuild matched_peaks lists with contested peaks resolved
    for pi, pm in enumerate(phase_matches):
        resolved = [
            mp
            for mp in pm.matched_peaks
            if obs_assignments.get(mp.obs_idx, (None,))[0] == pi
        ]
        pm.matched_peaks = resolved
        pm.n_matched = len(resolved)
        pm.score = _score_matches(resolved, tolerance)

    # Sort by score descending
    phase_matches.sort(key=lambda pm: pm.score, reverse=True)

    # Find unmatched
    all_matched = set(obs_assignments.keys())
    unmatched = [i for i in range(len(obs_d)) if i not in all_matched]

    return MatchResult(
        phase_matches=phase_matches,
        unmatched_indices=unmatched,
    )


# ---------------------------------------------------------------------------
# Pressure sweep (physics-informed matching)
# ---------------------------------------------------------------------------


def sweep_pressure(
    obs_d: NDArray[np.float64],
    obs_heights: NDArray[np.float64],
    obs_fwhm: NDArray[np.float64],
    phase_descriptions: list,
    phase_reflections: dict[str, list[dict]],
    tolerance: NDArray[np.float64] | float,
    P_min: float = 0.0,
    P_max: float = 100.0,
    n_coarse: int = 201,
    n_fine: int = 101,
    fine_half_width: float | None = None,
) -> tuple[float, MatchResult]:
    """Sweep pressure to find the best global match across all phases.

    All phases in a sample share the same pressure.  For each trial
    pressure, the predicted strain for every phase is computed from
    its equation of state, and observed peaks are matched at those
    strains.  The pressure giving the highest total score is selected.

    Two-pass search: a coarse grid over ``[P_min, P_max]``, then a
    finer grid centred on the coarse best.

    Args:
        obs_d: Observed peak d-spacings (Å), sorted decreasing.
        obs_heights: Observed peak heights.
        obs_fwhm: Observed peak FWHM (Å).
        phase_descriptions: :class:`~snapwrap._inspectrum.models.PhaseDescription`
            objects **with EOS data**.  Phases whose ``eos`` is None,
            or that are not stable at the trial pressure, are silently
            skipped.
        phase_reflections: Dict mapping ``desc.name`` → reflection
            list from :func:`crystallography.generate_reflections`.
        tolerance: Matching tolerance (Å), scalar or per-peak array.
        P_min: Lower pressure bound (GPa).
        P_max: Upper pressure bound (GPa).
        n_coarse: Number of coarse grid points.
        n_fine: Number of fine grid points.
        fine_half_width: Half-width of fine search window (GPa).
            Defaults to 2× coarse step.

    Returns:
        Tuple of ``(best_pressure_GPa, match_result)``.
        ``match_result.phase_matches`` contains per-phase results
        with ``strain`` set to the EOS-predicted value at the best
        pressure.
    """
    from snapwrap._inspectrum.eos import predicted_strain as _predicted_strain

    # Filter to phases that have EOS and reflections
    active = [
        d
        for d in phase_descriptions
        if d.eos is not None and d.name in phase_reflections
    ]

    if not active or len(obs_d) == 0:
        return 0.0, MatchResult(
            phase_matches=[],
            unmatched_indices=list(range(len(obs_d))),
        )

    def _score_at(P: float) -> tuple[float, dict[str, tuple[float, list[MatchedPeak]]]]:
        """Total score and per-phase data at a given pressure."""
        total = 0.0
        pdata: dict[str, tuple[float, list[MatchedPeak]]] = {}
        for desc in active:
            if not desc.is_stable_at(P):
                continue
            refs = phase_reflections[desc.name]
            if not refs:
                continue
            try:
                s = _predicted_strain(desc.eos, P)
            except ValueError:
                continue  # P outside EOS validity range
            matches = match_peaks_at_strain(
                obs_d,
                obs_heights,
                obs_fwhm,
                refs,
                s,
                tolerance,
            )
            score = _score_matches(matches, tolerance)
            total += score
            pdata[desc.name] = (s, matches)
        return total, pdata

    # --- Coarse pass ---
    pressures = np.linspace(P_min, P_max, n_coarse)
    best_score = -1.0
    best_P = 0.0
    best_pdata: dict[str, tuple[float, list[MatchedPeak]]] = {}

    for P in pressures:
        score, pdata = _score_at(float(P))
        if score > best_score:
            best_score = score
            best_P = float(P)
            best_pdata = pdata

    # --- Fine pass ---
    coarse_step = (P_max - P_min) / max(n_coarse - 1, 1)
    hw = fine_half_width if fine_half_width is not None else 2 * coarse_step
    fine_lo = max(P_min, best_P - hw)
    fine_hi = min(P_max, best_P + hw)
    fine_pressures = np.linspace(fine_lo, fine_hi, n_fine)

    for P in fine_pressures:
        score, pdata = _score_at(float(P))
        if score > best_score:
            best_score = score
            best_P = float(P)
            best_pdata = pdata

    # --- Build MatchResult with contested-peak resolution ---
    phase_matches: list[PhaseMatch] = []
    for desc in active:
        if desc.name in best_pdata:
            s, matches = best_pdata[desc.name]
            phase_matches.append(
                PhaseMatch(
                    phase_name=desc.name,
                    strain=s,
                    n_matched=len(matches),
                    n_expected=len(phase_reflections[desc.name]),
                    matched_peaks=matches,
                    score=_score_matches(matches, tolerance),
                )
            )

    # Resolve contested observed peaks (smallest |residual| wins)
    obs_assignments: dict[int, tuple[int, float]] = {}
    for pi, pm in enumerate(phase_matches):
        for mp in pm.matched_peaks:
            abs_res = abs(mp.residual)
            if (
                mp.obs_idx not in obs_assignments
                or abs_res < obs_assignments[mp.obs_idx][1]
            ):
                obs_assignments[mp.obs_idx] = (pi, abs_res)

    for pi, pm in enumerate(phase_matches):
        resolved = [
            mp
            for mp in pm.matched_peaks
            if obs_assignments.get(mp.obs_idx, (None,))[0] == pi
        ]
        pm.matched_peaks = resolved
        pm.n_matched = len(resolved)
        pm.score = _score_matches(resolved, tolerance)

    phase_matches.sort(key=lambda pm: pm.score, reverse=True)

    all_matched = set(obs_assignments.keys())
    unmatched = [i for i in range(len(obs_d)) if i not in all_matched]

    return best_P, MatchResult(
        phase_matches=phase_matches,
        unmatched_indices=unmatched,
    )
