"""Concrete examples clarifying asset vs artefact semantics.

Working definition used here:

- asset: persisted input (typically on disk)
- artefact: in-memory object derived from one or more assets

This module intentionally avoids hard *import-time* dependencies on Mantid
and SNAPRed. Builders that need them (e.g. the CIF -> ``crystalSpecies``
mapping) defer those imports until they are actually invoked, so the example
catalogue can be inspected and tested in environments without Mantid.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AssetDefinition:
    """A persisted source input from which an artefact can be derived."""

    name: str
    file_format: str
    typical_extensions: tuple[str, ...]
    persisted: bool = True


@dataclass(frozen=True)
class ArtefactDefinition:
    """An in-memory data object used by reduction/workflow logic."""

    name: str
    in_memory_object: str
    derived_from_asset: str


@dataclass(frozen=True)
class AssetArtefactExample:
    """Describes one concrete asset -> artefact mapping."""

    slug: str
    asset: AssetDefinition
    artefact: ArtefactDefinition
    notes: str


@dataclass(frozen=True)
class PixelMaskWorkspaceObject:
    """Placeholder for a Mantid-style pixel mask workspace."""

    source_nxs: Path
    workspace_name: str = "MaskWorkspace"


@dataclass(frozen=True)
class SwissCheeseObject:
    """Placeholder for SNAPRed swiss-cheese reduction object."""

    source_json: Path
    implementation: str = "snapred.swiss_cheese"


@dataclass(frozen=True)
class EOSObject:
    """Placeholder EOS object; exact format/schema intentionally TBD."""

    source_file: Path
    eos_model: str = "EOS"


def build_crystal_species_from_cif(path):
    """Build a real ``crystalSpecies`` artefact from a CIF asset.

    Mantid is required. The import is deferred to call-time so this module
    stays importable without Mantid installed.
    """
    from snapwrap.sampleMeta.utils import crystalSpecies

    return crystalSpecies.from_cif(Path(path))


def build_pixel_mask_workspace_from_nxs(path):
    return PixelMaskWorkspaceObject(source_nxs=Path(path))


def build_swiss_cheese_from_json(path):
    return SwissCheeseObject(source_json=Path(path))


def build_eos_object(path):
    return EOSObject(source_file=Path(path))


def list_asset_artefact_examples():
    """Return explicit, agreed examples of asset -> artefact mappings."""
    return [
        AssetArtefactExample(
            slug="cif_to_crystal_species",
            asset=AssetDefinition(
                name="cif file",
                file_format="CIF",
                typical_extensions=(".cif",),
            ),
            artefact=ArtefactDefinition(
                name="crystalSpecies object",
                in_memory_object="snapwrap.sampleMeta.utils.crystalSpecies",
                derived_from_asset="cif file",
            ),
            notes=(
                "Built via crystalSpecies.from_cif (Mantid-backed). "
                "Requires Mantid at build-time; not at example-listing time."
            ),
        ),
        AssetArtefactExample(
            slug="nxs_to_pixel_mask_workspace",
            asset=AssetDefinition(
                name="nxs file",
                file_format="NeXus",
                typical_extensions=(".nxs", ".nxs.h5"),
            ),
            artefact=ArtefactDefinition(
                name="Mantid MaskWorkspace",
                in_memory_object="PixelMaskWorkspaceObject",
                derived_from_asset="nxs file",
            ),
            notes="Typically represented in Mantid as a mask workspace.",
        ),
        AssetArtefactExample(
            slug="swiss_cheese_json_to_object",
            asset=AssetDefinition(
                name="swiss cheese json file",
                file_format="JSON",
                typical_extensions=(".json",),
            ),
            artefact=ArtefactDefinition(
                name="snapred swiss cheese object",
                in_memory_object="SwissCheeseObject",
                derived_from_asset="swiss cheese json file",
            ),
            notes="Domain-specific object consumed by SNAPRed workflows.",
        ),
        AssetArtefactExample(
            slug="eos_file_to_eos_object",
            asset=AssetDefinition(
                name="eos file",
                file_format="TBD",
                typical_extensions=(),
            ),
            artefact=ArtefactDefinition(
                name="EOS object",
                in_memory_object="EOSObject",
                derived_from_asset="eos file",
            ),
            notes="File format and schema are intentionally TBD.",
        ),
    ]


def build_example_artefact(example_slug, source_path):
    """Build a concrete artefact for one of the known example slugs."""
    builders = {
        "cif_to_crystal_species": build_crystal_species_from_cif,
        "nxs_to_pixel_mask_workspace": build_pixel_mask_workspace_from_nxs,
        "swiss_cheese_json_to_object": build_swiss_cheese_from_json,
        "eos_file_to_eos_object": build_eos_object,
    }
    try:
        builder = builders[example_slug]
    except KeyError as exc:
        raise KeyError(
            f"Unknown asset->artefact example slug: {example_slug!r}"
        ) from exc
    return builder(source_path)
