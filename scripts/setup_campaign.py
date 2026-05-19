"""Generic campaign setup runner — reads an operator spec file and sets up a campaign.

Usage::

    python scripts/setup_campaign.py --spec /SNS/SNAP/IPTS-33219/shared/campaigns/brucite_a.json
    python scripts/setup_campaign.py --spec ... --dry-run
    python scripts/setup_campaign.py --spec ... --created-by loveday

The spec file is a small JSON document (validated against
``campaign_setup_spec.schema.json``) that lists the campaign parameters and
the assets to ingest.  It lives in the IPTS shared folder alongside the
experiment data — not in this repository.

A template/example spec is provided at::

    docs/campaign_setup_spec_template.json
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set up a snapwrap reduction-artefacts campaign from a spec file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--spec",
        required=True,
        metavar="SPEC_JSON",
        help="Path to the campaign setup spec JSON file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report what would be done without writing anything.",
    )
    parser.add_argument(
        "--created-by",
        default="operator",
        metavar="NAME",
        help="Provenance author stored in all written records (default: 'operator').",
    )
    parser.add_argument(
        "--shared-root",
        default=None,
        metavar="PATH",
        help=(
            "Override the IPTS shared root directory.  Defaults to "
            "/SNS/SNAP/IPTS-<ipts>/shared as declared in the spec."
        ),
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Run the preflight check (file existence + schema) and exit.",
    )
    args = parser.parse_args()

    from snapwrap.reduction_artefacts import preflight_spec, run_campaign_setup

    spec_path = Path(args.spec)

    if args.preflight_only:
        problems = preflight_spec(spec_path, shared_root=args.shared_root)
        if problems:
            print(f"Preflight found {len(problems)} problem(s):")
            for p in problems:
                print(f"  ✗  {p}")
            sys.exit(1)
        print("✓ Preflight passed — all source files present.")
        return

    run_campaign_setup(
        spec_path,
        dry_run=args.dry_run,
        created_by=args.created_by,
        shared_root=args.shared_root,
    )


if __name__ == "__main__":
    main()
