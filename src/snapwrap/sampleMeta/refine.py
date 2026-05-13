"""Phase D: inspectrum refinement bridge.

Provides ``refine_species_from_workspace``, which accepts a list of
``crystalSpecies`` objects and a Mantid ``Workspace2D`` (focused,
d-spacing) and returns a ``RefinementReport`` containing the
per-species lattice refinement results.

The function does **not** touch persistence — the caller is
responsible for calling ``register_crystal_species_artefact`` and/or
``annotate_run`` after inspecting the report.

Typical usage
-------------
::

    from snapwrap.sampleMeta.refine import refine_species_from_workspace
    from snapwrap.reduction_artefacts import annotate_run

    report = refine_species_from_workspace(
        species_list, ws, "/path/to/snap_bank1.instprm"
    )
    for sp in report.species:
        if sp.refined and sp.refined["success"]:
            print(sp.name, sp.refined["a"], sp.refined["pressure_gpa"])

    annotate_run(
        ipts=33219,
        campaign_identifier="bruciteA",
        run_number=65893,
        shared_root=...,
        observed_species=[
            {
                "species_id": sp.name,
                "lattice_params": {k: sp.refined[k] for k in ("a","b","c","alpha","beta","gamma")},
                "pressure_gpa": sp.refined["pressure_gpa"],
                "artefact_path": None,
            }
            for sp in report.species
            if sp.refined and sp.refined["success"]
        ],
    )
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# RefinementReport
# ---------------------------------------------------------------------------


@dataclass
class RefinementReport:
    """Output of ``refine_species_from_workspace``.

    Attributes:
        refinements: Raw :class:`~snapwrap._inspectrum.lattice.LatticeRefinementResult`
            objects returned by the inspectrum engine (one per phase
            that was included in the refinement).
        species: The **mutated** ``crystalSpecies`` objects.  Each
            species whose name matched a refinement result has its
            ``unitCell`` and ``refined`` attribute updated in-place.
        sweep_pressure_gpa: Best-fit pressure from the pressure sweep
            (GPa), or ``None`` if no EOS-guided sweep was performed.
        metadata: Provenance and diagnostic information.
    """

    refinements: list = field(default_factory=list)
    species: list = field(default_factory=list)
    sweep_pressure_gpa: float | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation of the report.

        Suitable for passing to ``register_crystal_species_artefact``
        or writing to a JSON file.
        """
        return {
            "sweep_pressure_gpa": self.sweep_pressure_gpa,
            "refinements": [_refinement_to_dict(r) for r in self.refinements],
            "species": [sp.to_dict() for sp in self.species],
            "metadata": self.metadata,
        }


