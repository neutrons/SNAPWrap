"""CLI script: ingest an asset file into a campaign's managed asset store.

Usage examples::

    # Ingest a CIF file campaign-wide
    python scripts/ingest_asset.py \\
        --ipts 35214 \\
        --campaign dac_fe_01 \\
        --source /path/to/sample.cif \\
        --asset-type cif

    # Ingest a SEEMeta JSON for a specific run
    python scripts/ingest_asset.py \\
        --ipts 35214 \\
        --campaign dac_fe_01 \\
        --source /SNS/SNAP/IPTS-35214/shared/SEE/SEE065891.json \\
        --asset-type seemeta_json \\
        --scope run \\
        --run 65891

    # Ingest a UB matrix with an explicit asset-id
    python scripts/ingest_asset.py \\
        --ipts 35214 \\
        --campaign dac_fe_01 \\
        --source /path/to/diamond_a.mat \\
        --asset-type ub_matrix \\
        --asset-id diamond-a-run65891 \\
        --scope run --run 65891

    # Convenience: ingest a SEEMeta JSON using the run-scoped shortcut
    python scripts/ingest_asset.py \\
        --ipts 35214 \\
        --campaign dac_fe_01 \\
        --seemeta-run 65891 \\
        --source /SNS/SNAP/IPTS-35214/shared/SEE/SEE065891.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest an asset file into a SNAPWrap campaign asset store.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--ipts", type=int, required=True, help="IPTS experiment number.")
    parser.add_argument("--campaign", required=True, help="Campaign slug, alias, or numeric id.")
    parser.add_argument("--source", required=True, help="Path to the source file to ingest.")
    parser.add_argument(
        "--asset-type",
        help="Asset type (cif, eos_description, ub_matrix, seemeta_json, "
             "manual_pixel_mask, phase_description, other). "
             "Not required when --seemeta-run is used.",
    )
    parser.add_argument(
        "--asset-id",
        default=None,
        help="Logical asset id (default: source file stem).",
    )
    parser.add_argument(
        "--scope",
        choices=["campaign", "run"],
        default="campaign",
        help="Applicability scope (default: campaign).",
    )
    parser.add_argument(
        "--run",
        type=int,
        default=None,
        help="Run number (required when --scope run).",
    )
    parser.add_argument(
        "--seemeta-run",
        type=int,
        default=None,
        metavar="RUN",
        help="Shortcut: ingest as seemeta_json scoped to this run number.",
    )
    parser.add_argument(
        "--provenance-source",
        default="imported",
        choices=["manual", "imported", "generated", "acquired"],
        help="How the asset was obtained (default: imported).",
    )
    parser.add_argument("--created-by", default="operator", help="Creator identifier.")
    parser.add_argument("--notes", default=None, help="Free-text note.")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing file in the asset store if content differs.",
    )
    parser.add_argument(
        "--shared-root",
        default=None,
        help="Override IPTS shared root (for testing).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without writing anything.",
    )

    args = parser.parse_args(argv)

    try:
        from snapwrap.reduction_artefacts import ingest_asset, ingest_seemeta_for_run
    except ImportError as exc:
        print(f"ERROR: could not import snapwrap: {exc}", file=sys.stderr)
        return 2

    src = Path(args.source)
    if not src.exists():
        print(f"ERROR: source file not found: {src}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"[dry-run] Would ingest {src} as {args.asset_type or 'seemeta_json'} "
              f"into campaign {args.campaign!r} (IPTS {args.ipts})")
        return 0

    try:
        if args.seemeta_run is not None:
            record = ingest_seemeta_for_run(
                ipts=args.ipts,
                campaign_identifier=args.campaign,
                source_path=src,
                run_number=args.seemeta_run,
                shared_root=args.shared_root,
                created_by=args.created_by,
                notes=args.notes,
                overwrite=args.overwrite,
            )
        else:
            if not args.asset_type:
                print("ERROR: --asset-type is required unless --seemeta-run is used.", file=sys.stderr)
                return 1
            record = ingest_asset(
                ipts=args.ipts,
                campaign_identifier=args.campaign,
                source_path=src,
                asset_type=args.asset_type,
                asset_id=args.asset_id,
                shared_root=args.shared_root,
                applicability_scope=args.scope,
                run_number=args.run,
                provenance_source=args.provenance_source,
                created_by=args.created_by,
                notes=args.notes,
                overwrite=args.overwrite,
            )
    except (ValueError, FileNotFoundError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(record, indent=2))
    print(
        f"\n✓ Ingested {record['asset_type']} asset {record['asset_id']!r} "
        f"(v{record['version']}) → {record['path']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
