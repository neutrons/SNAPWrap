"""
Tests for inspectrum peak matching engine.

Tests progress from synthetic (controlled) to real (SNAP) data:
1. Synthetic: exact peak positions at known strain, verify recovery.
2. Noisy synthetic: perturbed positions, verify robustness.
3. Multi-phase: two sets of reflections, verify separation.
4. SNAP integration: real pre-processed spectra with known phases.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from snapwrap._inspectrum.matching import (
    identify_phases,
    match_peaks_at_strain,
    sweep_pressure,
    sweep_strain,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_reflections(d_values: list[float], f_sq: float = 100.0) -> list[dict]:
    """Build a minimal reflection list from d-spacings."""
    return [
        {
            "hkl": (1, 0, i),
            "d": d,
            "multiplicity": 6,
            "F_sq": f_sq,
        }
        for i, d in enumerate(d_values)
    ]


# ---------------------------------------------------------------------------
# match_peaks_at_strain
# ---------------------------------------------------------------------------


class TestMatchPeaksAtStrain:
    """Test single-strain matching."""

    def test_exact_match_no_strain(self):
        """Peaks at exact calculated positions should all match."""
        d_calc = [3.0, 2.0, 1.5, 1.0]
        refs = _make_reflections(d_calc)
        obs_d = np.array(d_calc)
        obs_h = np.ones(4)
        obs_fw = np.full(4, 0.01)

        matches = match_peaks_at_strain(obs_d, obs_h, obs_fw, refs, 1.0, 0.05)
        assert len(matches) == 4

    def test_exact_match_with_strain(self):
        """Peaks at strained positions should match at correct strain."""
        d_calc = [3.0, 2.0, 1.5, 1.0]
        strain = 0.95
        refs = _make_reflections(d_calc)
        obs_d = np.array([s * strain for s in d_calc])
        obs_h = np.ones(4)
        obs_fw = np.full(4, 0.01)

        matches = match_peaks_at_strain(obs_d, obs_h, obs_fw, refs, strain, 0.05)
        assert len(matches) == 4

    def test_no_match_outside_tolerance(self):
        """Peaks far from reflections should not match."""
        refs = _make_reflections([3.0, 2.0, 1.0])
        obs_d = np.array([3.5, 2.5, 1.5])  # all offset by 0.5
        obs_h = np.ones(3)
        obs_fw = np.full(3, 0.01)

        matches = match_peaks_at_strain(obs_d, obs_h, obs_fw, refs, 1.0, 0.1)
        assert len(matches) == 0

    def test_partial_match(self):
        """Only peaks within tolerance should match."""
        refs = _make_reflections([3.0, 2.0, 1.0])
        obs_d = np.array([3.01, 2.5, 1.01])  # 2.5 is too far
        obs_h = np.ones(3)
        obs_fw = np.full(3, 0.01)

        matches = match_peaks_at_strain(obs_d, obs_h, obs_fw, refs, 1.0, 0.05)
        assert len(matches) == 2

    def test_empty_observed(self):
        """No observed peaks gives no matches."""
        refs = _make_reflections([3.0, 2.0])
        matches = match_peaks_at_strain(
            np.array([]),
            np.array([]),
            np.array([]),
            refs,
            1.0,
            0.05,
        )
        assert len(matches) == 0

    def test_empty_reflections(self):
        """No reflections gives no matches."""
        obs_d = np.array([3.0, 2.0])
        matches = match_peaks_at_strain(
            obs_d,
            np.ones(2),
            np.full(2, 0.01),
            [],
            1.0,
            0.05,
        )
        assert len(matches) == 0

    def test_per_peak_tolerance(self):
        """Per-peak tolerance array is respected."""
        refs = _make_reflections([3.0, 1.0])
        obs_d = np.array([3.04, 1.04])
        obs_h = np.ones(2)
        obs_fw = np.full(2, 0.01)
        # Tight tolerance for first peak, loose for second
        tol = np.array([0.02, 0.10])

        matches = match_peaks_at_strain(obs_d, obs_h, obs_fw, refs, 1.0, tol)
        # Only the second peak should match (0.04 > 0.02 but 0.04 < 0.10)
        assert len(matches) == 1
        assert matches[0].obs_d == pytest.approx(1.04)

    def test_strong_reflections_get_priority(self):
        """When two reflections compete for one peak, stronger wins."""
        # Two reflections at nearly the same d, one much stronger
        refs = [
            {"hkl": (1, 0, 0), "d": 2.00, "multiplicity": 6, "F_sq": 1000.0},
            {"hkl": (1, 1, 0), "d": 2.02, "multiplicity": 12, "F_sq": 1.0},
        ]
        obs_d = np.array([2.01])  # equidistant from both
        obs_h = np.array([100.0])
        obs_fw = np.array([0.05])

        matches = match_peaks_at_strain(obs_d, obs_h, obs_fw, refs, 1.0, 0.05)
        assert len(matches) == 1
        # The stronger reflection (F²=1000) should claim the peak
        assert matches[0].hkl == (1, 0, 0)

    def test_residuals_computed(self):
        """Residual = obs_d - strained_d."""
        refs = _make_reflections([2.0])
        obs_d = np.array([1.92])
        obs_h = np.ones(1)
        obs_fw = np.full(1, 0.01)

        matches = match_peaks_at_strain(obs_d, obs_h, obs_fw, refs, 0.95, 0.05)
        assert len(matches) == 1
        # strained_d = 0.95 * 2.0 = 1.90
        assert matches[0].strained_d == pytest.approx(1.90)
        assert matches[0].residual == pytest.approx(0.02)


# ---------------------------------------------------------------------------
# sweep_strain
# ---------------------------------------------------------------------------


class TestSweepStrain:
    """Test strain sweep."""

    def test_recovers_known_strain(self):
        """Sweep should recover a known strain factor."""
        d_calc = [3.0, 2.5, 2.0, 1.5, 1.2, 1.0]
        true_strain = 0.96
        refs = _make_reflections(d_calc)
        obs_d = np.array([d * true_strain for d in d_calc])
        obs_h = np.ones(len(d_calc))
        obs_fw = np.full(len(d_calc), 0.01)

        best_s, matches, score = sweep_strain(
            obs_d,
            obs_h,
            obs_fw,
            refs,
            tolerance=0.02,
            s_min=0.90,
            s_max=1.05,
        )
        assert best_s == pytest.approx(true_strain, abs=0.001)
        assert len(matches) == len(d_calc)

    def test_no_peaks_returns_default(self):
        """Empty input returns strain 1.0 and no matches."""
        best_s, matches, score = sweep_strain(
            np.array([]),
            np.array([]),
            np.array([]),
            _make_reflections([2.0]),
            tolerance=0.02,
        )
        assert best_s == 1.0
        assert len(matches) == 0
        assert score == 0.0

    def test_no_reflections_returns_default(self):
        """Empty reflections returns strain 1.0."""
        best_s, matches, score = sweep_strain(
            np.array([2.0]),
            np.ones(1),
            np.full(1, 0.01),
            [],
            tolerance=0.02,
        )
        assert best_s == 1.0
        assert len(matches) == 0

    def test_fine_grid_improves_resolution(self):
        """Fine grid should improve strain precision."""
        d_calc = [3.0, 2.0, 1.5, 1.0]
        true_strain = 0.9537  # not on coarse grid
        refs = _make_reflections(d_calc)
        obs_d = np.array([d * true_strain for d in d_calc])
        obs_h = np.ones(4)
        obs_fw = np.full(4, 0.01)

        best_s, matches, score = sweep_strain(
            obs_d,
            obs_h,
            obs_fw,
            refs,
            tolerance=0.02,
            s_min=0.90,
            s_max=1.05,
            n_coarse=51,
            n_fine=201,
        )
        assert best_s == pytest.approx(true_strain, abs=0.001)

    def test_strain_near_unity(self):
        """No strain (s=1) should be recovered."""
        d_calc = [3.0, 2.0, 1.0]
        refs = _make_reflections(d_calc)
        obs_d = np.array(d_calc)
        obs_h = np.ones(3)
        obs_fw = np.full(3, 0.01)

        best_s, matches, _ = sweep_strain(
            obs_d,
            obs_h,
            obs_fw,
            refs,
            tolerance=0.02,
            s_min=0.95,
            s_max=1.05,
        )
        assert best_s == pytest.approx(1.0, abs=0.002)
        assert len(matches) == 3


# ---------------------------------------------------------------------------
# identify_phases
# ---------------------------------------------------------------------------


class TestIdentifyPhases:
    """Test multi-phase identification."""

    def test_two_phases_separated(self):
        """Two phases at different strains should be identified."""
        # Phase A: cubic with d = 3.0, 2.0, 1.5
        # Phase B: cubic with d = 2.8, 1.8, 1.3
        refs_a = _make_reflections([3.0, 2.0, 1.5])
        refs_b = _make_reflections([2.8, 1.8, 1.3])

        strain_a = 0.97
        strain_b = 0.94

        obs_d_a = [d * strain_a for d in [3.0, 2.0, 1.5]]
        obs_d_b = [d * strain_b for d in [2.8, 1.8, 1.3]]
        all_obs = np.array(sorted(obs_d_a + obs_d_b, reverse=True))
        all_h = np.ones(len(all_obs))
        all_fw = np.full(len(all_obs), 0.01)

        result = identify_phases(
            all_obs,
            all_h,
            all_fw,
            {"A": refs_a, "B": refs_b},
            tolerance=0.02,
            strain_ranges={"A": (0.94, 1.02), "B": (0.90, 0.98)},
        )

        assert len(result.phase_matches) == 2
        # Find phase A
        pm_a = next(pm for pm in result.phase_matches if pm.phase_name == "A")
        pm_b = next(pm for pm in result.phase_matches if pm.phase_name == "B")
        assert pm_a.strain == pytest.approx(strain_a, abs=0.002)
        assert pm_b.strain == pytest.approx(strain_b, abs=0.002)
        assert pm_a.n_matched >= 2
        assert pm_b.n_matched >= 2

    def test_unmatched_peaks_reported(self):
        """Observed peaks not matching any phase are flagged."""
        refs = _make_reflections([3.0, 2.0])
        # 3 observed: 2 match, 1 doesn't
        obs_d = np.array([3.0, 2.0, 1.5])
        obs_h = np.ones(3)
        obs_fw = np.full(3, 0.01)

        result = identify_phases(
            obs_d,
            obs_h,
            obs_fw,
            {"A": refs},
            tolerance=0.02,
            strain_ranges={"A": (0.99, 1.01)},
        )
        assert len(result.unmatched_indices) >= 1
        # The peak at 1.5 should be unmatched
        unmatched_d = [obs_d[i] for i in result.unmatched_indices]
        assert 1.5 in unmatched_d

    def test_contested_peak_goes_to_closer_phase(self):
        """When two phases claim the same peak, closer match wins."""
        # Both phases have a reflection near d=2.0
        refs_a = _make_reflections([2.000])
        refs_b = _make_reflections([2.005])
        obs_d = np.array([2.001])  # closer to A
        obs_h = np.ones(1)
        obs_fw = np.full(1, 0.01)

        result = identify_phases(
            obs_d,
            obs_h,
            obs_fw,
            {"A": refs_a, "B": refs_b},
            tolerance=0.02,
            strain_ranges={"A": (0.99, 1.01), "B": (0.99, 1.01)},
        )

        pm_a = next(pm for pm in result.phase_matches if pm.phase_name == "A")
        pm_b = next(pm for pm in result.phase_matches if pm.phase_name == "B")
        # A should get the peak (|2.001 - 2.000| < |2.001 - 2.005|)
        assert pm_a.n_matched == 1
        assert pm_b.n_matched == 0

    def test_sorted_by_score(self):
        """Phase matches should be sorted by score descending."""
        refs_a = _make_reflections([3.0, 2.0, 1.5, 1.0], f_sq=200.0)
        refs_b = _make_reflections([2.8])

        obs_d = np.array([3.0, 2.8, 2.0, 1.5, 1.0])
        obs_h = np.ones(5)
        obs_fw = np.full(5, 0.01)

        result = identify_phases(
            obs_d,
            obs_h,
            obs_fw,
            {"A": refs_a, "B": refs_b},
            tolerance=0.02,
            strain_ranges={"A": (0.99, 1.01), "B": (0.99, 1.01)},
        )
        # A has 4 matches, B has 1 → A should be first
        assert result.phase_matches[0].phase_name == "A"

    def test_default_strain_range(self):
        """Without explicit range, uses [0.90, 1.10]."""
        refs = _make_reflections([2.0])
        obs_d = np.array([2.0])
        obs_h = np.ones(1)
        obs_fw = np.full(1, 0.01)

        result = identify_phases(
            obs_d,
            obs_h,
            obs_fw,
            {"A": refs},
            tolerance=0.05,
        )
        assert result.phase_matches[0].n_matched == 1


# ---------------------------------------------------------------------------
# SNAP integration test
# ---------------------------------------------------------------------------

TEST_DATA = Path(__file__).parent / "test_data"


class TestSNAPIntegration:
    """Integration test: run matching on real SNAP data."""

    @pytest.fixture
    def snap_pipeline(self):
        """Load one SNAP spectrum through the full pre-processing pipeline.

        Returns:
            Tuple of (obs_d, obs_heights, obs_fwhm, phase_reflections,
                      experiment, instrument)
        """
        from snapwrap._inspectrum.background import estimate_background
        from snapwrap._inspectrum.crystallography import generate_reflections
        from snapwrap._inspectrum.loaders import (
            load_gsa,
            load_instprm,
            load_phase_descriptions,
        )
        from snapwrap._inspectrum.peakfinding import find_peaks_in_spectrum
        from snapwrap._inspectrum.resolution import fwhm_at_d, parse_resolution_curve

        # Load data
        spectra = load_gsa(TEST_DATA / "SNAP059056_all.gsa")
        spec = spectra[0]
        inst = load_instprm(TEST_DATA / "SNAP059056_all.instprm")
        exp = load_phase_descriptions(TEST_DATA / "snap_phases.json")

        # Background subtraction
        _, peaks = estimate_background(spec.y)

        # Resolution curve for tolerance
        d_curve, fwhm_curve = parse_resolution_curve(inst)

        # Peak finding (in d-spacing)
        from snapwrap._inspectrum.engine import tof_to_d

        d_axis = tof_to_d(spec.x, inst)
        peak_table = find_peaks_in_spectrum(
            d_axis,
            peaks,
            resolution=(d_curve, fwhm_curve),
        )

        # Tolerance: 1.0 × instrument FWHM at each observed d-spacing
        tol = fwhm_at_d(peak_table.positions, d_curve, fwhm_curve)

        # Generate reflections for each phase
        d_min, d_max = d_axis.min(), d_axis.max()
        phase_refs: dict[str, list[dict]] = {}
        for desc in exp.phases:
            if desc.phase is not None:
                refs = generate_reflections(desc.phase, d_min, d_max)
                phase_refs[desc.name] = refs

        return (
            peak_table.positions,
            peak_table.heights,
            peak_table.fwhm,
            phase_refs,
            tol,
            exp,
        )

    def test_tungsten_found(self, snap_pipeline):
        """Tungsten (calibrant) should be identified in SNAP data."""
        obs_d, obs_h, obs_fw, phase_refs, tol, exp = snap_pipeline

        result = identify_phases(
            obs_d,
            obs_h,
            obs_fw,
            phase_refs,
            tol,
            # Tungsten is a calibrant, strain should be near 1.0
            strain_ranges={"tungsten": (0.95, 1.05), "ice-VII": (0.80, 1.05)},
        )

        # Find tungsten in results
        w_match = next(
            (pm for pm in result.phase_matches if pm.phase_name == "tungsten"),
            None,
        )
        assert w_match is not None, "Tungsten not found in phase matches"
        assert (
            w_match.n_matched >= 2
        ), f"Expected ≥2 tungsten peaks matched, got {w_match.n_matched}"

    def test_ice_vii_found(self, snap_pipeline):
        """Ice VII (sample) should be identified in SNAP data."""
        obs_d, obs_h, obs_fw, phase_refs, tol, exp = snap_pipeline

        result = identify_phases(
            obs_d,
            obs_h,
            obs_fw,
            phase_refs,
            tol,
            strain_ranges={"tungsten": (0.95, 1.05), "ice-VII": (0.80, 1.05)},
        )

        ice_match = next(
            (pm for pm in result.phase_matches if pm.phase_name == "ice-VII"),
            None,
        )
        assert ice_match is not None, "Ice VII not found in phase matches"
        assert (
            ice_match.n_matched >= 1
        ), f"Expected ≥1 ice VII peaks matched, got {ice_match.n_matched}"

    def test_tungsten_strain_near_unity(self, snap_pipeline):
        """Tungsten calibrant should have strain close to 1.0.

        At ~10 GPa, tungsten (very stiff, K₀=295 GPa) is only
        slightly compressed: s ≈ 0.989.  The independent strain
        sweep should recover a strain within 0.04 of unity.
        """
        obs_d, obs_h, obs_fw, phase_refs, tol, exp = snap_pipeline

        result = identify_phases(
            obs_d,
            obs_h,
            obs_fw,
            phase_refs,
            tol,
            strain_ranges={"tungsten": (0.95, 1.05), "ice-VII": (0.80, 1.05)},
        )

        w_match = next(pm for pm in result.phase_matches if pm.phase_name == "tungsten")
        # Tungsten is stiff but IS compressed at ~10 GPa (s ≈ 0.989).
        # With an independent strain sweep, recovery is approximate.
        assert w_match.strain == pytest.approx(1.0, abs=0.04)

    def test_ice_vii_strain_shows_compression(self, snap_pipeline):
        """Ice VII under pressure should show compression (s < 1)."""
        obs_d, obs_h, obs_fw, phase_refs, tol, exp = snap_pipeline

        result = identify_phases(
            obs_d,
            obs_h,
            obs_fw,
            phase_refs,
            tol,
            strain_ranges={"tungsten": (0.95, 1.05), "ice-VII": (0.80, 1.05)},
        )

        ice_match = next(
            pm for pm in result.phase_matches if pm.phase_name == "ice-VII"
        )
        # Ice VII should be compressed (strain < 1)
        # At pressures > 2.1 GPa, we expect measurable compression
        assert ice_match.strain < 1.0

    def test_not_too_many_unmatched(self, snap_pipeline):
        """Most observed peaks should be assigned to a phase."""
        obs_d, obs_h, obs_fw, phase_refs, tol, exp = snap_pipeline

        result = identify_phases(
            obs_d,
            obs_h,
            obs_fw,
            phase_refs,
            tol,
            strain_ranges={"tungsten": (0.95, 1.05), "ice-VII": (0.80, 1.05)},
        )

        total_matched = sum(pm.n_matched for pm in result.phase_matches)
        total_obs = len(obs_d)
        # At least 30% of peaks should be matched
        assert (
            total_matched / total_obs > 0.3
        ), f"Only {total_matched}/{total_obs} peaks matched"


# ---------------------------------------------------------------------------
# sweep_pressure (physics-informed matching)
# ---------------------------------------------------------------------------


class TestSweepPressure:
    """Test pressure-based matching with EOS constraints."""

    @staticmethod
    def _make_phase_desc(
        name: str,
        eos_type: str = "vinet",
        K_0: float = 100.0,
        K_prime: float = 4.0,
        V_0: float = 30.0,
        stability: tuple[float | None, float | None] | None = None,
    ):
        """Build a minimal PhaseDescription with EOS for testing."""
        from snapwrap._inspectrum.models import EquationOfState, PhaseDescription

        eos = EquationOfState(
            eos_type=eos_type,
            V_0=V_0,
            K_0=K_0,
            K_prime=K_prime,
        )
        return PhaseDescription(
            name=name,
            cif_path="",
            eos=eos,
            stability_pressure=stability,
        )

    def test_recovers_known_pressure_single_phase(self):
        """Sweep should recover the pressure for a single phase."""
        from snapwrap._inspectrum.eos import predicted_strain

        desc = self._make_phase_desc("A", K_0=200.0, K_prime=4.0, V_0=25.0)
        true_P = 15.0
        true_s = predicted_strain(desc.eos, true_P)

        # Observed peaks = strained reflections
        d_calc = [3.0, 2.5, 2.0, 1.5, 1.0]
        refs = _make_reflections(d_calc)
        obs_d = np.array([d * true_s for d in d_calc])
        obs_h = np.ones(len(d_calc))
        obs_fw = np.full(len(d_calc), 0.01)

        best_P, result = sweep_pressure(
            obs_d,
            obs_h,
            obs_fw,
            [desc],
            {"A": refs},
            tolerance=0.02,
            P_min=0.0,
            P_max=40.0,
            n_coarse=201,
            n_fine=201,
        )
        assert best_P == pytest.approx(true_P, abs=0.5)
        pm = result.phase_matches[0]
        assert pm.n_matched == len(d_calc)

    def test_recovers_pressure_two_phases(self):
        """Pressure sweep constrains both phases simultaneously."""
        from snapwrap._inspectrum.eos import predicted_strain

        # A stiff phase (like tungsten) and a soft phase (like ice)
        stiff = self._make_phase_desc("stiff", K_0=300.0, K_prime=4.3, V_0=32.0)
        soft = self._make_phase_desc(
            "soft", eos_type="birch-murnaghan", K_0=25.0, K_prime=4.0, V_0=40.0
        )
        true_P = 12.0
        s_stiff = predicted_strain(stiff.eos, true_P)
        s_soft = predicted_strain(soft.eos, true_P)

        # Distinct reflection sets
        d_stiff = [3.0, 2.0, 1.5]
        d_soft = [2.7, 1.8, 1.2]
        refs_stiff = _make_reflections(d_stiff, f_sq=200.0)
        refs_soft = _make_reflections(d_soft, f_sq=100.0)

        obs_stiff = [d * s_stiff for d in d_stiff]
        obs_soft = [d * s_soft for d in d_soft]
        all_obs = np.array(sorted(obs_stiff + obs_soft, reverse=True))
        all_h = np.ones(len(all_obs))
        all_fw = np.full(len(all_obs), 0.01)

        best_P, result = sweep_pressure(
            all_obs,
            all_h,
            all_fw,
            [stiff, soft],
            {"stiff": refs_stiff, "soft": refs_soft},
            tolerance=0.02,
            P_min=0.0,
            P_max=30.0,
            n_coarse=201,
            n_fine=201,
        )
        assert best_P == pytest.approx(true_P, abs=1.0)
        total_matched = sum(pm.n_matched for pm in result.phase_matches)
        assert total_matched >= 5

    def test_stability_excludes_phase(self):
        """Phases not stable at found pressure are excluded."""
        from snapwrap._inspectrum.eos import predicted_strain

        # Phase only stable above 20 GPa
        desc = self._make_phase_desc(
            "high_P_only",
            K_0=100.0,
            V_0=30.0,
            stability=(20.0, None),
        )
        d_calc = [3.0, 2.0, 1.5]
        refs = _make_reflections(d_calc)
        # Place peaks at a low-pressure strain (5 GPa)
        s = predicted_strain(desc.eos, 5.0)
        obs_d = np.array([d * s for d in d_calc])
        obs_h = np.ones(3)
        obs_fw = np.full(3, 0.01)

        # Sweep only in the range where the phase is NOT stable
        best_P, result = sweep_pressure(
            obs_d,
            obs_h,
            obs_fw,
            [desc],
            {"high_P_only": refs},
            tolerance=0.02,
            P_min=0.0,
            P_max=15.0,
        )
        # Phase should not appear (skipped due to stability)
        if result.phase_matches:
            assert result.phase_matches[0].n_matched == 0

    def test_no_eos_phases_skipped(self):
        """Phases without EOS produce no matches."""
        from snapwrap._inspectrum.models import PhaseDescription

        desc = PhaseDescription(name="no_eos", cif_path="")
        refs = _make_reflections([3.0, 2.0])
        obs_d = np.array([3.0, 2.0])
        obs_h = np.ones(2)
        obs_fw = np.full(2, 0.01)

        best_P, result = sweep_pressure(
            obs_d,
            obs_h,
            obs_fw,
            [desc],
            {"no_eos": refs},
            tolerance=0.02,
        )
        assert best_P == 0.0
        assert len(result.phase_matches) == 0

    def test_empty_observed_returns_zero(self):
        """No observed peaks gives pressure 0 and no matches."""
        desc = self._make_phase_desc("A")
        refs = _make_reflections([3.0])
        best_P, result = sweep_pressure(
            np.array([]),
            np.array([]),
            np.array([]),
            [desc],
            {"A": refs},
            tolerance=0.02,
        )
        assert best_P == 0.0
        assert len(result.phase_matches) == 0


class TestSweepPressureSNAP:
    """Integration: sweep_pressure on real SNAP data."""

    @pytest.fixture
    def snap_data(self):
        """Load SNAP spectrum and generate reflections."""
        from snapwrap._inspectrum.background import estimate_background
        from snapwrap._inspectrum.crystallography import generate_reflections
        from snapwrap._inspectrum.engine import tof_to_d
        from snapwrap._inspectrum.loaders import (
            load_gsa,
            load_instprm,
            load_phase_descriptions,
        )
        from snapwrap._inspectrum.peakfinding import find_peaks_in_spectrum
        from snapwrap._inspectrum.resolution import fwhm_at_d, parse_resolution_curve

        spectra = load_gsa(TEST_DATA / "SNAP059056_all.gsa")
        spec = spectra[0]
        inst = load_instprm(TEST_DATA / "SNAP059056_all.instprm")
        exp = load_phase_descriptions(TEST_DATA / "snap_phases.json")

        _, peaks = estimate_background(spec.y)
        d_curve, fwhm_curve = parse_resolution_curve(inst)
        d_axis = tof_to_d(spec.x, inst)
        peak_table = find_peaks_in_spectrum(
            d_axis,
            peaks,
            resolution=(d_curve, fwhm_curve),
        )
        tol = fwhm_at_d(peak_table.positions, d_curve, fwhm_curve)

        d_min, d_max = d_axis.min(), d_axis.max()
        phase_refs: dict[str, list[dict]] = {}
        for desc in exp.phases:
            if desc.phase is not None:
                refs = generate_reflections(desc.phase, d_min, d_max)
                phase_refs[desc.name] = refs

        return peak_table, phase_refs, tol, exp

    def test_pressure_in_reasonable_range(self, snap_data):
        """Recovered pressure should be physically plausible."""
        peak_table, phase_refs, tol, exp = snap_data

        best_P, result = sweep_pressure(
            peak_table.positions,
            peak_table.heights,
            peak_table.fwhm,
            exp.phases,
            phase_refs,
            tol,
            P_min=0.0,
            P_max=60.0,
            n_coarse=301,
            n_fine=201,
        )
        # SNAP DAC experiments typically 2-60 GPa.
        # Ice-VII is stable above 2.1 GPa.
        assert 2.0 < best_P < 60.0

    def test_tungsten_found_with_pressure(self, snap_data):
        """Tungsten should match ≥1 peak at the recovered pressure."""
        peak_table, phase_refs, tol, exp = snap_data

        best_P, result = sweep_pressure(
            peak_table.positions,
            peak_table.heights,
            peak_table.fwhm,
            exp.phases,
            phase_refs,
            tol,
            P_min=0.0,
            P_max=60.0,
            n_coarse=301,
            n_fine=201,
        )

        w_match = next(
            (pm for pm in result.phase_matches if pm.phase_name == "tungsten"),
            None,
        )
        assert w_match is not None, "Tungsten not found"
        assert w_match.n_matched >= 1

    def test_ice_vii_found_with_pressure(self, snap_data):
        """Ice VII should match ≥3 peaks at the recovered pressure."""
        peak_table, phase_refs, tol, exp = snap_data

        best_P, result = sweep_pressure(
            peak_table.positions,
            peak_table.heights,
            peak_table.fwhm,
            exp.phases,
            phase_refs,
            tol,
            P_min=0.0,
            P_max=60.0,
            n_coarse=301,
            n_fine=201,
        )

        ice_match = next(
            (pm for pm in result.phase_matches if pm.phase_name == "ice-VII"),
            None,
        )
        assert ice_match is not None, "Ice VII not found"
        assert ice_match.n_matched >= 3

    def test_pressure_sweep_beats_blind_strain_sweep(self, snap_data):
        """Pressure sweep should match more peaks than blind strain."""
        peak_table, phase_refs, tol, exp = snap_data

        # Pressure sweep
        _, p_result = sweep_pressure(
            peak_table.positions,
            peak_table.heights,
            peak_table.fwhm,
            exp.phases,
            phase_refs,
            tol,
            P_min=0.0,
            P_max=60.0,
            n_coarse=301,
            n_fine=201,
        )
        p_matched = sum(pm.n_matched for pm in p_result.phase_matches)

        # Blind strain sweep
        s_result = identify_phases(
            peak_table.positions,
            peak_table.heights,
            peak_table.fwhm,
            phase_refs,
            tol,
            strain_ranges={"tungsten": (0.95, 1.05), "ice-VII": (0.80, 1.05)},
        )
        s_matched = sum(pm.n_matched for pm in s_result.phase_matches)

        assert (
            p_matched >= s_matched
        ), f"Pressure sweep matched {p_matched}, blind sweep matched {s_matched}"

    def test_tungsten_strain_consistent_with_eos(self, snap_data):
        """Tungsten strain should match EOS prediction at found pressure."""
        from snapwrap._inspectrum.eos import predicted_strain

        peak_table, phase_refs, tol, exp = snap_data

        best_P, result = sweep_pressure(
            peak_table.positions,
            peak_table.heights,
            peak_table.fwhm,
            exp.phases,
            phase_refs,
            tol,
            P_min=0.0,
            P_max=60.0,
            n_coarse=301,
            n_fine=201,
        )

        w_match = next(pm for pm in result.phase_matches if pm.phase_name == "tungsten")
        w_desc = next(d for d in exp.phases if d.name == "tungsten")
        expected_strain = predicted_strain(w_desc.eos, best_P)
        # Strain in PhaseMatch is set by EOS, so should match exactly
        assert w_match.strain == pytest.approx(expected_strain, abs=1e-6)
