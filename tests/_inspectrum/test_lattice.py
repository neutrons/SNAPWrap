"""Tests for snapwrap._inspectrum.lattice — lattice parameter refinement."""

from __future__ import annotations

import numpy as np
import pytest

from snapwrap._inspectrum.lattice import (
    LatticeRefinementResult,
    cell_volume,
    crystal_system_from_sg,
    d2_inv_cubic,
    d2_inv_hexagonal,
    d2_inv_orthorhombic,
    d2_inv_tetragonal,
    format_refinement_report,
    refine_all_phases,
    refine_lattice_parameters,
)
from snapwrap._inspectrum.matching import MatchedPeak, MatchResult, PhaseMatch
from snapwrap._inspectrum.models import CrystalPhase, EquationOfState, PhaseDescription

# ---------------------------------------------------------------------------
# d² inverse formulas
# ---------------------------------------------------------------------------


class TestD2InvFormulas:

    def test_cubic_100(self):
        """d(100) for cubic a=5 should be 5.0."""
        inv = d2_inv_cubic(1, 0, 0, 5.0)
        d = 1.0 / np.sqrt(inv)
        assert abs(d - 5.0) < 1e-10

    def test_cubic_110(self):
        """d(110) for cubic a=5 should be 5/√2."""
        inv = d2_inv_cubic(1, 1, 0, 5.0)
        d = 1.0 / np.sqrt(inv)
        assert abs(d - 5.0 / np.sqrt(2)) < 1e-10

    def test_cubic_111(self):
        """d(111) for cubic a=5 should be 5/√3."""
        inv = d2_inv_cubic(1, 1, 1, 5.0)
        d = 1.0 / np.sqrt(inv)
        assert abs(d - 5.0 / np.sqrt(3)) < 1e-10

    def test_tetragonal_100(self):
        """d(100) for tetragonal depends on a only."""
        inv = d2_inv_tetragonal(1, 0, 0, 4.0, 6.0)
        d = 1.0 / np.sqrt(inv)
        assert abs(d - 4.0) < 1e-10

    def test_tetragonal_001(self):
        """d(001) for tetragonal depends on c only."""
        inv = d2_inv_tetragonal(0, 0, 1, 4.0, 6.0)
        d = 1.0 / np.sqrt(inv)
        assert abs(d - 6.0) < 1e-10

    def test_hexagonal_100(self):
        """d(100) for hexagonal a=4, c=6."""
        inv = d2_inv_hexagonal(1, 0, 0, 4.0, 6.0)
        d = 1.0 / np.sqrt(inv)
        # For hex: 1/d² = 4/3 * 1/a² for (100)
        expected = 4.0 / np.sqrt(4.0 / 3.0)
        assert abs(d - expected) < 1e-10

    def test_orthorhombic_010(self):
        """d(010) for orthorhombic equals b."""
        inv = d2_inv_orthorhombic(0, 1, 0, 3.0, 5.0, 7.0)
        d = 1.0 / np.sqrt(inv)
        assert abs(d - 5.0) < 1e-10


# ---------------------------------------------------------------------------
# Crystal system identification
# ---------------------------------------------------------------------------


class TestCrystalSystem:

    def test_cubic(self):
        assert crystal_system_from_sg(229) == "cubic"  # Im-3m

    def test_hexagonal(self):
        assert crystal_system_from_sg(194) == "hexagonal"  # P6₃/mmc

    def test_trigonal(self):
        assert crystal_system_from_sg(167) == "trigonal"  # R-3c

    def test_orthorhombic(self):
        assert crystal_system_from_sg(62) == "orthorhombic"  # Pnma


# ---------------------------------------------------------------------------
# Cell volume
# ---------------------------------------------------------------------------


class TestCellVolume:

    def test_cubic(self):
        v = cell_volume(3.0, 3.0, 3.0, 90.0, 90.0, 90.0)
        assert abs(v - 27.0) < 1e-10

    def test_hexagonal(self):
        a, c = 4.0, 6.0
        v = cell_volume(a, a, c, 90.0, 90.0, 120.0)
        expected = a * a * c * np.sqrt(3) / 2
        assert abs(v - expected) < 1e-6


# ---------------------------------------------------------------------------
# Helpers for synthetic test data
# ---------------------------------------------------------------------------


