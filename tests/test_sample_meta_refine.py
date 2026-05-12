"""Phase B4 tests: crystalSpecies.refine() skeleton.

Mantid is required (the species are seeded from CIF via from_cif).
Tests cover:
- Both refine paths (EOS-guided and blind sweep) return the expected dict keys.
- EOS-guided path produces a strain close to the theoretical value.
- Blind sweep path finds a consistent strain.
- Edge cases: no observed d, no valid cell, unsupported crystal system.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("mantid")

from snapwrap.sampleMeta.utils import crystalSpecies
from snapwrap.sampleMeta.eos import EquationOfState

CIF_DIR = Path(__file__).parent / "_inspectrum" / "test_data"
TUNGSTEN_CIF = CIF_DIR / "EntryWithCollCode43421_tungsten.cif"

W_EOS = EquationOfState(
    eos_type="vinet",
    V_0=31.724,
    K_0=295.2,
    K_prime=4.32,
    source="Dewaele et al., PRB 70 094112 (2004)",
)

REQUIRED_RESULT_KEYS = {"strain", "path", "pressure_gpa", "unitCell_updated", "message"}


@pytest.fixture(scope="module")
def w_species_no_eos():
    return crystalSpecies.from_cif(TUNGSTEN_CIF)


@pytest.fixture(scope="module")
def w_species_with_eos():
    return crystalSpecies.from_cif(TUNGSTEN_CIF, role="calibrant", eos=W_EOS)


def _synthetic_obs_d(species, strain):
    """Shift all calculated d-spacings by a known strain factor."""
    import numpy as np

    a = species.unitCell.a
    ds = []
    for h in range(1, 5):
        for k in range(0, h + 1):
            for l in range(0, k + 1):
                hkl2 = h * h + k * k + l * l
                if hkl2 == 0:
                    continue
                ds.append(a / (hkl2 ** 0.5) * strain)
    return np.array(sorted(ds, reverse=True))


def test_refine_returns_required_keys(w_species_no_eos):
    obs = _synthetic_obs_d(w_species_no_eos, strain=0.98)
    result = w_species_no_eos.refine(obs)
    assert REQUIRED_RESULT_KEYS.issubset(result.keys())


def test_blind_sweep_path_label(w_species_no_eos):
    obs = _synthetic_obs_d(w_species_no_eos, strain=0.98)
    result = w_species_no_eos.refine(obs, pressure_gpa=None)
    assert result["path"] == "blind_sweep"
    assert result["unitCell_updated"] is True


def test_blind_sweep_recovers_strain(w_species_no_eos):
    """Blind sweep should recover a synthetic strain of 0.98 to ±1%."""
    true_strain = 0.98
    obs = _synthetic_obs_d(w_species_no_eos, strain=true_strain)
    result = w_species_no_eos.refine(obs)
    assert result["strain"] == pytest.approx(true_strain, abs=0.01)


def test_eos_guided_path_label(w_species_with_eos):
    obs = _synthetic_obs_d(w_species_with_eos, strain=0.98)
    result = w_species_with_eos.refine(obs, pressure_gpa=10.0)
    assert result["path"] == "eos_guided"
    assert result["unitCell_updated"] is True
    assert result["pressure_gpa"] == 10.0


def test_eos_guided_recovers_strain_near_theoretical(w_species_with_eos):
    """EOS-guided path on synthetic 10 GPa data should match EOS prediction."""
    from snapwrap.sampleMeta.eos import predicted_strain

    true_P = 10.0
    true_strain = predicted_strain(W_EOS, true_P)
    obs = _synthetic_obs_d(w_species_with_eos, strain=true_strain)
    result = w_species_with_eos.refine(obs, pressure_gpa=true_P)
    assert result["strain"] == pytest.approx(true_strain, abs=0.005)


def test_refine_no_data_returns_no_data_path(w_species_no_eos):
    result = w_species_no_eos.refine([])
    assert result["path"] == "no_data"
    assert result["unitCell_updated"] is False


def test_refine_unsupported_crystal_system():
    """A non-cubic species should raise NotImplementedError (Phase D TODO)."""
    ice_cif = CIF_DIR / "EntryWithCollCode211741_iceVII.cif"
    if not ice_cif.exists():
        pytest.skip("ice-VII CIF not available")
    sp = crystalSpecies.from_cif(ice_cif)
    # ice-VII is cubic too — make a monoclinic species manually
    sp_mono = crystalSpecies(
        spaceGroup="P 1 21/c 1",
        observedReflections=[],
        name="test_monoclinic",
    )
    # Inject a fake valid unit cell so we get past the early-exit checks.
    from snapwrap.sampleMeta.utils import unitCell
    sp_mono.unitCell = unitCell("monoclinic")
    sp_mono.unitCell.a = 5.0
    sp_mono.unitCell.b = 5.0
    sp_mono.unitCell.c = 5.0
    sp_mono.valid["unitCell"] = True

    import numpy as np
    obs = np.array([2.5, 2.0, 1.5])
    with pytest.raises(NotImplementedError, match="cubic"):
        sp_mono.refine(obs)
