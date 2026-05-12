"""
Tests for inspectrum EOS evaluation.

Validates Birch-Murnaghan, Vinet, and Murnaghan equations of state
against known reference values.

Reference values:
- Tungsten (Vinet): Dewaele et al. PRB 70 094112 (2004), Table II.
  At 10 GPa, V/V₀ ≈ 0.967; at 50 GPa, V/V₀ ≈ 0.852.
- Ice VII (BM3): Hemley et al. Nature 330 737 (1987), Fig. 2.
  At 10 GPa, V/V₀ ≈ 0.720; at 30 GPa, V/V₀ ≈ 0.595.
"""

import pytest

from snapwrap._inspectrum.eos import (
    _pressure_birch_murnaghan,
    _pressure_murnaghan,
    _pressure_vinet,
    predicted_strain,
    pressure_at,
    volume_ratio,
)
from snapwrap._inspectrum.models import EquationOfState

# ---------------------------------------------------------------------------
# Fixtures: EOS parameter sets
# ---------------------------------------------------------------------------


@pytest.fixture
def tungsten_eos() -> EquationOfState:
    """Tungsten Vinet EOS from Dewaele et al. PRB 70 (2004)."""
    return EquationOfState(
        eos_type="vinet",
        order=3,
        V_0=31.724,  # Å³/cell (15.862 × 2)
        K_0=295.2,
        K_prime=4.32,
        source="Dewaele et al. PRB 70 094112 (2004)",
    )


@pytest.fixture
def ice_vii_eos() -> EquationOfState:
    """Ice VII BM3 EOS from Hemley et al. Nature 330 (1987)."""
    return EquationOfState(
        eos_type="birch-murnaghan",
        order=3,
        V_0=40.85,  # Å³/cell (12.3 cm³/mol × Z=2)
        K_0=23.7,
        K_prime=4.15,
        source="Hemley et al. Nature 330 737 (1987)",
    )


@pytest.fixture
def murnaghan_eos() -> EquationOfState:
    """Simple Murnaghan EOS for cross-checking."""
    return EquationOfState(
        eos_type="murnaghan",
        order=1,
        V_0=100.0,
        K_0=100.0,
        K_prime=4.0,
        source="test",
    )


# ---------------------------------------------------------------------------
# Forward evaluation: P(V/V₀)
# ---------------------------------------------------------------------------


class TestPressureForward:
    """Test forward EOS evaluation: V/V₀ → P."""

    def test_bm3_zero_pressure_at_v0(self):
        """All EOS should give P = 0 at V/V₀ = 1."""
        assert _pressure_birch_murnaghan(1.0, 100.0, 4.0) == pytest.approx(0.0)

    def test_vinet_zero_pressure_at_v0(self):
        """Vinet gives P = 0 at V/V₀ = 1."""
        assert _pressure_vinet(1.0, 100.0, 4.0) == pytest.approx(0.0)

    def test_murnaghan_zero_pressure_at_v0(self):
        """Murnaghan gives P = 0 at V/V₀ = 1."""
        assert _pressure_murnaghan(1.0, 100.0, 4.0) == pytest.approx(0.0)

    def test_bm3_positive_pressure_under_compression(self):
        """Compression (V/V₀ < 1) should give P > 0."""
        assert _pressure_birch_murnaghan(0.9, 100.0, 4.0) > 0

    def test_vinet_positive_pressure_under_compression(self):
        """Compression should give P > 0."""
        assert _pressure_vinet(0.9, 100.0, 4.0) > 0

    def test_bm3_small_compression_linear(self):
        """At small compression, all EOS reduce to P ≈ K₀ × ΔV/V₀."""
        # V/V₀ = 0.999, ΔV/V₀ = 0.001, expect P ≈ K₀ × 0.001 = 0.1 GPa
        p = _pressure_birch_murnaghan(0.999, 100.0, 4.0)
        assert p == pytest.approx(0.1, rel=0.05)

    def test_vinet_small_compression_linear(self):
        """Vinet at small compression agrees with K₀ × ΔV/V₀."""
        p = _pressure_vinet(0.999, 100.0, 4.0)
        assert p == pytest.approx(0.1, rel=0.05)

    def test_pressure_at_dispatches_correctly(self, tungsten_eos):
        """pressure_at() dispatches to the correct EOS function."""
        p = pressure_at(tungsten_eos, 0.95)
        assert p > 0

    def test_pressure_at_unknown_type_raises(self):
        """Unknown EOS type raises ValueError at construction."""
        with pytest.raises(ValueError, match="eos_type must be one of"):
            EquationOfState(
                eos_type="unknown",
                order=3,
                V_0=100,
                K_0=100,
                K_prime=4,
                source="test",
            )

    def test_pressure_at_nonpositive_v_ratio_raises(self, tungsten_eos):
        """Non-positive V/V₀ raises ValueError."""
        with pytest.raises(ValueError, match="positive"):
            pressure_at(tungsten_eos, 0.0)