def _make_cubic_phase_match(
    a_true: float,
    hkl_list: list[tuple[int, int, int]],
    strain: float = 1.0,
) -> tuple[PhaseMatch, PhaseDescription]:
    """Build a PhaseMatch with synthetic d-spacings for cubic lattice."""
    matched = []
    for i, (h, k, l) in enumerate(hkl_list):
        d = a_true / np.sqrt(h**2 + k**2 + l**2)
        matched.append(
            MatchedPeak(
                obs_idx=i,
                obs_d=d,
                obs_height=1000.0,
                obs_fwhm=0.01,
                calc_d=d / strain,
                strained_d=d,
                hkl=(h, k, l),
                multiplicity=1,
                F_sq=1.0,
                residual=0.0,
            )
        )

    pm = PhaseMatch(
        phase_name="test_cubic",
        strain=strain,
        n_matched=len(matched),
        n_expected=len(matched),
        matched_peaks=matched,
        score=10.0,
    )

    phase = CrystalPhase(
        name="test_cubic",
        a=a_true / strain,
        b=a_true / strain,
        c=a_true / strain,
        alpha=90.0,
        beta=90.0,
        gamma=90.0,
        space_group="I m -3 m",
        space_group_number=229,
    )
    desc = PhaseDescription(name="test_cubic", phase=phase)

    return pm, desc


def _make_hex_phase_match(
    a_true: float,
    c_true: float,
    hkl_list: list[tuple[int, int, int]],
    strain: float = 1.0,
) -> tuple[PhaseMatch, PhaseDescription]:
    """Build a PhaseMatch with synthetic d-spacings for hexagonal lattice."""
    matched = []
    for i, (h, k, l) in enumerate(hkl_list):
        inv = (4.0 / 3.0) * (h**2 + h * k + k**2) / a_true**2 + l**2 / c_true**2
        d = 1.0 / np.sqrt(inv)
        matched.append(
            MatchedPeak(
                obs_idx=i,
                obs_d=d,
                obs_height=1000.0,
                obs_fwhm=0.01,
                calc_d=d / strain,
                strained_d=d,
                hkl=(h, k, l),
                multiplicity=1,
                F_sq=1.0,
                residual=0.0,
            )
        )

    pm = PhaseMatch(
        phase_name="test_hex",
        strain=strain,
        n_matched=len(matched),
        n_expected=len(matched),
        matched_peaks=matched,
        score=10.0,
    )

    phase = CrystalPhase(
        name="test_hex",
        a=a_true / strain,
        b=a_true / strain,
        c=c_true / strain,
        alpha=90.0,
        beta=90.0,
        gamma=120.0,
        space_group="P 63/m m c",
        space_group_number=194,
    )
    desc = PhaseDescription(name="test_hex", phase=phase)

    return pm, desc


# ---------------------------------------------------------------------------
# Lattice refinement tests — cubic
# ---------------------------------------------------------------------------


