"""Phase B1 tests: snapwrap.sampleMeta.eos re-export.

No Mantid required. Verifies:
- All five public symbols are importable through the sampleMeta.eos facade.
- The re-exported objects are identical to the underlying _inspectrum originals
  (i.e. we are re-exporting, not copying).
- Round-trip sanity: predicted_strain at 0 GPa is 1.0; pressure_at V/V0=1 is 0.
"""

from __future__ import annotations

import pytest

from snapwrap.sampleMeta import eos as sampleMeta_eos
from snapwrap._inspectrum import EquationOfState as _InspEquationOfState
from snapwrap._inspectrum.eos import (
    pressure_at as _insp_pressure_at,
    predicted_strain as _insp_predicted_strain,
    volume_ratio as _insp_volume_ratio,
)
from snapwrap._inspectrum.matching import sweep_strain as _insp_sweep_strain


def test_all_public_symbols_importable():
    for name in sampleMeta_eos.__all__:
        assert hasattr(sampleMeta_eos, name), f"Missing symbol: {name}"


def test_reexports_are_same_objects_as_inspectrum():
    """Re-exports must be the very same objects, not copies."""
    assert sampleMeta_eos.EquationOfState is _InspEquationOfState
    assert sampleMeta_eos.pressure_at is _insp_pressure_at
    assert sampleMeta_eos.predicted_strain is _insp_predicted_strain
    assert sampleMeta_eos.volume_ratio is _insp_volume_ratio
    assert sampleMeta_eos.sweep_strain is _insp_sweep_strain


@pytest.fixture
def tungsten_eos():
    return sampleMeta_eos.EquationOfState(
        eos_type="vinet",
        V_0=31.724,
        K_0=295.2,
        K_prime=4.32,
        source="Dewaele et al., PRB 70 094112 (2004)",
    )


def test_predicted_strain_zero_pressure_is_one(tungsten_eos):
    s = sampleMeta_eos.predicted_strain(tungsten_eos, pressure=0.0)
    assert s == pytest.approx(1.0, abs=1e-10)


def test_volume_ratio_zero_pressure_is_one(tungsten_eos):
    vr = sampleMeta_eos.volume_ratio(tungsten_eos, pressure=0.0)
    assert vr == pytest.approx(1.0, abs=1e-10)


def test_pressure_at_unit_volume_ratio_is_zero(tungsten_eos):
    p = sampleMeta_eos.pressure_at(tungsten_eos, v_ratio=1.0)
    assert p == pytest.approx(0.0, abs=1e-6)


def test_predicted_strain_increases_with_pressure(tungsten_eos):
    """Higher pressure -> smaller lattice -> strain < 1."""
    s10 = sampleMeta_eos.predicted_strain(tungsten_eos, pressure=10.0)
    s50 = sampleMeta_eos.predicted_strain(tungsten_eos, pressure=50.0)
    assert s10 < 1.0
    assert s50 < s10


def test_inspectrum_ground_truth_W_at_50GPa(tungsten_eos):
    """Spot-check: W Vinet EOS (Dewaele et al.) at 50 GPa.

    The inspectrum test suite (test_eos.py) asserts 0.85 < V/V₀ < 0.90
    at 50 GPa; the cube-root of that range gives strain in [0.947, 0.965].
    Our computed value is ~0.9580; tolerance ±0.010 is deliberately loose
    to accommodate future numpy/scipy variation.
    """
    s = sampleMeta_eos.predicted_strain(tungsten_eos, pressure=50.0)
    assert 0.947 < s < 0.965
