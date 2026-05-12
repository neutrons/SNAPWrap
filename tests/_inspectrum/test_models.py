"""
Tests for inspectrum data models.

Covers DiffractionSpectrum, DiffractionDataset, CrystalPhase,
Instrument, and InspectionResult.
"""

import numpy as np
import pytest

from snapwrap._inspectrum.models import (
    CrystalPhase,
    DiffractionDataset,
    DiffractionSpectrum,
    EquationOfState,
    ExperimentDescription,
    InspectionResult,
    Instrument,
    PhaseDescription,
    SampleConditions,
    SpectrumConditions,
)

# ---------------------------------------------------------------------------
# DiffractionSpectrum
# ---------------------------------------------------------------------------


class TestDiffractionSpectrum:
    """Tests for DiffractionSpectrum."""

    def test_create_spectrum_with_valid_data(self):
        """Test creating a spectrum with consistent x, y, e arrays."""
        x = np.array([0.79, 0.80, 0.81])
        y = np.array([85.0, 88.0, 91.0])
        e = np.array([2.1, 1.9, 1.8])
        spec = DiffractionSpectrum(x=x, y=y, e=e, label="test")

        assert spec.n_points == 3
        assert spec.label == "test"
        assert spec.bank == 0

    def test_d_min_and_d_max(self):
        """Test d_min and d_max properties."""
        x = np.array([0.79, 1.50, 2.50])
        y = np.zeros(3)
        e = np.zeros(3)
        spec = DiffractionSpectrum(x=x, y=y, e=e)

        assert spec.d_min == pytest.approx(0.79)
        assert spec.d_max == pytest.approx(2.50)

    def test_mismatched_array_lengths_raises_error(self):
        """Test that mismatched x, y, e lengths raise ValueError."""
        x = np.array([0.79, 0.80])
        y = np.array([85.0, 88.0, 91.0])
        e = np.array([2.1, 1.9])

        with pytest.raises(ValueError, match="equal length"):
            DiffractionSpectrum(x=x, y=y, e=e)

    def test_repr_contains_key_info(self):
        """Test that repr includes label, bank, n_points, d_range."""
        spec = DiffractionSpectrum(
            x=np.array([1.0, 2.0]),
            y=np.zeros(2),
            e=np.zeros(2),
            label="SNAP059056",
            bank=1,
        )
        r = repr(spec)
        assert "SNAP059056" in r
        assert "bank=1" in r
        assert "n_points=2" in r

    def test_default_units(self):
        """Test default x and y unit labels."""
        spec = DiffractionSpectrum(x=np.zeros(1), y=np.zeros(1), e=np.zeros(1))
        assert spec.x_unit == "d-Spacing"
        assert "Counts" in spec.y_unit


# ---------------------------------------------------------------------------
# DiffractionDataset
# ---------------------------------------------------------------------------


class TestDiffractionDataset:
    """Tests for DiffractionDataset."""

    def test_empty_dataset(self):
        """Test creating an empty dataset."""
        ds = DiffractionDataset(label="empty")
        assert ds.n_spectra == 0
        assert len(ds) == 0

    def test_dataset_with_spectra(self):
        """Test dataset indexing and length."""
        specs = [
            DiffractionSpectrum(
                x=np.zeros(5), y=np.zeros(5), e=np.zeros(5), label=f"run{i}"
            )
            for i in range(3)
        ]
        ds = DiffractionDataset(spectra=specs, label="pressure_series")

        assert ds.n_spectra == 3
        assert len(ds) == 3
        assert ds[0].label == "run0"
        assert ds[2].label == "run2"

    def test_repr_shows_count(self):
        """Test repr includes spectrum count."""
        ds = DiffractionDataset(label="test")
        assert "n_spectra=0" in repr(ds)


# ---------------------------------------------------------------------------
# CrystalPhase
# ---------------------------------------------------------------------------