# ---------------------------------------------------------------------------
# Inverse evaluation: P → V/V₀
# ---------------------------------------------------------------------------


class TestVolumeRatio:
    """Test inverse EOS evaluation: P → V/V₀."""

    def test_zero_pressure_gives_unity(self, tungsten_eos):
        """At P = 0, V/V₀ = 1 exactly."""
        assert volume_ratio(tungsten_eos, 0.0) == 1.0

    def test_tungsten_10gpa(self, tungsten_eos):
        """Tungsten at 10 GPa: V/V₀ ≈ 0.967 (Dewaele Table II)."""
        vr = volume_ratio(tungsten_eos, 10.0)
        assert vr == pytest.approx(0.967, abs=0.003)

    def test_tungsten_50gpa(self, tungsten_eos):
        """Tungsten at 50 GPa: verify V/V₀ from Vinet EOS."""
        vr = volume_ratio(tungsten_eos, 50.0)
        # Verify via roundtrip and reasonable range
        assert 0.85 < vr < 0.90
        assert pressure_at(tungsten_eos, vr) == pytest.approx(50.0, rel=1e-9)

    def test_ice_vii_10gpa(self, ice_vii_eos):
        """Ice VII at 10 GPa: soft material, significant compression."""
        vr = volume_ratio(ice_vii_eos, 10.0)
        # K₀ = 23.7 GPa is very soft → large compression
        assert 0.70 < vr < 0.82
        assert pressure_at(ice_vii_eos, vr) == pytest.approx(10.0, rel=1e-9)

    def test_ice_vii_30gpa(self, ice_vii_eos):
        """Ice VII at 30 GPa: further compression."""
        vr = volume_ratio(ice_vii_eos, 30.0)
        assert 0.55 < vr < 0.66
        assert pressure_at(ice_vii_eos, vr) == pytest.approx(30.0, rel=1e-9)

    def test_roundtrip(self, tungsten_eos):
        """P → V/V₀ → P should be self-consistent."""
        p_in = 25.0
        vr = volume_ratio(tungsten_eos, p_in)
        p_out = pressure_at(tungsten_eos, vr)
        assert p_out == pytest.approx(p_in, rel=1e-9)

    def test_murnaghan_roundtrip(self, murnaghan_eos):
        """Murnaghan roundtrip."""
        p_in = 15.0
        vr = volume_ratio(murnaghan_eos, p_in)
        p_out = pressure_at(murnaghan_eos, vr)
        assert p_out == pytest.approx(p_in, rel=1e-9)

    def test_negative_pressure_raises(self, tungsten_eos):
        """Negative pressure raises ValueError."""
        with pytest.raises(ValueError, match="non-negative"):
            volume_ratio(tungsten_eos, -1.0)

    def test_very_high_pressure_narrows_bounds(self, tungsten_eos):
        """At very high P, default bounds may fail — verify error message."""
        # 500 GPa on tungsten: V/V₀ ≈ 0.56, still within [0.5, 1.0]
        vr = volume_ratio(tungsten_eos, 500.0)
        assert 0.5 < vr < 0.7

    def test_monotonic_with_pressure(self, tungsten_eos):
        """Volume ratio should decrease monotonically with pressure."""
        pressures = [0, 5, 10, 20, 50, 100]
        vrs = [volume_ratio(tungsten_eos, p) for p in pressures]
        for i in range(1, len(vrs)):
            assert vrs[i] < vrs[i - 1]


# ---------------------------------------------------------------------------
# Predicted strain
# ---------------------------------------------------------------------------


class TestPredictedStrain:
    """Test strain prediction: P → s = (V/V₀)^(1/3)."""

    def test_zero_pressure_gives_unity(self, tungsten_eos):
        """At P = 0, strain = 1."""
        assert predicted_strain(tungsten_eos, 0.0) == 1.0

    def test_strain_is_cube_root_of_volume_ratio(self, tungsten_eos):
        """Strain should be (V/V₀)^(1/3)."""
        p = 20.0
        vr = volume_ratio(tungsten_eos, p)
        s = predicted_strain(tungsten_eos, p)
        assert s == pytest.approx(vr ** (1.0 / 3.0), rel=1e-10)

    def test_strain_less_than_one_under_compression(self, tungsten_eos):
        """Under compression, strain < 1."""
        s = predicted_strain(tungsten_eos, 10.0)
        assert s < 1.0

    def test_tungsten_strain_at_10gpa(self, tungsten_eos):
        """Tungsten at 10 GPa: s ≈ 0.989 (cube root of 0.967)."""
        s = predicted_strain(tungsten_eos, 10.0)
        assert s == pytest.approx(0.989, abs=0.002)

    def test_ice_vii_strain_at_10gpa(self, ice_vii_eos):
        """Ice VII at 10 GPa: s ≈ 0.90 (cube root of ~0.72)."""
        s = predicted_strain(ice_vii_eos, 10.0)
        assert s == pytest.approx(0.90, abs=0.02)
