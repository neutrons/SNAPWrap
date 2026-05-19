"""Manifest-driven reduction runner for IPTS-33219 bruciteA DAC campaign.

This script reads the run manifest built by ``setup_campaign_brucite_a.py``
(via ``build_run_manifest``) and drives ``snapwrap.reduce`` with exactly the
artefacts recorded in that manifest.  It is designed to be run from within
Mantid Workbench or a pixi shell where Mantid is available.

Usage (from repo root)::

    # Reduce a single run:
    python scripts/run_campaign_reduction.py --run 65891

    # Reduce all campaign runs:
    python scripts/run_campaign_reduction.py --all

    # Dry-run (print kwargs, don't actually reduce):
    python scripts/run_campaign_reduction.py --run 65891 --dry-run

    # Re-reduce (build a new attempt manifest even if one exists):
    python scripts/run_campaign_reduction.py --run 65891 --new-attempt
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Campaign parameters ───────────────────────────────────────────────────────
IPTS = 33219
CAMPAIGN_SLUG = "dac_brucite_a"
RUNS = [65891, 65892, 65893, 65894, 65895, 65896]
SHARED_ROOT = Path(f"/SNS/SNAP/IPTS-{IPTS}/shared")


def _latest_manifest_path(run_number: int) -> Path | None:
    """Return the path of the highest-attempt manifest for *run_number*, or None."""
    manifests_dir = (
        SHARED_ROOT
        / "snapwrap"
        / "reduction_artefacts"
        / "campaigns"
        / CAMPAIGN_SLUG
        / "manifests"
    )
    if not manifests_dir.exists():
        return None
    candidates = sorted(manifests_dir.glob(f"run_{run_number}_attempt_*.json"))
    return candidates[-1] if candidates else None


def _build_manifest(run_number: int) -> Path:
    """Build (or rebuild) the run manifest and return its path."""
    from snapwrap.reduction_artefacts import build_run_manifest

    result = build_run_manifest(
        ipts=IPTS,
        campaign_identifier=CAMPAIGN_SLUG,
        run_number=run_number,
        shared_root=SHARED_ROOT,
    )
    p = Path(result["manifest_path"])
    log.info("Manifest written: %s (attempt %d)", p.name, result["attempt_number"])
    return p


def reduce_run(
    run_number: int,
    *,
    new_attempt: bool = False,
    dry_run: bool = False,
    keep_unfocussed: bool = True,
    verbose: bool = True,
) -> None:
    """Reduce a single run using its latest (or freshly built) manifest."""
    # ── Locate or create manifest ─────────────────────────────────────────────
    manifest_path = _latest_manifest_path(run_number)
    if manifest_path is None or new_attempt:
        log.info("Building run manifest for run %d...", run_number)
        manifest_path = _build_manifest(run_number)
    else:
        log.info("Using existing manifest: %s", manifest_path.name)

    # ── Load manifest and print summary ──────────────────────────────────────
    with manifest_path.open("r") as fh:
        manifest = json.load(fh)

    print(f"\n{'═'*60}")
    print(f"  Run {run_number}  —  manifest attempt {manifest['attempt_number']}")
    print(f"{'═'*60}")
    print(f"  Assembly : {manifest.get('assembly_type', '?')}")
    print(f"  Manifest : {manifest_path}")
    print()
    for entry in manifest.get("selected_artefacts", []):
        status = entry.get("status", "?")
        mark = "✓" if status == "active" else "⚠" if status == "planned" else "?"
        print(
            f"  {mark} [{entry.get('artefact_type', '?'):<28}] "
            f"{entry.get('artefact_id', '?'):<40}  status={status}"
        )
        if status == "planned":
            print(f"      ↳ path=PENDING — this artefact is not yet available")
    print()

    if dry_run:
        print("[dry-run] kwargs that would be passed to wrap.reduce():")
        from snapwrap.reduction_artefacts.reduce import build_reduce_kwargs

        def _mock_cheese_loader(path: str) -> list[str]:
            """Return plausible workspace names from the mask JSON filename."""
            stem = Path(path).stem
            return [f"maskBins_{stem}"]

        try:
            kwargs = build_reduce_kwargs(
                manifest,
                cheese_loader=_mock_cheese_loader,
                verbose=verbose,
                keepUnfocussed=keep_unfocussed,
            )
            print(f"  wrap.reduce({run_number},")
            for k, v in kwargs.items():
                print(f"    {k}={v!r},")
            print("  )")
        except RuntimeError as exc:
            print(f"  [BLOCKED] {exc}")
        return

    # ── Real reduction ────────────────────────────────────────────────────────
    try:
        import snapwrap  # noqa: F401 (presence check before heavy import)
    except ImportError:
        log.error(
            "snapwrap/Mantid not importable.  "
            "Run this script from within Mantid Workbench or a pixi shell with Mantid."
        )
        sys.exit(1)

    from snapwrap import SNAPWrap
    from snapwrap.reduction_artefacts.reduce import reduce_from_manifest

    log.info("Initialising SNAPWrap for IPTS %d ...", IPTS)
    wrap = SNAPWrap(IPTS=IPTS)

    # The cheese_loader wraps the wrap instance so the cheese API can be called
    # without passing wrap into build_reduce_kwargs separately.
    def _cheese_loader(path: str) -> list[str]:
        cheese = wrap.cheeseMask()
        cheese.load(filename=path)
        cheese.makeMaskBinsTables()
        # Return workspace names as produced by the real cheese mask object.
        # The actual attribute depends on the SNAPReduce version; common names:
        try:
            return cheese.getWorkspaceNames()
        except AttributeError:
            # Fallback: derive from the JSON filename (dSpacing / Wavelength)
            stem = Path(path).stem
            # e.g. SNAP_65896_dSpacing → maskBins_dSpacing
            for tag in ("dSpacing", "Wavelength", "TOF"):
                if tag.lower() in stem.lower():
                    return [f"maskBins_{tag}"]
            return [f"maskBins_{stem}"]

    log.info("Starting reduction for run %d ...", run_number)
    result = reduce_from_manifest(
        manifest_path,
        wrap=wrap,
        cheese_loader=_cheese_loader,
        verbose=verbose,
        keepUnfocussed=keep_unfocussed,
    )
    log.info("Reduction complete for run %d.  Result: %s", run_number, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manifest-driven reduction for IPTS-33219 bruciteA."
    )
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--run", type=int, metavar="RUN", help="Reduce a single run number.")
    grp.add_argument("--all", action="store_true", help="Reduce all campaign runs.")
    parser.add_argument(
        "--new-attempt",
        action="store_true",
        help="Build a fresh manifest (new attempt) even if one already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the reduce kwargs without actually calling reduce.",
    )
    parser.add_argument(
        "--no-keep-unfocussed",
        action="store_true",
        help="Do not keep unfocussed data (default: keep).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce verbosity of the reduce call.",
    )
    args = parser.parse_args()

    runs = RUNS if args.all else [args.run]
    for run in runs:
        reduce_run(
            run,
            new_attempt=args.new_attempt,
            dry_run=args.dry_run,
            keep_unfocussed=not args.no_keep_unfocussed,
            verbose=not args.quiet,
        )


if __name__ == "__main__":
    main()