class TestCrystalPhase:
    """Tests for CrystalPhase."""

    def test_tungsten_cubic_volume(self):
        """Test volume calculation for BCC tungsten (cubic)."""
        # Tungsten: a = 3.16475 Å, cubic
        w = CrystalPhase(
            name="tungsten",
            a=3.16475,
            b=3.16475,
            c=3.16475,
            alpha=90.0,
            beta=90.0,
            gamma=90.0,
            space_group="I m -3 m",
            space_group_number=229,
        )
        # V = a³ for cubic
        expected_volume = 3.16475**3
        assert w.volume == pytest.approx(expected_volume, rel=1e-6)

    def test_ice_vii_volume(self):
        """Test volume calculation for ice VII (cubic)."""
        ice = CrystalPhase(
            name="ice-VII",
            a=3.3891,
            b=3.3891,
            c=3.3891,
            alpha=90.0,
            beta=90.0,
            gamma=90.0,
            space_group="P n -3 m Z",
            space_group_number=224,
        )
        expected_volume = 3.3891**3
        assert ice.volume == pytest.approx(expected_volume, rel=1e-6)

    def test_copy_is_independent(self):
        """Test that copy() returns a deep copy."""
        original = CrystalPhase(
            name="tungsten",
            a=3.16475,
            b=3.16475,
            c=3.16475,
            atom_sites=[{"label": "W1", "fract_x": 0.0}],
        )
        copied = original.copy()

        # Modify the copy
        copied.a = 3.20
        copied.atom_sites[0]["fract_x"] = 0.5

        # Original must be untouched
        assert original.a == pytest.approx(3.16475)
        assert original.atom_sites[0]["fract_x"] == pytest.approx(0.0)

    def test_default_scale_is_one(self):
        """Test that default scale factor is 1.0."""
        phase = CrystalPhase(name="test")
        assert phase.scale == pytest.approx(1.0)

    def test_repr_contains_name_and_space_group(self):
        """Test repr shows name and space group."""
        phase = CrystalPhase(
            name="tungsten",
            a=3.16,
            b=3.16,
            c=3.16,
            space_group="I m -3 m",
            space_group_number=229,
        )
        r = repr(phase)
        assert "tungsten" in r
        assert "I m -3 m" in r
        assert "#229" in r


# ---------------------------------------------------------------------------
# Instrument
# ---------------------------------------------------------------------------


class TestInstrument:
    """Tests for Instrument."""

    def test_create_snap_instrument(self):
        """Test creating an instrument with SNAP-like parameters."""
        inst = Instrument(
            inst_type="PNT",
            bank=1,
            two_theta=85.3035,
            flt_path=15.5806,
            difC=5218.45,
            alpha=0.986512012223,
            beta_0=0.0235,
            beta_1=0.03,
            sig_1=66.0,
        )
        assert inst.difC == pytest.approx(5218.45)
        assert inst.two_theta == pytest.approx(85.3035)

    def test_params_dict_contains_all_keys(self):
        """Test that params property returns all expected keys."""
        inst = Instrument(difC=5218.45, sig_1=66.0)
        p = inst.params

        expected_keys = {
            "difA",
            "difB",
            "difC",
            "Zero",
            "2-theta",
            "fltPath",
            "alpha",
            "beta-0",
            "beta-1",
            "beta-q",
            "sig-0",
            "sig-1",
            "sig-2",
            "sig-q",
            "X",
            "Y",
            "Z",
            "Azimuth",
        }
        assert set(p.keys()) == expected_keys
        assert p["difC"] == pytest.approx(5218.45)
        assert p["sig-1"] == pytest.approx(66.0)

    def test_copy_is_independent(self):
        """Test that copy() returns a deep copy."""
        original = Instrument(difC=5218.45)
        copied = original.copy()
        copied.difC = 9999.0

        assert original.difC == pytest.approx(5218.45)

    def test_repr_contains_key_values(self):
        """Test repr shows type, bank, 2θ, difC."""
        inst = Instrument(
            inst_type="PNT",
            bank=1,
            two_theta=85.3,
            difC=5218.45,
            flt_path=15.58,
        )
        r = repr(inst)
        assert "PNT" in r
        assert "bank=1" in r
        assert "5218.45" in r


