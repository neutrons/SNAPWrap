"""Artefact builders for crystallography assets.

Provides:

- :func:`load_eos_description` — load an ``EquationOfState`` from a
  ``.eos.json`` file on disk.
- :func:`load_phase_description` — load an inspectrum-style multi-phase
  description JSON file, returning an ``ExperimentDescription``.
- :func:`build_crystal_species` — given one CIF asset record (and an optional
  EOS asset record) return a :class:`~snapwrap.reduction_artefacts.assets.LoadedAsset`
  wrapping a :class:`~snapwrap.sampleMeta.utils.crystalSpecies`.

Mantid is **not** imported at module level.  ``build_crystal_species`` defers
the Mantid import until call time so this module stays importable in
environments without Mantid.

EOS description file format
---------------------------
A plain JSON file with fields matching the
``snapwrap._inspectrum.models.EquationOfState`` dataclass::

    {
        "eos_type": "vinet",
        "V_0": 31.724,
        "K_0": 295.2,
        "K_prime": 4.32,
        "source": "Dewaele et al., PRB 70 094112 (2004)"
    }

Optional fields (``order``, ``extra``) default to the dataclass defaults when
absent.  Unknown keys are silently ignored so that extended files (with
uncertainty fields, for example) round-trip safely.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .assets import AssetRecord, LoadedAsset

_EOS_KNOWN_FIELDS = frozenset(
    {"eos_type", "order", "V_0", "K_0", "K_prime", "source", "extra"}
)


def load_eos_description(path: str | Path) -> Any:
    """Load an :class:`~snapwrap._inspectrum.models.EquationOfState` from a
    ``.eos.json`` file.

    Args:
        path: Path to the EOS description JSON file.

    Returns:
        An ``EquationOfState`` dataclass instance populated from the file.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        ValueError: If required fields (``eos_type``, ``V_0``, ``K_0``,
            ``K_prime``) are missing or ``eos_type`` is not one of the
            supported values.
    """
    from snapwrap.sampleMeta.eos import EquationOfState

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"EOS description file not found: {p}")

    with p.open("r", encoding="utf-8") as fh:
        raw: dict[str, Any] = json.load(fh)

    if not isinstance(raw, dict):
        raise ValueError(f"EOS description must be a JSON object, got {type(raw).__name__}")

    required = ("eos_type", "V_0", "K_0", "K_prime")
    missing = [k for k in required if k not in raw]
    if missing:
        raise ValueError(
            f"EOS description file {p} is missing required fields: {missing}"
        )

    valid_types = ("murnaghan", "birch-murnaghan", "vinet")
    if raw["eos_type"] not in valid_types:
        raise ValueError(
            f"eos_type {raw['eos_type']!r} is not supported; "
            f"choose one of {valid_types}"
        )

    kwargs: dict[str, Any] = {k: raw[k] for k in _EOS_KNOWN_FIELDS if k in raw}
    return EquationOfState(**kwargs)


def build_crystal_species(
    cif_asset: AssetRecord,
    eos_asset: AssetRecord | None = None,
    role: str = "sample",
) -> "LoadedAsset":
    """Build a ``crystalSpecies`` artefact from a CIF asset (and optional EOS).

    This is the canonical Phase C factory.  It:

    1. Optionally loads the EOS description from *eos_asset.path*.
    2. Calls :meth:`~snapwrap.sampleMeta.utils.crystalSpecies.from_cif`
       with the CIF path, *role*, and EOS object.
    3. Wraps the result in a
       :class:`~snapwrap.reduction_artefacts.assets.LoadedAsset` whose
       ``record`` is *cif_asset*.

    Mantid is required (deferred import).  The EOS description loader does
    **not** require Mantid.

    Args:
        cif_asset: The registered CIF asset record.  ``cif_asset.path`` must
            point to an accessible ``.cif`` file.
        eos_asset: Optional EOS asset record.  When supplied,
            ``eos_asset.path`` must point to a ``.eos.json`` file loadable by
            :func:`load_eos_description`.
        role: ``"sample"`` (default) or ``"calibrant"``.

    Returns:
        :class:`~snapwrap.reduction_artefacts.assets.LoadedAsset` with
        ``record = cif_asset`` and ``payload`` being the constructed
        :class:`~snapwrap.sampleMeta.utils.crystalSpecies`.
    """
    from snapwrap.sampleMeta.utils import crystalSpecies as CrystalSpecies

    eos_obj = None
    if eos_asset is not None:
        eos_obj = load_eos_description(eos_asset.path)

    species = CrystalSpecies.from_cif(cif_asset.path, role=role, eos=eos_obj)
    return LoadedAsset(record=cif_asset, payload=species)


def load_phase_description(path: "str | Path") -> Any:
    """Load an inspectrum-style multi-phase description JSON file.

    Wraps :func:`snapwrap._inspectrum.loaders.load_phase_descriptions`.
    The returned object is an ``ExperimentDescription`` dataclass whose
    ``phases`` list contains one entry per phase declared in the file.

    No Mantid import is required.  CIFs referenced inside the JSON are loaded
    by inspectrum's own ``load_cif`` (cryspy-backed).

    Args:
        path: Path to the phases JSON file (inspectrum ``snap_phases.json``
              schema).

    Returns:
        An ``ExperimentDescription`` instance.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        ValueError: If the file fails inspectrum validation.
    """
    from snapwrap._inspectrum.loaders import load_phase_descriptions

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Phase description file not found: {p}")
    return load_phase_descriptions(p)
