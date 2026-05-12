"""Tests for ``snapwrap.reduction_artefacts.asset_artefact_examples``.

The CIF -> ``crystalSpecies`` mapping is gated on Mantid (which provides
``LoadCIF``); the other example builders are pure-Python placeholders and
run unconditionally.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from snapwrap.reduction_artefacts import (
    EOSObject,
    PixelMaskWorkspaceObject,
    SwissCheeseObject,
    build_example_artefact,
    list_asset_artefact_examples,
)

CIF_FIXTURE = (
    Path(__file__).parent
    / "_inspectrum"
    / "test_data"
    / "EntryWithCollCode43421_tungsten.cif"
)


def test_list_asset_artefact_examples_contains_expected_four_mappings() -> None:
    examples = list_asset_artefact_examples()
    assert len(examples) == 4

    by_slug = {row.slug: row for row in examples}
    assert "cif_to_crystal_species" in by_slug
    assert "nxs_to_pixel_mask_workspace" in by_slug
    assert "swiss_cheese_json_to_object" in by_slug
    assert "eos_file_to_eos_object" in by_slug

    cif_row = by_slug["cif_to_crystal_species"]
    assert "crystalSpecies" in cif_row.artefact.in_memory_object


def test_build_example_artefact_returns_expected_placeholder_object_type() -> None:
    nxs_obj = build_example_artefact(
        "nxs_to_pixel_mask_workspace", "nexus/SNAP_1234.nxs.h5"
    )
    swiss_obj = build_example_artefact(
        "swiss_cheese_json_to_object", "assets/swiss_cheese.json"
    )
    eos_obj = build_example_artefact("eos_file_to_eos_object", "assets/eos.dat")

    assert isinstance(nxs_obj, PixelMaskWorkspaceObject)
    assert isinstance(swiss_obj, SwissCheeseObject)
    assert isinstance(eos_obj, EOSObject)


def test_build_example_artefact_unknown_slug_raises() -> None:
    with pytest.raises(KeyError, match="Unknown asset->artefact example slug"):
        build_example_artefact("unknown", "x")


def test_build_cif_artefact_yields_real_crystal_species() -> None:
    """The cif slug builds a real ``crystalSpecies`` (Mantid required)."""
    pytest.importorskip("mantid")
    from snapwrap.sampleMeta.utils import crystalSpecies

    obj = build_example_artefact("cif_to_crystal_species", CIF_FIXTURE)
    assert isinstance(obj, crystalSpecies)
    assert obj.cifPath == str(CIF_FIXTURE)
    assert obj.role == "sample"
    assert obj.hasCrystalStructure
    assert obj.valid["unitCell"]