# ---------------------------------------------------------------------------
# InspectionResult
# ---------------------------------------------------------------------------


class TestInspectionResult:
    """Tests for InspectionResult."""

    def test_create_empty_result(self):
        """Test creating a result with defaults."""
        result = InspectionResult()
        assert result.crystal_phases == []
        assert result.instrument is None
        assert result.match_result is None
        assert result.refinements == []
        assert result.peak_table is None
        assert result.sweep_pressure_gpa is None
        assert result.processed_spectra is None
        assert result.chi_squared is None

    def test_result_with_phases_and_instrument(self):
        """Test creating a result with phases and instrument."""
        phases = [
            CrystalPhase(name="tungsten", a=3.16),
            CrystalPhase(name="ice-VII", a=3.39),
        ]
        inst = Instrument(difC=5218.45)
        result = InspectionResult(
            crystal_phases=phases,
            instrument=inst,
            chi_squared=1.23,
        )
        assert len(result.crystal_phases) == 2
        assert result.instrument is not None
        assert result.chi_squared == pytest.approx(1.23)

    def test_repr_shows_phase_names(self):
        """Test repr shows phase names."""
        result = InspectionResult(
            crystal_phases=[CrystalPhase(name="tungsten")],
        )
        r = repr(result)
        assert "tungsten" in r


# ---------------------------------------------------------------------------
# EquationOfState
# ---------------------------------------------------------------------------


class TestEquationOfState:
    """Tests for EquationOfState."""

    def test_create_birch_murnaghan(self):
        """Test creating a 3rd-order BM EOS with valid parameters."""
        eos = EquationOfState(
            eos_type="birch-murnaghan",
            V_0=40.85,
            K_0=23.7,
            K_prime=4.15,
            source="Hemley et al., Nature 330 (1987)",
        )
        assert eos.eos_type == "birch-murnaghan"
        assert pytest.approx(40.85) == eos.V_0
        assert pytest.approx(23.7) == eos.K_0
        assert eos.source != ""

    def test_create_vinet(self):
        """Test creating a Vinet EOS."""
        eos = EquationOfState(
            eos_type="vinet",
            V_0=31.724,
            K_0=295.2,
            K_prime=4.32,
        )
        assert eos.eos_type == "vinet"

    def test_invalid_eos_type_raises_error(self):
        """Test that an unsupported EOS type raises ValueError."""
        with pytest.raises(ValueError, match="eos_type"):
            EquationOfState(eos_type="unknown", V_0=10.0, K_0=100.0)

    def test_non_positive_V0_raises_error(self):
        """Test that V₀ ≤ 0 raises ValueError."""
        with pytest.raises(ValueError, match="V_0"):
            EquationOfState(V_0=0.0, K_0=100.0)

    def test_non_positive_K0_raises_error(self):
        """Test that K₀ ≤ 0 raises ValueError."""
        with pytest.raises(ValueError, match="K_0"):
            EquationOfState(V_0=30.0, K_0=-1.0)

    def test_extra_stores_uncertainties(self):
        """Test that extra dict stores error values."""
        eos = EquationOfState(
            V_0=31.724,
            K_0=295.2,
            extra={"K_0_err": 3.9, "K_prime_err": 0.11},
        )
        assert eos.extra["K_0_err"] == pytest.approx(3.9)

    def test_repr_readable(self):
        """Test repr includes key parameters."""
        eos = EquationOfState(V_0=31.724, K_0=295.2, K_prime=4.32)
        r = repr(eos)
        assert "295.2" in r
        assert "birch-murnaghan" in r


# ---------------------------------------------------------------------------
# SampleConditions
# ---------------------------------------------------------------------------