def _refinement_to_dict(ref) -> dict:
    """Serialise a ``LatticeRefinementResult`` to a plain dict."""
    return {
        "phase_name": ref.phase_name,
        "a": ref.a,
        "b": ref.b,
        "c": ref.c,
        "alpha": ref.alpha,
        "beta": ref.beta,
        "gamma": ref.gamma,
        "pressure_gpa": ref.pressure_gpa,
        "residual_sum_sq": ref.residual_sum_sq,
        "n_peaks_used": ref.n_peaks_used,
        "n_peaks_excluded": ref.n_peaks_excluded,
        "success": ref.success,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def refine_species_from_workspace(
    species_list: list,
    ws,
    instprm_path: str | Path,
    conditions=None,
    *,
    bank: int = 0,
    P_min: float = 0.0,
    P_max: float | None = None,
) -> RefinementReport:
    """Refine lattice parameters for a list of crystal species against a workspace.

    This is the inspectrum bridge.  It converts a Mantid
    ``Workspace2D`` (focused, d-spacing) to a
    ``DiffractionSpectrum``, builds ``PhaseDescription`` objects
    directly from each species' ``cifPath`` and ``eos``, calls the
    inspectrum ``inspect()`` engine, then maps the refined lattice
    parameters back onto the input ``crystalSpecies`` objects.

    The input ``species_list`` is mutated in-place: each matched
    species gets its ``unitCell`` updated and a ``refined`` dict
    attached (see ``crystalSpecies.refined`` in
    ``sampleMeta/utils.py``).

    Args:
        species_list: List of ``crystalSpecies`` objects to refine.
            Species without a ``cifPath`` are silently skipped.
        ws: Mantid ``Workspace2D`` in d-spacing (focused).  Must have
            at least ``bank + 1`` spectra.
        instprm_path: Path to the GSAS-II ``.instprm`` file for the
            relevant bank.
        conditions: Optional
            :class:`~snapwrap._inspectrum.models.SampleConditions`
            object encoding known P/T conditions.  Passed to the
            ``ExperimentDescription`` as ``sample_conditions``.
        bank: Spectrum index to read from ``ws`` (0-based).  Defaults
            to 0.
        P_min: Lower pressure bound for the inspectrum pressure sweep
            (GPa).  Defaults to 0.
        P_max: Upper pressure bound for the pressure sweep (GPa).
            Defaults to ``None`` (engine default of 100 GPa).

    Returns:
        A :class:`RefinementReport` with the per-phase refinement
        results, the mutated species list, the best-fit sweep
        pressure, and diagnostic metadata.

    Raises:
        ImportError: If the ``snapwrap._inspectrum`` package is not
            available.
        ValueError: If ``ws`` has fewer spectra than ``bank + 1``.
        FileNotFoundError: If ``instprm_path`` does not exist.
    """
    import numpy as np

    from snapwrap._inspectrum.engine import inspect as _inspect
    from snapwrap._inspectrum.loaders import load_cif, load_instprm
    from snapwrap._inspectrum.models import (
        DiffractionSpectrum,
        ExperimentDescription,
        PhaseDescription,
    )

    instprm_path = Path(instprm_path)
    if not instprm_path.exists():
        raise FileNotFoundError(f"instprm file not found: {instprm_path}")

    # ------------------------------------------------------------------
    # Step 1 — build PhaseDescription objects directly from CIF + EOS
    # ------------------------------------------------------------------
    phase_descs: list[PhaseDescription] = []
    for sp in species_list:
        if not sp.cifPath:
            continue
        crystal_phase = load_cif(sp.cifPath)
        crystal_phase.name = sp.name or crystal_phase.name

        # Map snapwrap EquationOfState → inspectrum EquationOfState.
        # They are structurally identical (both dataclasses with the
        # same field names), but may be from different modules.
        insp_eos = _coerce_eos(sp.eos)

        # stability_pressure: use tuple if the species has one set
        stability = getattr(sp, "stability_pressure", None)

        desc = PhaseDescription(
            name=sp.name or crystal_phase.name,
            cif_path=str(sp.cifPath),
            role=sp.role,
            eos=insp_eos,
            stability_pressure=stability,
            phase=crystal_phase,
        )
        phase_descs.append(desc)

    if not phase_descs:
        # Nothing to refine — return an empty report.
        return RefinementReport(
            species=list(species_list),
            metadata={
                "warning": "No species with cifPath — nothing to refine.",
                "timestamp": _now_iso(),
            },
        )

    experiment = ExperimentDescription(
        phases=phase_descs,
        global_max_pressure=P_max,
    )

    # ------------------------------------------------------------------
    # Step 2 — load instrument
    # ------------------------------------------------------------------
    instrument = load_instprm(instprm_path)

    # ------------------------------------------------------------------
    # Step 3 — adapt Mantid workspace → DiffractionSpectrum
    # ------------------------------------------------------------------
    n_spec = ws.getNumberHistograms()
    if bank >= n_spec:
        raise ValueError(
            f"Requested bank={bank} but workspace has only {n_spec} spectra."
        )

    x = np.array(ws.readX(bank))
    y = np.array(ws.readY(bank))
    e = np.array(ws.readE(bank))

    # Mantid uses bin boundaries; convert to bin centres if needed.
    if len(x) == len(y) + 1:
        x = 0.5 * (x[:-1] + x[1:])

    spectrum = DiffractionSpectrum(
        x=x,
        y=y,
        e=e,
        x_unit="d-Spacing",
        label=str(ws.name()),
        bank=bank,
    )

    # ------------------------------------------------------------------
    # Step 4 — call the inspectrum engine
    # ------------------------------------------------------------------
    result = _inspect(
        spectrum,
        instrument,
        experiment,
        P_min=P_min,
        P_max=P_max or 100.0,
    )

    # ------------------------------------------------------------------
    # Step 5 — map refined lattice params back onto crystalSpecies
    # ------------------------------------------------------------------
    for ref in result.refinements:
        sp = next(
            (s for s in species_list if s.name == ref.phase_name), None
        )
        if sp is None:
            continue

        # Update unit cell in-place.
        if sp.unitCell is not None:
            sp.unitCell.a = ref.a
            sp.unitCell.b = ref.b
            sp.unitCell.c = ref.c
            sp.unitCell.alpha = ref.alpha
            sp.unitCell.beta = ref.beta
            sp.unitCell.gamma = ref.gamma
        sp.valid["unitCell"] = True

        # Rebuild Mantid CrystalStructure so tick marks use the
        # refined cell (best-effort — no-op if Mantid is absent).
        try:
            sp._buildCrystalStructure()
        except Exception:
            pass

        # Attach the full refinement summary.
        sp.refined = {
            "a": ref.a,
            "b": ref.b,
            "c": ref.c,
            "alpha": ref.alpha,
            "beta": ref.beta,
            "gamma": ref.gamma,
            "pressure_gpa": ref.pressure_gpa,
            "residual_sum_sq": ref.residual_sum_sq,
            "n_peaks_used": ref.n_peaks_used,
            "success": ref.success,
        }

    return RefinementReport(
        refinements=result.refinements,
        species=list(species_list),
        sweep_pressure_gpa=result.sweep_pressure_gpa,
        metadata={
            "instprm": str(instprm_path),
            "workspace": str(ws.name()),
            "bank": bank,
            "P_min": P_min,
            "P_max": P_max,
            "n_phases": len(phase_descs),
            "timestamp": _now_iso(),
        },
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _coerce_eos(eos):
    """Convert any EquationOfState-like object to the inspectrum variant.

    Both snapwrap and inspectrum define ``EquationOfState`` as a
    dataclass with the same fields.  If the incoming object is
    already the inspectrum type (or ``None``), return it unchanged.
    Otherwise reconstruct from its ``__dict__``.
    """
    if eos is None:
        return None

    from snapwrap._inspectrum.models import EquationOfState as InspEOS

    if isinstance(eos, InspEOS):
        return eos

    # Try to coerce via field names.
    try:
        from dataclasses import asdict as _asdict
        return InspEOS(**_asdict(eos))
    except Exception:
        pass

    # Last resort: attribute access.
    try:
        return InspEOS(
            eos_type=eos.eos_type,
            V_0=eos.V_0,
            K_0=eos.K_0,
            K_prime=eos.K_prime,
        )
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat(timespec="seconds")
