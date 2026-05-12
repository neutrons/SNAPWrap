"""
Data loaders for snapwrap._inspectrum.

Provides functions to read diffraction data, instrument parameters,
and crystal structure information from common file formats:

- load_gsa: GSAS FXYE (.gsa) format — TOF x-axis
- load_mantid_csv: Mantid-exported CSV — d-spacing x-axis
- load_instprm: GSAS-II instrument parameter (.instprm) files
- load_cif: CIF crystal structure files via pycifstar
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
from pycifstar import to_data as cif_to_data

from snapwrap._inspectrum.models import (
    CrystalPhase,
    DiffractionSpectrum,
    EquationOfState,
    ExperimentDescription,
    Instrument,
    PhaseDescription,
    SampleConditions,
    SpectrumConditions,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_cif_number(value_str: str) -> float:
    """Parse a CIF numeric value, stripping uncertainty in parentheses.

    Examples:
        '3.16475(20)' → 3.16475
        '90.'         → 90.0
        '0'           → 0.0
        '.'           → NaN (CIF missing-value marker)
        '0.202(3)'    → 0.202

    Args:
        value_str: String from a CIF field.

    Returns:
        Parsed float value.

    Raises:
        ValueError: If the string cannot be parsed as a number.
    """
    s = value_str.strip()
    if s in (".", "?"):
        return float("nan")
    # Strip trailing uncertainty, e.g. "3.16475(20)" → "3.16475"
    s = re.sub(r"\(\d+\)$", "", s)
    return float(s)


# ---------------------------------------------------------------------------
# GSA loader (GSAS FXYE format, TOF x-axis)
# ---------------------------------------------------------------------------


def load_gsa(filepath: str | Path) -> list[DiffractionSpectrum]:
    """Load diffraction spectra from a GSAS FXYE (.gsa) file.

    Reads one or more banks of TOF vs intensity data.  Each BANK
    section becomes a separate DiffractionSpectrum with
    ``x_unit="TOF"``.

    The file format is::

        {JSON metadata line(s)}
        # comment lines with flight path, 2-theta, DIFC
        BANK <n> <npts> <npts> SLOG <tof_min> <tof_max> <log_step> 0 FXYE
        <tof>  <intensity>  <uncertainty>
        ...

    Args:
        filepath: Path to the .gsa file.

    Returns:
        List of DiffractionSpectrum objects (one per bank).

    Raises:
        FileNotFoundError: If file does not exist.
        ValueError: If the file cannot be parsed.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"GSA file not found: {path}")

    spectra: list[DiffractionSpectrum] = []
    metadata: dict[str, str] = {}
    current_bank: int | None = None
    tof_vals: list[float] = []
    y_vals: list[float] = []
    e_vals: list[float] = []

    with open(path) as f:
        for line in f:
            stripped = line.strip()

            # Skip empty lines
            if not stripped:
                continue

            # JSON metadata (first lines starting with '{')
            if stripped.startswith("{"):
                # Collect as raw metadata
                metadata["header_json"] = metadata.get("header_json", "") + stripped
                continue

            # Comment lines
            if stripped.startswith("#"):
                metadata["comments"] = metadata.get("comments", "") + stripped + "\n"
                continue

            # BANK header line
            if stripped.startswith("BANK"):
                # If we already have data from a previous bank, save it
                if current_bank is not None and tof_vals:
                    spectra.append(
                        DiffractionSpectrum(
                            x=np.array(tof_vals, dtype=np.float64),
                            y=np.array(y_vals, dtype=np.float64),
                            e=np.array(e_vals, dtype=np.float64),
                            x_unit="TOF",
                            y_unit="Counts",
                            label=path.stem,
                            bank=current_bank - 1,  # 0-based
                            metadata=dict(metadata),
                        )
                    )
                    tof_vals, y_vals, e_vals = [], [], []

                # Parse BANK line: BANK <n> <npts> <npts> SLOG ...
                parts = stripped.split()
                current_bank = int(parts[1])
                continue

            # Data lines: 3 whitespace-separated floats
            if current_bank is not None:
                parts = stripped.split()
                if len(parts) >= 3:
                    tof_vals.append(float(parts[0]))
                    y_vals.append(float(parts[1]))
                    e_vals.append(float(parts[2]))

    # Save the last bank
    if current_bank is not None and tof_vals:
        spectra.append(
            DiffractionSpectrum(
                x=np.array(tof_vals, dtype=np.float64),
                y=np.array(y_vals, dtype=np.float64),
                e=np.array(e_vals, dtype=np.float64),
                x_unit="TOF",
                y_unit="Counts",
                label=path.stem,
                bank=current_bank - 1,  # 0-based
                metadata=dict(metadata),
            )
        )

    if not spectra:
        raise ValueError(f"No BANK data found in {path}")

    return spectra