class TestSampleConditions:
    """Tests for SampleConditions."""

    def test_defaults_are_none(self):
        """Test that defaults represent ambient/unknown."""
        cond = SampleConditions()
        assert cond.pressure is None
        assert cond.temperature is None

    def test_with_pressure_and_temperature(self):
        """Test creating conditions with both values."""
        cond = SampleConditions(pressure=3.5, temperature=300)
        assert cond.pressure == pytest.approx(3.5)
        assert cond.temperature == pytest.approx(300)

    def test_repr_ambient(self):
        """Test repr for unknown conditions."""
        assert "ambient" in repr(SampleConditions())

    def test_repr_with_pressure(self):
        """Test repr includes pressure when set."""
        cond = SampleConditions(pressure=5.0)
        assert "5.0 GPa" in repr(cond)


# ---------------------------------------------------------------------------
# PhaseDescription
# ---------------------------------------------------------------------------


class TestPhaseDescription:
    """Tests for PhaseDescription."""

    def test_create_minimal(self):
        """Test creating a description with just a name."""
        desc = PhaseDescription(name="tungsten", cif_path="w.cif")
        assert desc.role == "sample"
        assert desc.eos is None
        assert desc.phase is None

    def test_calibrant_role(self):
        """Test creating a calibrant phase."""
        desc = PhaseDescription(name="tungsten", role="calibrant")
        assert desc.role == "calibrant"

    def test_invalid_role_raises_error(self):
        """Test that invalid role raises ValueError."""
        with pytest.raises(ValueError, match="role"):
            PhaseDescription(role="unknown")

    def test_is_stable_at_no_constraint(self):
        """Test stability check with no pressure range set."""
        desc = PhaseDescription(name="W")
        assert desc.is_stable_at(100.0) is True
        assert desc.is_stable_at(None) is True

    def test_is_stable_at_within_range(self):
        """Test stability check within defined range."""
        desc = PhaseDescription(
            name="ice-VII",
            stability_pressure=(2.1, 40.0),
        )
        assert desc.is_stable_at(5.0) is True
        assert desc.is_stable_at(1.0) is False
        assert desc.is_stable_at(50.0) is False

    def test_is_stable_at_open_ended(self):
        """Test stability with open-ended range (None upper bound)."""
        desc = PhaseDescription(
            name="ice-VII",
            stability_pressure=(2.1, None),
        )
        assert desc.is_stable_at(100.0) is True
        assert desc.is_stable_at(1.0) is False

    def test_is_stable_at_unknown_pressure(self):
        """Test that unknown pressure always returns True."""
        desc = PhaseDescription(
            name="ice-VII",
            stability_pressure=(2.1, None),
        )
        assert desc.is_stable_at(None) is True

    def test_repr_shows_eos_type(self):
        """Test repr includes EOS type when present."""
        desc = PhaseDescription(
            name="W",
            eos=EquationOfState(
                eos_type="vinet",
                V_0=31.7,
                K_0=295.2,
            ),
        )
        assert "vinet" in repr(desc)


# ---------------------------------------------------------------------------
# SpectrumConditions
# ---------------------------------------------------------------------------


class TestSpectrumConditions:
    """Tests for SpectrumConditions."""

    def test_create_with_label(self):
        """Test creating per-spectrum conditions."""
        sc = SpectrumConditions(label="SNAP059056", pressure=3.5)
        assert sc.label == "SNAP059056"
        assert sc.pressure == pytest.approx(3.5)
        assert sc.temperature is None

    def test_create_with_run_number(self):
        """Test creating conditions with run_number and instrument."""
        sc = SpectrumConditions(
            run_number=59056,
            instrument="SNAP",
            facility="SNS",
            pgs="all",
        )
        assert sc.run_number == 59056
        assert sc.instrument == "SNAP"
        assert sc.facility == "SNS"
        assert sc.pgs == "all"

    def test_resolved_label_from_run_number(self):
        """Test label is derived from instrument + run_number."""
        sc = SpectrumConditions(run_number=59056, instrument="SNAP")
        assert sc.resolved_label() == "SNAP059056"

    def test_resolved_label_from_global_instrument(self):
        """Test label uses default_instrument when per-entry is None."""
        sc = SpectrumConditions(run_number=59056)
        assert sc.resolved_label(default_instrument="SNAP") == "SNAP059056"

    def test_resolved_label_prefers_explicit(self):
        """Test explicit label takes precedence."""
        sc = SpectrumConditions(label="CUSTOM", run_number=59056, instrument="SNAP")
        assert sc.resolved_label() == "CUSTOM"

    def test_repr_shows_label(self):
        """Test repr includes label."""
        sc = SpectrumConditions(label="RUN001")
        assert "RUN001" in repr(sc)

    def test_repr_shows_run_number(self):
        """Test repr shows run number when no label."""
        sc = SpectrumConditions(run_number=59056)
        assert "59056" in repr(sc)


