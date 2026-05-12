"""Tests for the engine module.

Tests coordinate transforms (d_to_tof, tof_to_d) and the full
inspect() pipeline on SNAP data.
"""

from pathlib import Path

import numpy as np
import pytest

from snapwrap._inspectrum.engine import d_to_tof, inspect, tof_to_d
from snapwrap._inspectrum.models import Instrument

# ---------------------------------------------------------------------------
# Coordinate transforms
# ---------------------------------------------------------------------------


class TestDToTof:
    """Tests for d_to_tof."""

    def test_linear_conversion_no_difA(self):
        """TOF = difC * d + Zero when difA = 0."""
        inst = Instrument(difC=5000.0, zero=10.0, difA=0.0)
        d = np.array([1.0, 2.0, 3.0])
        tof = d_to_tof(d, inst)
        expected = 5000.0 * d + 10.0
        np.testing.assert_allclose(tof, expected)

    def test_with_difA(self):
        """TOF = difA * d^2 + difC * d + Zero."""
        inst = Instrument(difC=5000.0, zero=10.0, difA=1.5)
        d = np.array([2.0])
        expected = 1.5 * 4.0 + 5000.0 * 2.0 + 10.0
        tof = d_to_tof(d, inst)
        np.testing.assert_allclose(tof, [expected])


class TestTofToD:
    """Tests for tof_to_d."""

    def test_roundtrip_no_difA(self):
        """d -> TOF -> d should be identity when difA = 0."""
        inst = Instrument(difC=5218.45, zero=3.5, difA=0.0)
        d_orig = np.array([0.5, 1.0, 1.5, 2.0, 3.0])
        tof = d_to_tof(d_orig, inst)
        d_back = tof_to_d(tof, inst)
        np.testing.assert_allclose(d_back, d_orig, atol=1e-10)

    def test_roundtrip_with_difA(self):
        """d -> TOF -> d should be identity when difA != 0."""
        inst = Instrument(difC=5218.45, zero=3.5, difA=0.8)
        d_orig = np.array([0.5, 1.0, 1.5, 2.0, 3.0])
        tof = d_to_tof(d_orig, inst)
        d_back = tof_to_d(tof, inst)
        np.testing.assert_allclose(d_back, d_orig, atol=1e-10)


# ---------------------------------------------------------------------------
# Full pipeline: inspect()
# ---------------------------------------------------------------------------

TEST_DATA = Path(__file__).parent / "test_data"


class TestInspect:
    """Integration tests for the inspect() pipeline."""

    @pytest.fixture()
    def snap_inputs(self):
        """Load SNAP059056 data and phase descriptions."""
        from snapwrap._inspectrum.loaders import (
            load_gsa,
            load_instprm,
            load_phase_descriptions,
        )

        spectra = load_gsa(TEST_DATA / "SNAP059056_all.gsa")
        inst = load_instprm(TEST_DATA / "SNAP059056_all.instprm")
        exp = load_phase_descriptions(TEST_DATA / "snap_phases.json")
        return spectra[0], inst, exp

    def test_returns_inspection_result(self, snap_inputs):
        """inspect() returns an InspectionResult with expected fields."""
        spec, inst, exp = snap_inputs
        result = inspect(spec, inst, exp)

        assert result.match_result is not None
        assert result.peak_table is not None
        assert result.sweep_pressure_gpa is not None
        assert result.instrument is not None
        assert len(result.crystal_phases) > 0

    def test_finds_peaks(self, snap_inputs):
        """Pipeline finds a reasonable number of peaks."""
        spec, inst, exp = snap_inputs
        result = inspect(spec, inst, exp)

        n_peaks = len(result.peak_table.positions)
        assert n_peaks >= 5, f"Expected ≥5 peaks, got {n_peaks}"
        assert n_peaks <= 30, f"Expected ≤30 peaks, got {n_peaks}"

    def test_matches_both_phases(self, snap_inputs):
        """Both ice-VII and tungsten are matched."""
        spec, inst, exp = snap_inputs
        result = inspect(spec, inst, exp)

        phase_names = {
            pm.phase_name
            for pm in result.match_result.phase_matches
            if pm.n_matched > 0
        }
        assert "ice-VII" in phase_names
        assert "tungsten" in phase_names

    def test_refinements_produced(self, snap_inputs):
        """Lattice refinements are produced for matched phases."""
        spec, inst, exp = snap_inputs
        result = inspect(spec, inst, exp)

        assert len(result.refinements) >= 1
        ref_names = {r.phase_name for r in result.refinements}
        assert "ice-VII" in ref_names

    def test_ice_vii_lattice_parameter(self, snap_inputs):
        """Ice-VII refined lattice parameter is physically reasonable."""
        spec, inst, exp = snap_inputs
        result = inspect(spec, inst, exp)

        ice_ref = next(r for r in result.refinements if r.phase_name == "ice-VII")
        # At ~17 GPa, ice-VII a ≈ 3.0-3.1 Å
        assert 2.9 < ice_ref.a < 3.2, f"ice-VII a={ice_ref.a:.4f} out of range"

    def test_sweep_pressure_reasonable(self, snap_inputs):
        """Sweep pressure is in a physically reasonable range."""
        spec, inst, exp = snap_inputs
        result = inspect(spec, inst, exp)

        # SNAP059056 is at ~17 GPa
        assert 10.0 < result.sweep_pressure_gpa < 25.0

    def test_metadata_populated(self, snap_inputs):
        """Metadata contains diagnostic info."""
        spec, inst, exp = snap_inputs
        result = inspect(spec, inst, exp)

        assert "n_peaks_found" in result.metadata
        assert "n_phases_matched" in result.metadata
        assert "noise_sigma" in result.metadata
        assert result.metadata["n_phases_matched"] >= 1

    def test_does_not_mutate_inputs(self, snap_inputs):
        """inspect() does not modify the input objects."""
        spec, inst, exp = snap_inputs
        orig_difC = inst.difC
        orig_a = exp.phases[0].phase.a if exp.phases[0].phase else None

        inspect(spec, inst, exp)

        assert inst.difC == orig_difC
        if orig_a is not None:
            assert exp.phases[0].phase.a == orig_a

    def test_no_phases_raises(self, snap_inputs):
        """Empty experiment raises ValueError."""
        spec, inst, _ = snap_inputs
        from snapwrap._inspectrum.models import ExperimentDescription

        empty_exp = ExperimentDescription(phases=[])
        with pytest.raises(ValueError, match="No phases"):
            inspect(spec, inst, empty_exp)

    def test_flat_spectrum_returns_empty_result(self, snap_inputs):
        """A flat (peakless) spectrum returns gracefully with 0 matches."""
        _, inst, exp = snap_inputs
        from snapwrap._inspectrum.models import DiffractionSpectrum

        flat = DiffractionSpectrum(
            x=np.linspace(3000, 40000, 5000),
            y=np.full(5000, 100.0),
            e=np.full(5000, 10.0),
            x_unit="TOF",
        )
        result = inspect(flat, inst, exp)

        assert result.metadata["n_peaks_found"] == 0
        assert result.match_result is None
        assert result.refinements == []
