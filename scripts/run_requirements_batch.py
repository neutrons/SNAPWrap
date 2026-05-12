#!/usr/bin/env python
"""Generate requirement reports from campaign dictionary specs.

This script is intended for real-IPTS shadow pilots where operators keep a
Python template containing campaign dictionaries and run lists.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import importlib.util
import json
from pathlib import Path
from typing import Any

from snapwrap.reduction_artefacts import (
    generate_requirement_reports_from_campaign_specs,
    preflight_campaign_specs_seemeta,
)


def _load_campaign_specs(module_path: Path, variable: str) -> list[dict[str, Any]]:
    spec = importlib.util.spec_from_file_location("campaign_specs_module", module_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Could not load python module from {module_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    payload = getattr(module, variable, None)
    if payload is None:
        raise ValueError(f"Variable {variable!r} not found in {module_path}")
    if not isinstance(payload, list):
        raise ValueError(f"Variable {variable!r} must be a list of campaign dictionaries")
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate requirement reports from campaign specs")
    parser.add_argument("--ipts", required=True, type=int, help="IPTS number")
    parser.add_argument("--spec-module", required=True, help="Path to Python file containing campaign specs")
    parser.add_argument(
        "--spec-variable",
        default="CAMPAIGNS",
        help="Variable name containing campaign spec list (default: CAMPAIGNS)",
    )
    parser.add_argument(
        "--shared-root",
        default=None,
        help="Override shared root path (default /SNS/SNAP/IPTS-<ipts>/shared)",
    )
    parser.add_argument(
        "--strict-seemeta",
        action="store_true",
        help="Require full SEEMeta (provided or auto-acquired) for every run",
    )
    parser.add_argument(
        "--preflight-seemeta",
        action="store_true",
        help="Run SEEMeta coverage preflight before generating reports",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Run preflight and exit without generating requirement reports",
    )
    parser.add_argument("--persist", action="store_true", help="Persist reports under campaign manifests/")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary")
    parser.add_argument(
        "--no-missing-summary",
        action="store_true",
        help="Disable grouped missing-requirement summary",
    )
    return parser


def _print_grouped_missing_summary(reports: list[dict[str, Any]]) -> None:
    grouped: dict[str, dict[str, Any]] = {}

    for report in reports:
        campaign = str(report.get("campaign_slug", "unknown"))
        bucket = grouped.setdefault(
            campaign,
            {
                "runs": 0,
                "run_numbers": [],
                "missing_by_type": defaultdict(int),
            },
        )
        bucket["runs"] += 1
        bucket["run_numbers"].append(report.get("run_number"))

        requirements = report.get("requirements", [])
        if not isinstance(requirements, list):
            continue

        for req in requirements:
            if not isinstance(req, dict):
                continue
            if not req.get("missing", False):
                continue
            artefact_type = req.get("artefact_type")
            if isinstance(artefact_type, str) and artefact_type:
                bucket["missing_by_type"][artefact_type] += 1

    print("\nMissing required artefacts by campaign")
    for campaign in sorted(grouped):
        bucket = grouped[campaign]
        missing_by_type = bucket["missing_by_type"]
        if not missing_by_type:
            continue

        run_numbers = sorted(r for r in bucket["run_numbers"] if isinstance(r, int))
        run_preview = ",".join(str(r) for r in run_numbers[:6])
        if len(run_numbers) > 6:
            run_preview += ",..."

        print(f"- campaign={campaign} runs={bucket['runs']} run_preview=[{run_preview}]")
        for artefact_type, count in sorted(missing_by_type.items()):
            print(f"    - {artefact_type}: missing in {count}/{bucket['runs']} runs")


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        module_path = Path(args.spec_module).resolve()
        campaign_specs = _load_campaign_specs(module_path, args.spec_variable)

        if args.preflight_seemeta or args.preflight_only:
            rows = preflight_campaign_specs_seemeta(campaign_specs=campaign_specs)
            missing = [row for row in rows if not row["seemeta_present"]]
            print(f"SEEMeta preflight: {len(rows) - len(missing)}/{len(rows)} runs resolved")
            for row in missing:
                print(f"  missing: campaign={row['campaign']} run={row['run_number']}")

            if args.preflight_only:
                return 2 if (args.strict_seemeta and missing) else 0

            if args.strict_seemeta and missing:
                raise ValueError(
                    f"SEEMeta preflight failed for {len(missing)} run(s) with --strict-seemeta enabled"
                )

        reports = generate_requirement_reports_from_campaign_specs(
            ipts=args.ipts,
            campaign_specs=campaign_specs,
            shared_root=args.shared_root,
            require_seemeta=args.strict_seemeta,
            persist=args.persist,
        )
    except Exception as exc:
        print(f"ERROR: {exc}")
        print(
            "Hint: ensure your module defines CAMPAIGNS=[{campaign, runs:[...]}], "
            "and include assembly_type or per-run seemeta/seemeta_json when needed. "
            "If omitted, runtime falls back to SEEMeta.utils.acquireMeta(run)."
        )
        return 2

    if args.json:
        print(json.dumps({"reports": reports}, indent=2))
        return 0

    print(f"Generated {len(reports)} report(s)")
    for report in reports:
        summary = report["summary"]
        print(
            f"- campaign={report['campaign_slug']} run={report['run_number']} "
            f"assembly={report['assembly_type']} ready={summary['ready']} "
            f"missing_required={summary['missing_required']}"
        )
        if report.get("report_path"):
            print(f"  report: {report['report_path']}")

    if not args.no_missing_summary:
        _print_grouped_missing_summary(reports)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