class TestRefineCubic:

    def test_exact_cubic(self):
        """Refine from exact d-spacings should recover lattice param."""
        a_true = 3.16
        pm, desc = _make_cubic_phase_match(
            a_true,
            [(1, 1, 0), (2, 0, 0), (2, 1, 1), (2, 2, 0)],
        )
        result = refine_lattice_parameters(pm, desc)
        assert result.success
        assert abs(result.a - a_true) < 1e-4
        assert result.crystal_system == "cubic"
        assert result.n_peaks_used == 4

    def test_cubic_single_peak(self):
        """Cubic requires only 1 peak (1 free param)."""
        a_true = 3.16
        pm, desc = _make_cubic_phase_match(a_true, [(1, 1, 0)])
        result = refine_lattice_parameters(pm, desc)
        assert result.success
        assert abs(result.a - a_true) < 1e-4

    def test_cubic_with_strain(self):
        """Strained cubic should refine to the strained lattice param."""
        a_cif = 3.16475
        strain = 0.99
        a_strained = a_cif * strain
        pm, desc = _make_cubic_phase_match(
            a_strained,
            [(1, 1, 0), (2, 0, 0), (2, 1, 1)],
            strain=strain,
        )
        result = refine_lattice_parameters(pm, desc)
        assert result.success
        assert abs(result.a - a_strained) < 1e-4

    def test_cubic_volume(self):
        """Volume should be a³ for cubic."""
        a_true = 3.16
        pm, desc = _make_cubic_phase_match(
            a_true,
            [(1, 1, 0), (2, 0, 0)],
        )
        result = refine_lattice_parameters(pm, desc)
        assert abs(result.volume - a_true**3) < 0.01

    def test_cubic_pressure_from_eos(self):
        """When EOS is present, pressure should be derived."""
        a_cif = 3.16475
        strain = 0.989
        a_strained = a_cif * strain
        eos = EquationOfState(
            eos_type="vinet",
            V_0=31.724,  # ≈ 2 × a_cif³ / 2 for BCC
            K_0=295.2,
            K_prime=4.32,
        )
        pm, desc = _make_cubic_phase_match(
            a_strained,
            [(1, 1, 0), (2, 0, 0)],
            strain=strain,
        )
        desc.eos = eos
        result = refine_lattice_parameters(pm, desc)
        assert result.success
        assert result.pressure_gpa is not None
        assert result.pressure_gpa > 0

    def test_weak_peak_exclusion(self):
        """Peaks below prominence threshold should be excluded."""
        a_true = 3.16
        pm, desc = _make_cubic_phase_match(
            a_true,
            [(1, 1, 0), (2, 0, 0), (2, 1, 1)],
        )
        # Make one peak weak
        pm.matched_peaks[2] = MatchedPeak(
            obs_idx=2,
            obs_d=pm.matched_peaks[2].obs_d,
            obs_height=1.0,  # very weak
            obs_fwhm=0.01,
            calc_d=pm.matched_peaks[2].calc_d,
            strained_d=pm.matched_peaks[2].strained_d,
            hkl=pm.matched_peaks[2].hkl,
            multiplicity=1,
            F_sq=1.0,
            residual=0.0,
        )
        result = refine_lattice_parameters(
            pm,
            desc,
            noise_sigma=0.5,
            min_prominence_sigma=5.0,
        )
        assert result.n_peaks_used == 2
        assert result.n_peaks_excluded == 1
        assert result.success


# ---------------------------------------------------------------------------
# Lattice refinement tests — hexagonal
# ---------------------------------------------------------------------------


class TestRefineHexagonal:

    def test_exact_hexagonal(self):
        """Refine from exact hex d-spacings should recover a and c."""
        a_true, c_true = 4.0, 6.0
        pm, desc = _make_hex_phase_match(
            a_true,
            c_true,
            [(1, 0, 0), (0, 0, 1), (1, 0, 1), (1, 1, 0)],
        )
        result = refine_lattice_parameters(pm, desc)
        assert result.success
        assert abs(result.a - a_true) < 1e-3
        assert abs(result.c - c_true) < 1e-3

    def test_hex_insufficient_peaks(self):
        """Hexagonal needs ≥2 peaks; 1 should fail."""
        pm, desc = _make_hex_phase_match(4.0, 6.0, [(1, 0, 0)])
        result = refine_lattice_parameters(pm, desc)
        assert not result.success


# ---------------------------------------------------------------------------
# refine_all_phases
# ---------------------------------------------------------------------------


class TestRefineAllPhases:

    def test_two_phases(self):
        """Refine two cubic phases simultaneously."""
        pm1, desc1 = _make_cubic_phase_match(3.16, [(1, 1, 0), (2, 0, 0)])
        pm2, desc2 = _make_cubic_phase_match(5.0, [(1, 1, 1), (2, 2, 0)])
        pm2.phase_name = "test_cubic2"
        desc2.name = "test_cubic2"

        match_result = MatchResult(
            phase_matches=[pm1, pm2],
            unmatched_indices=[],
        )
        results = refine_all_phases(
            match_result,
            [desc1, desc2],
        )
        assert len(results) == 2
        assert all(r.success for r in results)


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


class TestFormatReport:

    def test_report_contains_phase_name(self):
        r = LatticeRefinementResult(
            phase_name="tungsten",
            crystal_system="cubic",
            a=3.16,
            b=3.16,
            c=3.16,
            volume=31.6**3 / 1000,
            n_peaks_used=2,
            success=True,
            pressure_gpa=10.0,
        )
        report = format_refinement_report([r], sweep_pressure_gpa=10.2)
        assert "tungsten" in report
        assert "10.00 GPa" in report
        assert "10.20 GPa" in report


# ---------------------------------------------------------------------------
# Integration: real SNAP data
# ---------------------------------------------------------------------------


