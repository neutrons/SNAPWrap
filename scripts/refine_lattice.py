"""Phase D CLI: refine lattice parameters for a campaign run.

Usage
-----
::

    pixi run python scripts/refine_lattice.py \\
        --campaign bruciteA \\
        --ipts 33219 \\
        --run 65893 \\
        --workspace /path/to/focused_65893.nxs \\
        --instprm /path/to/snap_bank1.instprm \\
        [--bank 0] \\
        [--P-min 0.0] \\
        [--P-max 50.0] \\
        [--shared-root /SNS/SNAP] \\
        [--dry-run]

Workflow
--------
1. Load the campaign manifest from ``{shared_root}/IPTS-{ipts}/shared/
   snapwrap/reduction_artefacts/campaigns/{campaign}/manifest.json``.
2. Build ``crystalSpecies`` objects from ``candidate_species`` entries
   (those whose CIF asset is registered).
3. Load the Mantid workspace from ``--workspace``.
4. Call ``refine_species_from_workspace``.
5. Print the refinement report.
6. (Unless ``--dry-run``) Call ``annotate_run`` to persist
   ``observed_species`` back into the living manifest.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Refine lattice parameters for a SNAP campaign run.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--campaign", required=True, help="Campaign slug (e.g. bruciteA)")
    p.add_argument("--ipts", required=True, type=int, help="IPTS number")
    p.add_argument("--run", required=True, type=int, help="Run number to annotate")
    p.add_argument(
        "--workspace",
        required=True,
        type=Path,
        help="Path to focused Mantid workspace (.nxs or .nxs.h5)",
    )
    p.add_argument(
        "--instprm",
        required=True,
        type=Path,
        help="Path to GSAS-II .instprm file for the target bank",
    )
    p.add_argument("--bank", type=int, default=0, help="Spectrum index (0-based)")
    p.add_argument("--P-min", type=float, default=0.0, help="Lower pressure bound (GPa)")
    p.add_argument("--P-max", type=float, default=None, help="Upper pressure bound (GPa)")
    p.add_argument(
        "--shared-root",
        type=Path,
        default=Path("/SNS/SNAP"),
        help="Root of the SNAP shared area",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the report but do not persist back to the manifest",
    )
    return p


def main(argv=None) -> int:
    args = _build_arg_parser().parse_args(argv)

    # ------------------------------------------------------------------
    # 1. Locate the campaign manifest
    # ------------------------------------------------------------------
    campaign_dir = (
        args.shared_root
        / f"IPTS-{args.ipts}"
        / "shared"
        / "snapwrap"
        / "reduction_artefacts"
        / "campaigns"
        / args.campaign
    )
    manifest_path = campaign_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"ERROR: campaign manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    with manifest_path.open() as fh:
        manifest = json.load(fh)

    candidate_species = manifest.get("candidate_species", [])
    if not candidate_species:
        print("ERROR: no candidate_species in manifest.", file=sys.stderr)
        return 1

    # ------------------------------------------------------------------
    # 2. Build crystalSpecies from manifest entries
    # ------------------------------------------------------------------
    try:
        import mantid  # noqa: F401
        from snapwrap.sampleMeta.utils import crystalSpecies
        from snapwrap.sampleMeta.eos import EquationOfState
    except ImportError as exc:
        print(f"ERROR: Mantid or snapwrap.sampleMeta unavailable: {exc}", file=sys.stderr)
        return 1

    species_list = []
    for entry in candidate_species:
        cif_path = entry.get("cif")
        if not cif_path or not Path(cif_path).exists():
            print(
                f"  WARNING: skipping {entry.get('species_id')!r} "
                f"— CIF not found: {cif_path}"
            )
            continue

        eos_dict = entry.get("eos")
        eos = None
        if eos_dict:
            try:
                eos = EquationOfState(
                    eos_type=eos_dict["type"],
                    V_0=eos_dict["V_0"],
                    K_0=eos_dict["K_0"],
                    K_prime=eos_dict["K_prime"],
                )
            except Exception as exc:
                print(f"  WARNING: could not parse EOS for {entry.get('species_id')!r}: {exc}")

        try:
            sp = crystalSpecies.from_cif(
                cif_path,
                name=entry.get("species_id"),
                role=entry.get("role", "sample"),
                eos=eos,
            )
            species_list.append(sp)
            print(f"  Loaded species: {sp.name}  ({sp.crystalSystem})")
        except Exception as exc:
            print(f"  WARNING: failed to load species {entry.get('species_id')!r}: {exc}")

    if not species_list:
        print("ERROR: no species could be loaded.", file=sys.stderr)
        return 1

    # ------------------------------------------------------------------
    # 3. Load the Mantid workspace
    # ------------------------------------------------------------------
    try:
        from mantid.simpleapi import LoadNexus
        ws = LoadNexus(str(args.workspace), OutputWorkspace="_refine_lattice_ws")
        print(f"  Loaded workspace: {ws.name()}  ({ws.getNumberHistograms()} spectra)")
    except Exception as exc:
        print(f"ERROR: could not load workspace {args.workspace}: {exc}", file=sys.stderr)
        return 1

    # ------------------------------------------------------------------
    # 4. Refine
    # ------------------------------------------------------------------
    from snapwrap.sampleMeta.refine import refine_species_from_workspace

    print(f"\nRefining against bank {args.bank}, P=[{args.P_min}, {args.P_max}] GPa ...")
    report = refine_species_from_workspace(
        species_list,
        ws,
        args.instprm,
        bank=args.bank,
        P_min=args.P_min,
        P_max=args.P_max,
    )

    # ------------------------------------------------------------------
    # 5. Print report
    # ------------------------------------------------------------------
    print(f"\nSweep pressure: {report.sweep_pressure_gpa} GPa")
    print(f"Refinements: {len(report.refinements)}")
    for ref in report.refinements:
        status = "✓" if ref.success else "✗"
        p_str = f"{ref.pressure_gpa:.2f} GPa" if ref.pressure_gpa is not None else "—"
        print(
            f"  {status} {ref.phase_name:<20s} "
            f"a={ref.a:.5f}  b={ref.b:.5f}  c={ref.c:.5f} Å  "
            f"P={p_str}  n_peaks={ref.n_peaks_used}  "
            f"RSS={ref.residual_sum_sq:.4e}"
        )

    # ------------------------------------------------------------------
    # 6. Persist (unless dry-run)
    # ------------------------------------------------------------------
    if args.dry_run:
        print("\n[dry-run] Not persisting results.")
        return 0

    from snapwrap.reduction_artefacts import (
        annotate_run,
        register_crystal_species_artefact,
    )

    # 6a. Register each successful refinement as a crystalSpecies artefact.
    # This writes a record to crystal_species_index.jsonl and returns its path,
    # which we then embed in the manifest via annotate_run.
    observed = []
    for sp in report.species:
        if not (sp.refined and sp.refined["success"]):
            continue

        # Find the matching manifest entry to get cif_asset_id provenance.
        manifest_entry = next(
            (e for e in candidate_species if e.get("species_id") == sp.name),
            {},
        )

        artefact_record = register_crystal_species_artefact(
            ipts=args.ipts,
            campaign_identifier=args.campaign,
            species_name=sp.name,
            cif_path=sp.cifPath,
            role=sp.role,
            source_run=args.run,
            refined_a=sp.refined["a"],
            refined_b=sp.refined["b"],
            refined_c=sp.refined["c"],
            refined_pressure_gpa=sp.refined["pressure_gpa"],
            unitCell_updated=True,
            cif_asset_id=manifest_entry.get("artefact_path"),  # best-effort
            shared_root=args.shared_root,
        )

        # artefact_record path is used to close the loop in the manifest.
        artefact_path = artefact_record.get("path") or artefact_record.get("record_id")

        observed.append(
            {
                "species_id": sp.name,
                "lattice_params": {
                    "a": sp.refined["a"],
                    "b": sp.refined["b"],
                    "c": sp.refined["c"],
                    "alpha": sp.refined["alpha"],
                    "beta": sp.refined["beta"],
                    "gamma": sp.refined["gamma"],
                },
                "pressure_gpa": sp.refined["pressure_gpa"],
                "artefact_path": artefact_path,
            }
        )
        print(f"  Registered artefact: {sp.name}  →  {artefact_path}")

    # 6b. Write observed_species back into the living manifest.
    if observed:
        annotate_run(
            ipts=args.ipts,
            campaign_identifier=args.campaign,
            run_number=args.run,
            shared_root=args.shared_root,
            observed_species=observed,
        )
        print(f"\nAnnotated run {args.run} with {len(observed)} observed species.")
    else:
        print("\nNo successful refinements — run not annotated.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