# ---------------------------------------------------------------------------
# Mantid CSV loader (d-spacing x-axis)
# ---------------------------------------------------------------------------


def load_mantid_csv(filepath: str | Path) -> list[DiffractionSpectrum]:
    """Load diffraction spectra from a Mantid-exported CSV file.

    Reads d-spacing vs intensity data.  The expected format is::

        XYDATA
        # File generated by Mantid, Instrument SNAPLite
        # The X-axis unit is: d-Spacing, The Y-axis unit is: ...
        # Data for spectra :0
        # Spectrum 1
        # d-Spacing              Y                 E
        0.79057       84.94315788        2.09126162
        ...

    Each "Spectrum" section becomes a separate DiffractionSpectrum.
    In practice, the CSV files in our test set contain a single spectrum.

    Args:
        filepath: Path to the .csv file.

    Returns:
        List of DiffractionSpectrum objects (one per spectrum block).

    Raises:
        FileNotFoundError: If file does not exist.
        ValueError: If the file cannot be parsed.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    spectra: list[DiffractionSpectrum] = []
    metadata: dict[str, str] = {}
    x_unit = "d-Spacing"
    y_unit = "Counts"
    current_spectrum: int | None = None
    d_vals: list[float] = []
    y_vals: list[float] = []
    e_vals: list[float] = []

    with open(path) as f:
        for line in f:
            stripped = line.strip()

            if not stripped:
                continue

            # Header marker
            if stripped == "XYDATA":
                continue

            # Comment / header lines
            if stripped.startswith("#"):
                # Extract units if present
                if "X-axis unit" in stripped:
                    match = re.search(r"X-axis unit is:\s*([^,]+)", stripped)
                    if match:
                        x_unit = match.group(1).strip()
                if "Y-axis unit" in stripped:
                    match = re.search(r"Y-axis unit is:\s*(.+)", stripped)
                    if match:
                        y_unit = match.group(1).strip()

                # Detect spectrum header
                spec_match = re.search(r"Spectrum\s+(\d+)", stripped)
                if spec_match:
                    # Save previous spectrum if exists
                    if current_spectrum is not None and d_vals:
                        spectra.append(
                            DiffractionSpectrum(
                                x=np.array(d_vals, dtype=np.float64),
                                y=np.array(y_vals, dtype=np.float64),
                                e=np.array(e_vals, dtype=np.float64),
                                x_unit=x_unit,
                                y_unit=y_unit,
                                label=path.stem,
                                bank=current_spectrum - 1,  # 0-based
                                metadata=dict(metadata),
                            )
                        )
                        d_vals, y_vals, e_vals = [], [], []
                    current_spectrum = int(spec_match.group(1))

                metadata["comments"] = metadata.get("comments", "") + stripped + "\n"
                continue

            # Data lines
            parts = stripped.split()
            if len(parts) >= 3:
                d_vals.append(float(parts[0]))
                y_vals.append(float(parts[1]))
                e_vals.append(float(parts[2]))

    # Save last spectrum
    if d_vals:
        bank = (current_spectrum - 1) if current_spectrum is not None else 0
        spectra.append(
            DiffractionSpectrum(
                x=np.array(d_vals, dtype=np.float64),
                y=np.array(y_vals, dtype=np.float64),
                e=np.array(e_vals, dtype=np.float64),
                x_unit=x_unit,
                y_unit=y_unit,
                label=path.stem,
                bank=bank,
                metadata=dict(metadata),
            )
        )

    if not spectra:
        raise ValueError(f"No spectrum data found in {path}")

    return spectra


# ---------------------------------------------------------------------------
# Instrument parameter loader (.instprm)
# ---------------------------------------------------------------------------

# Map from instprm key names to Instrument dataclass field names
_INSTPRM_KEY_MAP: dict[str, str] = {
    "Type": "inst_type",
    "2-theta": "two_theta",
    "fltPath": "flt_path",
    "difA": "difA",
    "difB": "difB",
    "difC": "difC",
    "Zero": "zero",
    "alpha": "alpha",
    "beta-0": "beta_0",
    "beta-1": "beta_1",
    "beta-q": "beta_q",
    "sig-0": "sig_0",
    "sig-1": "sig_1",
    "sig-2": "sig_2",
    "sig-q": "sig_q",
    "X": "X",
    "Y": "Y",
    "Z": "Z",
    "Azimuth": "azimuth",
}


def load_instprm(filepath: str | Path) -> Instrument:
    """Load GSAS-II instrument parameters from an .instprm file.

    Parses the key:value format used by GSAS-II.  The large ``pdabc``
    absorption table is stored in ``raw_params`` but not mapped to
    individual fields.

    Args:
        filepath: Path to the .instprm file.

    Returns:
        Instrument object populated from the file.

    Raises:
        FileNotFoundError: If file does not exist.
        ValueError: If no valid parameters are found.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"instprm file not found: {path}")

    raw_params: dict[str, Any] = {}
    bank = 1
    in_pdabc = False
    pdabc_lines: list[str] = []

    with open(path) as f:
        for line in f:
            stripped = line.rstrip()

            # Header comment with bank number
            if stripped.startswith("#"):
                bank_match = re.search(r"Bank\s+(\d+)", stripped)
                if bank_match:
                    bank = int(bank_match.group(1))
                continue

            # Handle the multi-line pdabc block
            if stripped.startswith("pdabc:"):
                in_pdabc = True
                # The value starts after pdabc: and may be """
                continue

            if in_pdabc:
                if '"""' in stripped:
                    # End of pdabc block (closing triple-quotes)
                    in_pdabc = False
                    raw_params["pdabc"] = "\n".join(pdabc_lines)
                    pdabc_lines = []
                else:
                    pdabc_lines.append(stripped)
                continue

            # Normal key:value lines
            if ":" in stripped:
                key, _, value = stripped.partition(":")
                key = key.strip()
                value = value.strip()
                raw_params[key] = value

    if not raw_params:
        raise ValueError(f"No parameters found in {path}")

    # Build the Instrument object
    kwargs: dict[str, Any] = {
        "bank": bank,
        "source_file": str(path),
        "raw_params": raw_params,
    }

    for file_key, field_name in _INSTPRM_KEY_MAP.items():
        if file_key in raw_params:
            value = raw_params[file_key]
            if field_name == "inst_type":
                kwargs[field_name] = str(value)
            else:
                kwargs[field_name] = float(value)

    return Instrument(**kwargs)


