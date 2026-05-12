"""Phase A5 tests: ``crystalSpecies.from_cif`` round-trips and field hardening.

These tests are gated on Mantid (which provides ``LoadCIF``).  They use the
two reference CIFs vendored under ``tests/_inspectrum/test_data/`` so we
don't need a separate fixture corpus.

See ``docs/crystal_species_refinement_plan.md`` Phase A.
"""

from __future__ import annotations

from pathlib import Path

import pytest

mantid = pytest.importorskip("mantid")  # noqa: F841 - import guard

from snapwrap.sampleMeta.utils import crystalSpecies  # noqa: E402

CIF_DIR = Path(__file__).parent / "_inspectrum" / "test_data"
TUNGSTEN_CIF = CIF_DIR / "EntryWithCollCode43421_tungsten.cif"
ICE_VII_CIF = CIF_DIR / "EntryWithCollCode211741_iceVII.cif"


@pytest.fixture(scope="module")
def tungsten_species():
    return crystalSpecies.from_cif(TUNGSTEN_CIF)


@pytest.fixture(scope="module")
def ice_vii_species():
    return crystalSpecies.from_cif(ICE_VII_CIF)


def test_tungsten_basic_fields(tungsten_species):
    sp = tungsten_species
    assert sp.cifPath is not None
    assert Path(sp.cifPath) == TUNGSTEN_CIF
    assert sp.role == "sample"
    assert sp.eos is None
    assert sp.spaceGroup  # non-empty
    assert sp.crystalSystem == "cubic"
    assert sp.hasCrystalStructure
    assert sp.valid["unitCell"]
    assert sp.unitCell is not None
    # Reference: a = 3.16475 Å (W, Im-3m); allow loose tolerance for CIF parse.
    assert sp.unitCell.a == pytest.approx(3.16475, abs=0.05)
    assert sp.unitCell.b == pytest.approx(sp.unitCell.a)
    assert sp.unitCell.c == pytest.approx(sp.unitCell.a)


def test_ice_vii_basic_fields(ice_vii_species):
    sp = ice_vii_species
    assert sp.cifPath is not None
    assert sp.crystalSystem == "cubic"
    assert sp.hasCrystalStructure
    assert sp.valid["unitCell"]
    # Reference: a = 3.31812 Å (D2O ice-VII, Pn-3m).
    assert sp.unitCell.a == pytest.approx(3.31812, abs=0.05)


def test_role_validation():
    with pytest.raises(ValueError, match="Invalid role"):
        crystalSpecies.from_cif(TUNGSTEN_CIF, role="bogus")


def test_role_calibrant_accepted():
    sp = crystalSpecies.from_cif(TUNGSTEN_CIF, role="calibrant")
    assert sp.role == "calibrant"


def test_eos_attached_passthrough():
    """An EquationOfState supplied to from_cif is stored on the species
    and survives a to_dict/from_dict round-trip."""
    eos_module = pytest.importorskip("snapwrap._inspectrum")
    EquationOfState = eos_module.EquationOfState

    eos = EquationOfState(
        eos_type="vinet",
        V_0=31.724,
        K_0=295.2,
        K_prime=4.32,
        source="Dewaele et al., PRB 70 094112 (2004)",
    )
    sp = crystalSpecies.from_cif(TUNGSTEN_CIF, role="calibrant", eos=eos)
    assert sp.eos is eos

    d = sp.to_dict()
    assert d["_schema_version"] == crystalSpecies.SCHEMA_VERSION
    assert d["role"] == "calibrant"
    assert d["cifPath"] == str(TUNGSTEN_CIF)
    assert d["eos"]["eos_type"] == "vinet"
    assert d["eos"]["V_0"] == pytest.approx(31.724)

    sp2 = crystalSpecies.from_dict(d)
    assert sp2.role == "calibrant"
    assert sp2.cifPath == str(TUNGSTEN_CIF)
    assert sp2.eos is not None
    assert sp2.eos.eos_type == "vinet"
    assert sp2.eos.K_0 == pytest.approx(295.2)
    assert sp2.unitCell is not None
    assert sp2.unitCell.a == pytest.approx(sp.unitCell.a)


def test_round_trip_without_eos(tungsten_species):
    d = tungsten_species.to_dict()
    assert d["eos"] is None
    sp2 = crystalSpecies.from_dict(d)
    assert sp2.role == "sample"
    assert sp2.eos is None
    assert sp2.cifPath == tungsten_species.cifPath
    assert sp2.unitCell.a == pytest.approx(tungsten_species.unitCell.a)


def test_legacy_dict_without_new_fields_still_loads():
    """A dict missing the Phase A fields (legacy on-disk JSON) must still
    rehydrate with sensible defaults."""
    sp = crystalSpecies.from_cif(TUNGSTEN_CIF)
    d = sp.to_dict()
    # Strip Phase A fields to simulate a v0 payload.
    for k in ("_schema_version", "cifPath", "role", "eos"):
        d.pop(k, None)
    sp2 = crystalSpecies.from_dict(d)
    assert sp2.role == "sample"
    assert sp2.cifPath is None
    assert sp2.eos is None
