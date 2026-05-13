"""Build a DAC swiss-cheese bin mask from a SNAP run.

This script drives the full automated pipeline:

  raw nexus → find diamond peaks → determine UB matrices
            → build swiss-cheese mask → register artefact

Usage
-----
::

    python scripts/build_dac_mask.py \\
        --campaign bruciteA \\
        --ipts 33219 \\
        --run 65891 \\
        --width-coef 0.02 \\
        --lite

Optional flags
--------------
--dry-run        Print what would be done without writing any files.
--dens-thresh N  FindPeaksMD density threshold (default: 400).
--notes TEXT     Free-text notes stored in provenance.

Re-run from saved UBs
---------------------
If you have already determined the UBs and only want to regenerate the mask
(e.g. after changing ``--width-coef``) pass the UB paths explicitly::

    python scripts/build_dac_mask.py \\
        --campaign bruciteA --ipts 33219 --run 65891 \\
        --width-coef 0.03 --lite \\
        --ub /path/to/SNAP65891UB1.mat \\
        --ub /path/to/SNAP65891UB2.mat

In this mode the peak-finding step is skipped (much faster).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build a DAC swiss-cheese bin mask from a SNAP run.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    p.add_argument("--campaign", required=True, metavar="SLUG",
                   help="Campaign slug (must already be bootstrapped).")
    p.add_argument("--ipts", required=True, type=int,
                   help="IPTS experiment number.")
    p.add_argument("--run", required=True, type=int, dest="run_number",
                   help="SNAP run number to process.")
    p.add_argument("--width-coef", required=True, type=float, nargs="+",
                   dest="width_coef", metavar="COEF",
                   help="Polynomial notch-width coefficient(s). "
                        "A single value, e.g. 0.02, gives a flat width.")
    p.add_argument("--lite", action="store_true",
                   help="Set when the instrument was in Lite (18432-pixel) mode.")
    p.add_argument("--ub", action="append", dest="ub_paths", metavar="PATH",
                   help="Path to a pre-computed ISAW UB .mat file. "
                        "Pass this flag twice (once per diamond) to skip peak finding.")
    p.add_argument("--artefact-id", dest="artefact_id", default=None,
                   help="Artefact ID for the registry (default: dac_mask_{campaign}_{run}).")
    p.add_argument("--prefix", default=None,
                   help="Filename prefix for mask JSON (default: dac_mask_{campaign}).")
    p.add_argument("--shared-root", dest="shared_root", default=None,
                   help="Override IPTS shared root (for testing).")
    p.add_argument("--lam-min", dest="lam_min", type=float, default=0.5,
                   help="Minimum wavelength (Å) for reflection enumeration (default: 0.5).")
    p.add_argument("--dens-thresh", dest="dens_thresh", type=float, default=400,
                   help="FindPeaksMD density threshold (default: 400).")
    p.add_argument("--notes", default=None,
                   help="Free-text notes stored in the artefact provenance.")
    p.add_argument("--dry-run", action="store_true", dest="dry_run",
                   help="Print the planned operations without executing them.")

    return p.parse_args(argv)


def main(argv=None) -> int:  # noqa: C901
    args = _parse_args(argv)

    campaign = args.campaign
    ipts = args.ipts
    run = args.run_number
    width_coef = args.width_coef
    is_lite = args.lite
    shared_root = Path(args.shared_root) if args.shared_root else None
    artefact_id = args.artefact_id or f"dac_mask_{campaign}_run{run}"
    file_prefix = args.prefix or f"dac_mask_{campaign}"

    # Resolve output directory under the asset store for this campaign
    if shared_root is not None:
        root = shared_root
    else:
        root = Path(f"/SNS/SNAP/IPTS-{ipts}/shared")

    output_dir = (
        root / "snapwrap" / "reduction_artefacts"
        / "campaigns" / campaign / "artefacts" / f"dac_mask_run{run}"
    )

    print(f"Campaign  : {campaign}")
    print(f"IPTS      : {ipts}")
    print(f"Run       : {run}")
    print(f"Width coef: {width_coef}")
    print(f"Lite mode : {is_lite}")
    print(f"Output dir: {output_dir}")

    if args.dry_run:
        print("\n[dry-run] No files written.")
        return 0

    from snapwrap.reduction_artefacts.masking import (
        build_swiss_cheese_from_run,
        build_swiss_cheese_from_ub_files,
    )
    from snapwrap.reduction_artefacts.persistence import register_swiss_cheese_artefact

    # ── Build the mask ────────────────────────────────────────────────────
    if args.ub_paths:
        # Fast path: UBs already on disk
        print(f"\nUsing {len(args.ub_paths)} pre-computed UB file(s):")
        for ub in args.ub_paths:
            print(f"  {ub}")
        mask_paths = build_swiss_cheese_from_ub_files(
            ub_paths=args.ub_paths,
            run_number=run,
            width_coef=width_coef,
            is_lite=is_lite,
            output_dir=output_dir,
            file_prefix=file_prefix,
            ipts=ipts,
            lam_min=args.lam_min,
        )
        ub_paths = [Path(p) for p in args.ub_paths]
    else:
        # Full pipeline: peak finding + UB determination
        print("\nRunning full pipeline (peak finding + UB determination)…")
        mask_paths, ub_paths = build_swiss_cheese_from_run(
            run_number=run,
            width_coef=width_coef,
            is_lite=is_lite,
            output_dir=output_dir,
            file_prefix=file_prefix,
            ipts=ipts,
            lam_min=args.lam_min,
            dens_thresh=args.dens_thresh,
        )

    print(f"\nMask files written ({len(mask_paths)}):")
    for mp in mask_paths:
        print(f"  {mp}")

    print(f"\nUB files ({len(ub_paths)}):")
    for ub in ub_paths:
        print(f"  {ub}")

    if not mask_paths:
        print("ERROR: No mask JSON files were produced.", file=sys.stderr)
        return 1

    # ── Register artefact ─────────────────────────────────────────────────
    # Register one artefact record per mask JSON (typically one — Wavelength)
    for mask_path in mask_paths:
        record = register_swiss_cheese_artefact(
            ipts=ipts,
            campaign_identifier=campaign,
            artefact_id=artefact_id,
            mask_json_path=str(mask_path),
            source_run=run,
            ub_mat_paths=[str(p) for p in ub_paths],
            width_coef=width_coef,
            is_lite=is_lite,
            shared_root=shared_root,
            notes=args.notes,
        )
        print(f"\nRegistered artefact: {record['record_id']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