# ---------------------------------------------------------------------------
# ExperimentDescription
# ---------------------------------------------------------------------------


class TestExperimentDescription:
    """Tests for ExperimentDescription."""

    def _make_experiment(self) -> ExperimentDescription:
        """Helper: build an experiment with two phases and conditions."""
        w = PhaseDescription(name="tungsten", role="calibrant")
        ice = PhaseDescription(
            name="ice-VII",
            stability_pressure=(2.1, None),
        )
        return ExperimentDescription(
            phases=[w, ice],
            global_temperature=295,
            global_max_pressure=10.0,
            instrument="SNAP",
            facility="SNS",
            pgs="all",
            spectrum_conditions=[
                SpectrumConditions(run_number=1, label="RUN1", pressure=5.0),
                SpectrumConditions(run_number=2, label="RUN2"),
            ],
        )

    def test_create_empty(self):
        """Test creating an empty experiment."""
        exp = ExperimentDescription()
        assert exp.phases == []
        assert exp.global_temperature is None
        assert exp.global_max_pressure is None

    def test_conditions_for_known_label(self):
        """Test conditions_for returns per-spectrum pressure + global T."""
        exp = self._make_experiment()
        cond = exp.conditions_for("RUN1")
        assert cond.pressure == pytest.approx(5.0)
        assert cond.temperature == pytest.approx(295)

    def test_conditions_for_label_without_pressure(self):
        """Test conditions_for inherits global T, pressure stays None."""
        exp = self._make_experiment()
        cond = exp.conditions_for("RUN2")
        assert cond.pressure is None
        assert cond.temperature == pytest.approx(295)

    def test_conditions_for_unknown_label(self):
        """Test conditions_for falls back to globals for unknown label."""
        exp = self._make_experiment()
        cond = exp.conditions_for("UNKNOWN")
        assert cond.pressure is None
        assert cond.temperature == pytest.approx(295)

    def test_active_phases_at_low_pressure(self):
        """Test that ice VII is excluded below 2.1 GPa."""
        exp = self._make_experiment()
        active = exp.active_phases_at(1.0)
        names = [p.name for p in active]
        assert "tungsten" in names
        assert "ice-VII" not in names

    def test_active_phases_at_high_pressure(self):
        """Test that both phases are present above 2.1 GPa."""
        exp = self._make_experiment()
        active = exp.active_phases_at(5.0)
        assert len(active) == 2

    def test_active_phases_at_none(self):
        """Test that unknown pressure returns all phases."""
        exp = self._make_experiment()
        active = exp.active_phases_at(None)
        assert len(active) == 2

    def test_repr_readable(self):
        """Test repr includes phase names and conditions."""
        exp = self._make_experiment()
        r = repr(exp)
        assert "tungsten" in r
        assert "295" in r
        assert "10.0" in r
        assert "SNAP" in r

    def test_global_instrument_and_facility(self):
        """Test global instrument/facility/pgs are stored."""
        exp = self._make_experiment()
        assert exp.instrument == "SNAP"
        assert exp.facility == "SNS"
        assert exp.pgs == "all"

    def test_conditions_for_uses_resolved_label(self):
        """Test conditions_for matches via resolved_label."""
        exp = ExperimentDescription(
            global_temperature=300,
            instrument="SNAP",
            spectrum_conditions=[
                SpectrumConditions(run_number=59056, pressure=5.0),
            ],
        )
        cond = exp.conditions_for("SNAP059056")
        assert cond.pressure == pytest.approx(5.0)
        assert cond.temperature == pytest.approx(300)
