"""CLI script: show the resolved asset/artefact set for a run.

Prints (in normative glossary terms) which artefacts are required, which are
available, and what would be selected for reduction — before writing any
manifest.  Use this to preview ``build_run_manifest`` without committing.

Usage examples::

    # Preview resolution for a DAC run
    python scripts/show_run_resolution.py \\
        --ipts 35214 \\
        --campaign dac_fe_01 \\
        --run 65891

    # Specify assembly type explicitly (override campaign.json)
    python scripts/show_run_resolution.py \\
        --ipts 35214 \\
        --campaign pe_h2o_01 \\
        --run 65900 \\
        --assembly-type PE

    # Provide SEEMeta JSON for assembly inference
    python scripts/show_run_resolution.py \\
        --ipts 35214 \\
        --campaign dac_fe_01 \\
        --run 65891 \\
        --seemeta-json /SNS/SNAP/IPTS-35214/shared/SEE/SEE065891.json

    # Write the manifest as well
    python scripts/show_run_resolution.py \\
        --ipts 35214 --campaign dac_fe_01 --run 65891 --write-manifest
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


_STATUS_SYMBOL = {
    True: "✓",
    False: "✗",
}


def _print_report(report: dict, selected_artefacts: list[dict] | None = None) -> None:
    print(f"\nAssembly type : {report['assembly_type']}")
    if report.get("unsupported"):
        print("  (unsupported / OTHER — no artefacts required)")
        return
    print(f"Run number    : {report.get('run_number', '—')}")
    print(f"Campaign      : {report.get('campaign_slug', '—')}")
    print(f"Ready         : {_STATUS_SYMBOL[report['summary']['ready']]}  "
          f"({report['summary']['available_required']}/{report['summary']['required_total']} available)")
    print()

    by_type = {}
    if selected_artefacts:
        by_type = {s["artefact_type"]: s for s in selected_artefacts}

    for req in report["requirements"]:
        atype = req["artefact_type"]
        avail = _STATUS_SYMBOL[req["available"]]
        required_label = " [required]" if req["required"] else " [optional]"
        selected = by_type.get(atype)

        print(f"  {avail} {atype}{required_label}")
        print(f"      intended_use     : {req['intended_use']}")
        print(f"      preferred_method : {req['preferred_method']}")
        print(f"      available        : {req['available']}  (active records: {req['active_count']})")
        if selected:
            print(f"      → selected       : {selected['artefact_id']}  "
                  f"v{selected['version']}  method={selected['method']}")
            print(f"        path           : {selected['path']}")
        elif req["missing"]:
            print(f"      ✗ MISSING — this artefact must be created before reduction.")
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Show resolved artefact set for a run (normative glossary view).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--ipts", type=int, required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--run", type=int, required=True, dest="run_number")
    parser.add_argument("--assembly-type", default=None)
    parser.add_argument(
        "--seemeta-json",
        default=None,
        metavar="PATH",
        help="Path to SEEMeta JSON file for assembly inference.",
    )
    parser.add_argument(
        "--method-preferences",
        default=None,
        metavar="JSON",
        help='JSON string of per-artefact method preferences, e.g. \'{"bin_mask": "bin_mask.from_ub_pair"}\'.',
    )
    parser.add_argument(
        "--write-manifest",
        action="store_true",
        help="Also write manifests/run_<run>_attempt_<n>.json (equivalent to build_run_manifest).",
    )
    parser.add_argument("--shared-root", default=None)

    args = parser.parse_args(argv)

    try:
        from snapwrap.reduction_artefacts import (
            build_requirement_report,
            build_run_manifest,
            generate_requirement_report_for_run,
            read_jsonl_records,
            resolve_campaign_slug,
        )
        from snapwrap.reduction_artefacts.persistence import _resolve_paths
    except ImportError as exc:
        print(f"ERROR: could not import snapwrap: {exc}", file=sys.stderr)
        return 2

    seemeta: dict | None = None
    if args.seemeta_json:
        p = Path(args.seemeta_json)
        if not p.exists():
            print(f"ERROR: SEEMeta file not found: {p}", file=sys.stderr)
            return 1
        with p.open("r", encoding="utf-8") as fh:
            seemeta = json.load(fh)

    method_preferences = None
    if args.method_preferences:
        try:
            method_preferences = json.loads(args.method_preferences)
        except json.JSONDecodeError as exc:
            print(f"ERROR: --method-preferences is not valid JSON: {exc}", file=sys.stderr)
            return 1

    try:
        if args.write_manifest:
            result = build_run_manifest(
                ipts=args.ipts,
                campaign_identifier=args.campaign,
                run_number=args.run_number,
                shared_root=args.shared_root,
                assembly_type=args.assembly_type,
                seemeta=seemeta,
                method_preferences=method_preferences,
            )
            # Reconstruct a fake report for display from the manifest.
            report = generate_requirement_report_for_run(
                ipts=args.ipts,
                campaign_identifier=args.campaign,
                run_number=args.run_number,
                shared_root=args.shared_root,
                assembly_type=result["assembly_type"],
                persist=False,
            )
            _print_report(report, selected_artefacts=result["selected_artefacts"])
            print(f"Manifest written → {result['manifest_path']}", file=sys.stderr)
        else:
            report = generate_requirement_report_for_run(
                ipts=args.ipts,
                campaign_identifier=args.campaign,
                run_number=args.run_number,
                shared_root=args.shared_root,
                assembly_type=args.assembly_type,
                seemeta=seemeta,
                method_preferences=method_preferences,
                persist=False,
            )

            # Compute selection without writing.
            try:
                campaign_slug = resolve_campaign_slug(
                    ipts=args.ipts,
                    campaign_identifier=args.campaign,
                    shared_root=args.shared_root,
                )
                paths = _resolve_paths(args.ipts, campaign_slug, args.shared_root)
                artefact_records = read_jsonl_records(paths.artefacts_index)
            except Exception:
                artefact_records = []

            by_type: dict[str, list[dict]] = {}
            for rec in artefact_records:
                if str(rec.get("status", "")) != "active":
                    continue
                atype = str(rec.get("artefact_type", ""))
                rc = rec.get("run_context", {})
                if isinstance(rc, dict):
                    rc_run = rc.get("run_number")
                    if isinstance(rc_run, int) and rc_run != args.run_number:
                        continue
                by_type.setdefault(atype, []).append(rec)

            selected: list[dict] = []
            for req in report["requirements"]:
                candidates = by_type.get(req["artefact_type"], [])
                chosen = next(
                    (c for c in reversed(candidates) if c.get("method") == req["preferred_method"]),
                    candidates[-1] if candidates else None,
                )
                if chosen:
                    selected.append({
                        "artefact_id": chosen.get("artefact_id", ""),
                        "artefact_type": req["artefact_type"],
                        "version": int(chosen.get("version", 1)),
                        "method": str(chosen.get("method", "")),
                        "path": str(chosen.get("path", "")),
                    })

            _print_report(report, selected_artefacts=selected)

    except (ValueError, FileNotFoundError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
