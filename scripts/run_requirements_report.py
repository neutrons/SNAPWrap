#!/usr/bin/env python
"""Generate Phase 2 requirement reports for one or more runs.

This script is intended for real-IPTS shadow testing where operators want to
evaluate missing/available artefacts without triggering full reduction.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from snapwrap.reduction_artefacts import generate_requirement_report_for_run


def _parse_method_preferences(values: list[str]) -> dict[str, str | list[str]]:
    preferences: dict[str, str | list[str]] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(
                f"Invalid --method-preference value {item!r}; expected artefact=method[,fallback...]"
            )
        artefact, methods = item.split("=", 1)
        artefact = artefact.strip()
        method_candidates = [m.strip() for m in methods.split(",") if m.strip()]
        if not artefact or not method_candidates:
            raise ValueError(
                f"Invalid --method-preference value {item!r}; expected artefact=method[,fallback...]"
            )
        if len(method_candidates) == 1:
            preferences[artefact] = method_candidates[0]
        else:
            preferences[artefact] = method_candidates
    return preferences


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate reduction artefact requirement reports")
    parser.add_argument("--ipts", required=True, type=int, help="IPTS number")
    parser.add_argument(
        "--campaign",
        required=True,
        help="Campaign identifier (slug or numeric campaign_id)",
    )
    parser.add_argument(
        "--run",
        dest="runs",
        type=int,
        action="append",
        required=True,
        help="Run number; may be provided multiple times",
    )
    parser.add_argument(
        "--shared-root",
        default=None,
        help="Override IPTS shared root path (defaults to /SNS/SNAP/IPTS-<ipts>/shared)",
    )
    parser.add_argument("--assembly-type", default=None, help="Override assembly type (DAC/PE/OTHER)")
    parser.add_argument("--seemeta-json", default=None, help="Optional path to SEEMeta JSON")
    parser.add_argument(
        "--artefacts-index",
        default=None,
        help="Optional path to artefacts_index.jsonl override",
    )
    parser.add_argument(
        "--method-preference",
        action="append",
        default=[],
        help="Artefact method preference, e.g. bin_mask=bin_mask.from_transmission,bin_mask.from_ub_pair",
    )
    parser.add_argument("--state-id", default=None, help="Optional state id to include in reports")
    parser.add_argument(
        "--strict-seemeta",
        action="store_true",
        help="Require full SEEMeta (provided or auto-acquired) for every run",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not persist manifest files")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    return parser


def _load_json(path: str | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload_path = Path(path)
    with payload_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"SEEMeta JSON must contain an object at root: {payload_path}")
    return data


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    method_preferences = _parse_method_preferences(args.method_preference)
    seemeta = _load_json(args.seemeta_json)

    reports: list[dict[str, Any]] = []
    try:
        for run_number in sorted(set(args.runs)):
            report = generate_requirement_report_for_run(
                ipts=args.ipts,
                campaign_identifier=args.campaign,
                run_number=run_number,
                shared_root=args.shared_root,
                assembly_type=args.assembly_type,
                seemeta=seemeta,
                state_id=args.state_id,
                method_preferences=method_preferences or None,
                artefacts_index_path=args.artefacts_index,
                require_seemeta=args.strict_seemeta,
                persist=not args.dry_run,
            )
            reports.append(report)
    except Exception as exc:
        print(f"ERROR: {exc}")
        print(
            "Hint: assembly can be auto-acquired from SEEMeta.utils.acquireMeta(run) "
            "(using seeDict['type']). You may also provide --assembly-type or --seemeta-json, "
            "and optionally --artefacts-index."
        )
        return 2

    if args.json:
        print(json.dumps({"reports": reports}, indent=2))
        return 0

    for report in reports:
        summary = report["summary"]
        print(
            f"run={report['run_number']} campaign={report['campaign_slug']} "
            f"assembly={report['assembly_type']} ready={summary['ready']} "
            f"missing_required={summary['missing_required']}"
        )
        if report.get("report_path"):
            print(f"  report: {report['report_path']}")

        missing = [r for r in report["requirements"] if r["missing"]]
        if missing:
            print("  missing:")
            for row in missing:
                print(
                    f"    - {row['artefact_type']} (preferred={row['preferred_method']}, "
                    f"allowed={','.join(row['allowed_methods'])})"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