class TestSNAPLatticeRefinement:
    """End-to-end lattice refinement on SNAP059056."""

    @pytest.fixture()
    def snap_match(self):
        """Run pressure sweep and return match result + descriptions."""
        from pathlib import Path

        from snapwrap._inspectrum.background import estimate_background
        from snapwrap._inspectrum.crystallography import generate_reflections
        from snapwrap._inspectrum.engine import tof_to_d
        from snapwrap._inspectrum.loaders import (
            load_gsa,
            load_instprm,
            load_phase_descriptions,
        )
        from snapwrap._inspectrum.matching import sweep_pressure
        from snapwrap._inspectrum.peakfinding import find_peaks_in_spectrum
        from snapwrap._inspectrum.resolution import fwhm_at_d, parse_resolution_curve

        test_data = Path(__file__).parent / "test_data"
        spectra = load_gsa(test_data / "SNAP059056_all.gsa")
        spec = spectra[0]
        inst = load_instprm(test_data / "SNAP059056_all.instprm")
        exp = load_phase_descriptions(test_data / "snap_phases.json")
        _, peaks = estimate_background(spec.y)
        d_curve, fwhm_curve = parse_resolution_curve(inst)
        d_axis = tof_to_d(spec.x, inst)
        pt = find_peaks_in_spectrum(
            d_axis,
            peaks,
            resolution=(d_curve, fwhm_curve),
        )
        tol = fwhm_at_d(pt.positions, d_curve, fwhm_curve)

        phase_refs = {}
        for desc in exp.phases:
            if desc.phase is not None:
                refs = generate_reflections(desc.phase, d_axis.min(), d_axis.max())
                phase_refs[desc.name] = refs

        best_P, result = sweep_pressure(
            pt.positions,
            pt.heights,
            pt.fwhm,
            exp.phases,
            phase_refs,
            tol,
            P_min=0.0,
            P_max=60.0,
            n_coarse=301,
            n_fine=201,
        )

        # Noise estimate
        q25 = float(np.percentile(peaks, 25))
        lower_q = peaks[peaks <= q25]
        noise_sigma = float(np.std(lower_q))

        return best_P, result, exp.phases, noise_sigma

    def test_tungsten_lattice_param(self, snap_match):
        """Tungsten lattice param should be close to CIF value."""
        best_P, result, phases, noise_sigma = snap_match
        refinements = refine_all_phases(
            result,
            phases,
            noise_sigma=noise_sigma,
        )
        w_ref = next((r for r in refinements if r.phase_name == "tungsten"), None)
        assert w_ref is not None
        assert w_ref.success
        # Tungsten a ≈ 3.16 Å (compressed slightly at ~10 GPa)
        assert 3.0 < w_ref.a < 3.2

    def test_ice_vii_lattice_params(self, snap_match):
        """Ice VII lattice param should be significantly compressed."""
        best_P, result, phases, noise_sigma = snap_match
        refinements = refine_all_phases(
            result,
            phases,
            noise_sigma=noise_sigma,
        )
        ice_ref = next((r for r in refinements if r.phase_name == "ice-VII"), None)
        assert ice_ref is not None
        assert ice_ref.success
        # Ice VII a is ~3.39 Å at ambient, should be <3.35 at 10 GPa
        assert 2.8 < ice_ref.a < 3.4
        assert ice_ref.crystal_system == "cubic"

    def test_phase_pressures_from_eos(self, snap_match):
        """Both phases should give EOS-derived pressures."""
        best_P, result, phases, noise_sigma = snap_match
        refinements = refine_all_phases(
            result,
            phases,
            noise_sigma=noise_sigma,
        )
        for r in refinements:
            assert r.pressure_gpa is not None
            assert r.pressure_gpa > 0

    def test_pressure_spread_reasonable(self, snap_match):
        """Phase pressures should be in the same ballpark (< 10 GPa spread)."""
        best_P, result, phases, noise_sigma = snap_match
        refinements = refine_all_phases(
            result,
            phases,
            noise_sigma=noise_sigma,
        )
        pressures = [r.pressure_gpa for r in refinements if r.pressure_gpa is not None]
        if len(pressures) > 1:
            spread = max(pressures) - min(pressures)
            assert spread < 10.0

    def test_report_generation(self, snap_match):
        """Report should be non-empty and contain phase names."""
        best_P, result, phases, noise_sigma = snap_match
        refinements = refine_all_phases(
            result,
            phases,
            noise_sigma=noise_sigma,
        )
        report = format_refinement_report(refinements, sweep_pressure_gpa=best_P)
        assert "tungsten" in report
        assert "ice-VII" in report
        assert len(report) > 100