# ---------------------------------------------------------------------------
# CIF loader
# ---------------------------------------------------------------------------


def load_cif(filepath: str | Path) -> CrystalPhase:
    """Load a crystal structure from a CIF file.

    Uses pycifstar to parse the CIF and extracts lattice parameters,
    space group, and atom site information into a CrystalPhase object.

    Args:
        filepath: Path to the .cif file.

    Returns:
        CrystalPhase object populated from the CIF.

    Raises:
        FileNotFoundError: If file does not exist.
        ValueError: If required crystallographic fields are missing.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"CIF file not found: {path}")

    data = cif_to_data(str(path))

    # Extract lattice parameters
    try:
        a = _parse_cif_number(data["_cell_length_a"].value)
        b = _parse_cif_number(data["_cell_length_b"].value)
        c = _parse_cif_number(data["_cell_length_c"].value)
        alpha = _parse_cif_number(data["_cell_angle_alpha"].value)
        beta = _parse_cif_number(data["_cell_angle_beta"].value)
        gamma = _parse_cif_number(data["_cell_angle_gamma"].value)
    except (KeyError, TypeError) as exc:
        raise ValueError(f"CIF {path} missing required cell parameters") from exc

    # Space group
    space_group = ""
    sg_number = 0
    if data.is_value("_space_group_name_h-m_alt"):
        space_group = data["_space_group_name_h-m_alt"].value
    if data.is_value("_space_group_it_number"):
        sg_number = int(_parse_cif_number(data["_space_group_it_number"].value))

    # Chemical name for the phase label
    name = ""
    if data.is_value("_chemical_name_common"):
        name = data["_chemical_name_common"].value
    elif data.is_value("_chemical_formula_structural"):
        name = data["_chemical_formula_structural"].value

    # Atom sites
    atom_sites: list[dict[str, Any]] = []
    for loop in data.loops:
        if "_atom_site_label" in loop.names:
            n_atoms = len(loop["_atom_site_label"])
            for i in range(n_atoms):
                site: dict[str, Any] = {}
                for tag in loop.names:
                    val = loop[tag][i]
                    # Use short key without _atom_site_ prefix
                    short_key = tag.replace("_atom_site_", "")
                    site[short_key] = val
                atom_sites.append(site)
            break

    # Extra metadata
    cif_metadata: dict[str, Any] = {}
    if data.is_value("_cell_volume"):
        cif_metadata["cell_volume_cif"] = data["_cell_volume"].value
    if data.is_value("_cell_formula_units_z"):
        cif_metadata["Z"] = data["_cell_formula_units_z"].value

    # Symmetry operations — from _space_group_symop_operation_xyz loop
    symop_strings: list[str] = []
    for loop in data.loops:
        if "_space_group_symop_operation_xyz" in loop.names:
            symop_strings = list(loop["_space_group_symop_operation_xyz"])
            break
    # Fallback: older CIF format uses _symmetry_equiv_pos_as_xyz
    if not symop_strings:
        for loop in data.loops:
            if "_symmetry_equiv_pos_as_xyz" in loop.names:
                symop_strings = list(loop["_symmetry_equiv_pos_as_xyz"])
                break

    from snapwrap._inspectrum.crystallography import parse_symop

    symops = [parse_symop(s) for s in symop_strings]

    return CrystalPhase(
        name=name,
        a=a,
        b=b,
        c=c,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        space_group=space_group,
        space_group_number=sg_number,
        atom_sites=atom_sites,
        symops=symops,
        metadata=cif_metadata,
    )


# ---------------------------------------------------------------------------
# Phase description (JSON)
# ---------------------------------------------------------------------------

_AVOGADRO = 6.02214076e23


def _convert_V0_to_A3_per_cell(
    value: float,
    unit: str,
    Z: int,
) -> float:
    """Convert V₀ from a published unit to ų per unit cell.

    Args:
        value: Volume in the published unit.
        unit: One of ``"A3"`` (per cell), ``"A3/atom"`` (per atom),
            or ``"cm3/mol"`` (molar volume per formula unit).
        Z: Number of formula units (or atoms) per unit cell.

    Returns:
        Volume in ų per unit cell.

    Raises:
        ValueError: If *unit* is not recognised.
    """
    if unit in ("A3", "Å3"):
        return value
    if unit == "A3/atom":
        return value * Z
    if unit == "cm3/mol":
        return value * Z * 1e24 / _AVOGADRO
    raise ValueError(f"Unknown V_0 unit: {unit!r}")


def load_phase_descriptions(
    filepath: str | Path,
) -> ExperimentDescription:
    """Load an experiment description from a JSON file.

    The JSON format is human-editable.  See ``tests/test_data/`` for
    examples.  CIF files referenced in the JSON are loaded automatically
    relative to the JSON file's directory.

    Volume units in the JSON (``V_0_unit``) are converted to ų per
    unit cell on load.  Fields ending in ``_err`` are stored in
    :attr:`EquationOfState.extra`.

    The optional ``global_conditions`` block provides defaults that
    apply to all spectra (e.g. temperature, max_pressure).  Per-
    spectrum entries in ``spectrum_conditions`` can override these.

    Args:
        filepath: Path to the JSON file.

    Returns:
        ExperimentDescription with phases, global conditions, and
        per-spectrum conditions.

    Raises:
        FileNotFoundError: If the JSON file or a referenced CIF is
            missing.
        ValueError: If required fields are missing or invalid.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Phase description file not found: {path}")

    with open(path) as f:
        raw = json.load(f)

    if "phases" not in raw:
        raise ValueError(f"JSON file {path} must contain a 'phases' key")

    base_dir = path.parent
    descriptions: list[PhaseDescription] = []

    # --- Global conditions (optional) ---
    global_temp: float | None = None
    global_max_p: float | None = None
    if "global_conditions" in raw:
        gc = raw["global_conditions"]
        global_temp = gc.get("temperature")
        global_max_p = gc.get("max_pressure")

    for entry in raw["phases"]:
        # --- Reference conditions ---
        ref_cond = SampleConditions()
        if "reference_conditions" in entry:
            rc = entry["reference_conditions"]
            ref_cond = SampleConditions(
                pressure=rc.get("pressure"),
                temperature=rc.get("temperature"),
            )

        # --- Equation of state (optional) ---
        eos: EquationOfState | None = None
        if "eos" in entry and entry["eos"] is not None:
            eos_raw = entry["eos"]

            # Volume conversion
            V0_raw = eos_raw["V_0"]
            V0_unit = eos_raw.get("V_0_unit", "A3")
            Z = eos_raw.get("Z", 1)
            V0_cell = _convert_V0_to_A3_per_cell(V0_raw, V0_unit, Z)

            # Collect extra/error fields
            extra: dict[str, float] = {}
            skip_keys = {
                "type",
                "order",
                "V_0",
                "V_0_unit",
                "Z",
                "K_0",
                "K_prime",
                "source",
            }
            for k, v in eos_raw.items():
                if k not in skip_keys and isinstance(v, (int, float)):
                    extra[k] = float(v)

            eos = EquationOfState(
                eos_type=eos_raw["type"],
                order=eos_raw.get("order", 3),
                V_0=V0_cell,
                K_0=eos_raw["K_0"],
                K_prime=eos_raw.get("K_prime", 4.0),
                source=eos_raw.get("source", ""),
                extra=extra,
            )

        # --- Stability range (optional) ---
        stab = None
        if "stability_pressure" in entry:
            sp = entry["stability_pressure"]
            if sp is not None:
                stab = (sp[0], sp[1])

        # --- Load CIF ---
        cif_rel = entry["cif"]
        cif_path = base_dir / cif_rel
        phase = load_cif(cif_path)

        desc = PhaseDescription(
            name=entry.get("name", phase.name),
            cif_path=str(cif_rel),
            role=entry.get("role", "sample"),
            reference_conditions=ref_cond,
            eos=eos,
            stability_pressure=stab,
            phase=phase,
        )
        descriptions.append(desc)

    # --- Global data-provenance defaults ---
    instrument = raw.get("instrument", "")
    facility = raw.get("facility", "")
    pgs = raw.get("pixel_grouping_scheme", "all")

    # --- Per-spectrum conditions (optional) ---
    spec_conds: list[SpectrumConditions] = []
    for sc_raw in raw.get("spectrum_conditions", []):
        spec_conds.append(
            SpectrumConditions(
                run_number=sc_raw.get("run_number", 0),
                instrument=sc_raw.get("instrument"),
                facility=sc_raw.get("facility"),
                pgs=sc_raw.get("pixel_grouping_scheme"),
                label=sc_raw.get("label", ""),
                pressure=sc_raw.get("pressure"),
                temperature=sc_raw.get("temperature"),
            )
        )

    return ExperimentDescription(
        phases=descriptions,
        global_temperature=global_temp,
        global_max_pressure=global_max_p,
        instrument=instrument,
        facility=facility,
        pgs=pgs,
        spectrum_conditions=spec_conds,
    )
