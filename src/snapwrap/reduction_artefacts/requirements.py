"""Phase 2 requirement resolution for reduction artefacts.

This module maps assembly context (typically from SEEMeta) to required
artefact types and emits a deterministic missing/available checklist per run.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .persistence import read_jsonl_records, resolve_campaign_slug

_REQUIREMENT_SPECS: dict[str, list[dict[str, Any]]] = {
    "DAC": [
        {
            "artefact_type": "bin_mask",
            "required": True,
            "intended_use": "pre_reduction",
            "allowed_methods": [
                "bin_mask.from_ub_pair",
                "bin_mask.from_transmission",
                "bin_mask.manual_import",
            ],
            "default_method": "bin_mask.from_ub_pair",
            "notes": "Primary masking artefact for DAC workflows.",
        },
        {
            "artefact_type": "crystal_box",
            "required": True,
            "intended_use": "pre_reduction",
            "allowed_methods": ["crystal_box.from_cif"],
            "default_method": "crystal_box.from_cif",
            "notes": "Derived from CIF, supports crystallographic modeling.",
        },
    ],
    "PE": [
        {
            "artefact_type": "attenuation_workspace",
            "required": True,
            "intended_use": "pre_reduction",
            "allowed_methods": ["attenuation.from_seemeta"],
            "default_method": "attenuation.from_seemeta",
            "notes": "Declared required; implementation may be planned/TODO.",
        },
        {
            "artefact_type": "pixel_mask",
            "required": True,
            "intended_use": "pre_reduction",
            "allowed_methods": ["pixel_mask.letterbox", "pixel_mask.custom"],
            "default_method": "pixel_mask.letterbox",
            "notes": "Standard letterbox mask or custom data-driven mask.",
        },
    ],
    "OTHER": [],
}


def normalize_assembly_type(raw: str) -> str:
    """Normalize user/SEEMeta assembly types to ``DAC``/``PE``/``OTHER``."""
    text = raw.strip().upper()
    tokenized = text.replace("-", "_").replace(".", "_")

    if text in {"DAC", "DIAMOND_ANVIL_CELL", "DIAMOND ANVIL CELL"}:
        return "DAC"
    if tokenized in {"ASSEMBLY_DAC", "DAC_CELL", "DAC_ASSEMBLY"}:
        return "DAC"

    if text in {"PE", "PARIS_EDINBURGH", "PARIS EDINBURGH", "PE_CELL", "PE CELL"}:
        return "PE"
    if tokenized in {"ASSEMBLY_PE", "PE_ASSEMBLY", "PARIS_EDINBURGH_CELL"}:
        return "PE"

    if text in {"OTHER", "UNKNOWN"}:
        return "OTHER"
    raise ValueError(f"Unsupported assembly type: {raw!r}")


def infer_assembly_type_from_seemeta(seemeta: Mapping[str, Any]) -> str:
    """Infer normalized assembly type from a SEEMeta-like mapping."""
    for key in ("assembly_type", "assembly", "sample_environment", "cell_type"):
        value = seemeta.get(key)
        if isinstance(value, str) and value.strip():
            return normalize_assembly_type(value)
    raise KeyError("SEEMeta does not include a recognizable assembly type field")


def get_requirement_specs(assembly_type: str) -> list[dict[str, Any]]:
    """Return requirement specs for a normalized assembly type.

    Returned list is sorted by ``artefact_type`` to ensure deterministic output.
    """
    normalized = normalize_assembly_type(assembly_type)
    specs = deepcopy(_REQUIREMENT_SPECS[normalized])
    specs.sort(key=lambda x: x["artefact_type"])
    return specs


def _choose_method(spec: Mapping[str, Any], method_preferences: Mapping[str, Any] | None) -> str:
    allowed = list(spec.get("allowed_methods", []))
    default_method = str(spec.get("default_method", ""))

    if method_preferences is None:
        return default_method

    preferred = method_preferences.get(spec["artefact_type"])
    if preferred is None:
        return default_method

    if isinstance(preferred, str):
        if preferred in allowed:
            return preferred
        return default_method

    if isinstance(preferred, list):
        for candidate in preferred:
            if candidate in allowed:
                return candidate
    return default_method


def _group_active_artefacts(
    artefact_records: list[Mapping[str, Any]],
    run_number: int | None,
) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)

    for record in artefact_records:
        if str(record.get("status", "")).lower() != "active":
            continue

        artefact_type = record.get("artefact_type")
        if not isinstance(artefact_type, str):
            continue

        # Prefer run-specific records when they match; otherwise campaign-wide.
        run_context = record.get("run_context")
        record_run: int | None = None
        if isinstance(run_context, Mapping):
            maybe_run = run_context.get("run_number")
            if isinstance(maybe_run, int):
                record_run = maybe_run

        if run_number is not None and record_run is not None and record_run != run_number:
            continue

        grouped[artefact_type].append(record)

    return grouped


def build_requirement_report(
    *,
    assembly_type: str,
    run_number: int | None = None,
    state_id: str | None = None,
    method_preferences: Mapping[str, Any] | None = None,
    artefact_records: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build deterministic required/missing checklist for an assembly/run.

    Args:
        assembly_type: Raw or normalized assembly type.
        run_number: Optional run number for run-specific record filtering.
        state_id: Optional state identifier echoed in output for traceability.
        method_preferences: Optional per-artefact method preference map.
        artefact_records: Optional artefact index records for availability checks.
    """
    normalized = normalize_assembly_type(assembly_type)
    specs = get_requirement_specs(normalized)
    grouped = _group_active_artefacts(artefact_records or [], run_number=run_number)

    requirements: list[dict[str, Any]] = []
    for spec in specs:
        artefact_type = spec["artefact_type"]
        active = grouped.get(artefact_type, [])
        selected_method = _choose_method(spec, method_preferences)

        requirement = {
            "artefact_type": artefact_type,
            "required": bool(spec.get("required", True)),
            "intended_use": spec.get("intended_use", "pre_reduction"),
            "allowed_methods": list(spec.get("allowed_methods", [])),
            "preferred_method": selected_method,
            "available": bool(active),
            "active_count": len(active),
            "active_ids": sorted(
                str(r.get("artefact_id", "")) for r in active if str(r.get("artefact_id", ""))
            ),
            "notes": str(spec.get("notes", "")),
        }
        requirement["missing"] = requirement["required"] and not requirement["available"]
        requirements.append(requirement)

    missing_required = [r for r in requirements if r["missing"]]
    available_required = [r for r in requirements if r["required"] and r["available"]]

    return {
        "assembly_type": normalized,
        "run_number": run_number,
        "state_id": state_id,
        "requirements": requirements,
        "summary": {
            "required_total": sum(1 for r in requirements if r["required"]),
            "available_required": len(available_required),
            "missing_required": len(missing_required),
            "ready": len(missing_required) == 0,
        },
    }


def build_requirement_report_from_seemeta(
    *,
    seemeta: Mapping[str, Any],
    run_number: int | None = None,
    state_id: str | None = None,
    method_preferences: Mapping[str, Any] | None = None,
    artefact_records: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Convenience wrapper: infer assembly from SEEMeta then build report."""
    assembly_type = infer_assembly_type_from_seemeta(seemeta)
    return build_requirement_report(
        assembly_type=assembly_type,
        run_number=run_number,
        state_id=state_id,
        method_preferences=method_preferences,
        artefact_records=artefact_records,
    )


def _reduction_artefacts_root(ipts: int, shared_root: Path | str | None) -> Path:
    if shared_root is None:
        shared = Path(f"/SNS/SNAP/IPTS-{ipts}/shared")
    else:
        shared = Path(shared_root)
    return shared / "snapwrap" / "reduction_artefacts"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _normalize_seemeta_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Normalize SEEMeta payload shape for assembly inference.

    SNAP SEEMeta commonly uses ``type`` for assembly information; this mirrors
    that into ``assembly_type`` when needed.
    """
    if "assembly_type" not in payload and isinstance(payload.get("type"), str):
        normalized = dict(payload)
        normalized["assembly_type"] = str(payload["type"])
        return normalized
    return payload


def _try_acquire_seemeta_from_run(run_number: int) -> Mapping[str, Any] | None:
    """Best-effort fallback using ``SEEMeta.utils.acquireMeta(run)``."""
    try:
        see_utils = importlib.import_module("snapwrap.SEEMeta.utils")
        acquire = getattr(see_utils, "acquireMeta", None)
        if acquire is None:
            return None
        payload = acquire(run_number)
        if isinstance(payload, Mapping):
            return _normalize_seemeta_payload(payload)
        return None
    except Exception:
        return None


def generate_requirement_report_for_run(
    *,
    ipts: int,
    campaign_identifier: int | str,
    run_number: int,
    shared_root: Path | str | None = None,
    assembly_type: str | None = None,
    seemeta: Mapping[str, Any] | None = None,
    state_id: str | None = None,
    method_preferences: Mapping[str, Any] | None = None,
    artefact_records: list[Mapping[str, Any]] | None = None,
    artefacts_index_path: Path | str | None = None,
    require_seemeta: bool = False,
    persist: bool = True,
) -> dict[str, Any]:
    """Generate (and optionally persist) a run-facing requirement report.

    This function wires Phase 2 resolution to on-disk campaign state so it can
    be used directly in real-IPTS shadow trials.
    """
    if ipts < 1:
        raise ValueError("ipts must be >= 1")
    if run_number < 1:
        raise ValueError("run_number must be >= 1")

    root = _reduction_artefacts_root(ipts=ipts, shared_root=shared_root)

    # Primary path: resolve from managed state. Fallback: ad-hoc dry-run mode.
    try:
        campaign_slug = resolve_campaign_slug(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            shared_root=shared_root,
        )
    except KeyError as exc:
        if persist:
            raise
        if isinstance(campaign_identifier, str) and not campaign_identifier.strip().isdigit():
            campaign_slug = campaign_identifier
        else:
            raise KeyError(
                "Cannot resolve campaign from numeric identifier without state file; "
                "for ad-hoc dry-run use a slug campaign identifier."
            ) from exc

    campaign_dir = root / "campaigns" / campaign_slug
    campaign_json = campaign_dir / "campaign.json"
    campaign: dict[str, Any] = {
        "campaign_id": None,
        "campaign_slug": campaign_slug,
        "ipts": ipts,
        "assembly_type": None,
    }
    if campaign_json.exists():
        with campaign_json.open("r", encoding="utf-8") as handle:
            loaded_campaign = json.load(handle)
        if isinstance(loaded_campaign, dict):
            campaign.update(loaded_campaign)
    elif persist:
        raise FileNotFoundError(f"Missing campaign.json: {campaign_json}")

    resolved_assembly = assembly_type

    # If caller did not provide assembly context, try live SEEMeta acquisition.
    if seemeta is None and resolved_assembly is None:
        seemeta = _try_acquire_seemeta_from_run(run_number)

    if isinstance(seemeta, Mapping):
        seemeta = _normalize_seemeta_payload(seemeta)

    if require_seemeta and seemeta is None:
        raise ValueError(
            "SEEMeta is required but could not be acquired. Provide --seemeta-json "
            "or ensure SEEMeta.utils.acquireMeta(run) returns metadata for this run."
        )

    if seemeta is not None:
        report = build_requirement_report_from_seemeta(
            seemeta=seemeta,
            run_number=run_number,
            state_id=state_id,
            method_preferences=method_preferences,
            artefact_records=artefact_records,
        )
        resolved_assembly = report["assembly_type"]
    else:
        if resolved_assembly is None:
            raw = campaign.get("assembly_type")
            if not isinstance(raw, str) or not raw.strip():
                raise ValueError(
                    "Assembly type is required for this report. Provide --assembly-type, "
                    "--seemeta-json, or use a campaign.json that includes assembly_type."
                )
            resolved_assembly = raw

        if artefact_records is None:
            if artefacts_index_path is not None:
                artefact_records = read_jsonl_records(artefacts_index_path)
            elif campaign_dir.exists():
                artefact_records = read_jsonl_records(campaign_dir / "artefacts_index.jsonl")
            else:
                artefact_records = []

        report = build_requirement_report(
            assembly_type=resolved_assembly,
            run_number=run_number,
            state_id=state_id,
            method_preferences=method_preferences,
            artefact_records=artefact_records,
        )

    report.update(
        {
            "ipts": ipts,
            "campaign_slug": campaign_slug,
            "campaign_id": campaign.get("campaign_id"),
            "generated_at": _utc_now_iso(),
            "report_schema_version": "0.1.0",
            "seemeta_present": seemeta is not None,
        }
    )

    manifest_path = campaign_dir / "manifests" / f"requirements_run_{run_number}.json"
    report["report_path"] = str(manifest_path) if persist else None

    if persist:
        # Ensure the campaign manifest path exists before persisting.
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(manifest_path, report)

    return report


def _load_seemeta_payload(value: Any) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return _normalize_seemeta_payload(value)
    if isinstance(value, str):
        path = Path(value)
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, Mapping):
            raise ValueError(f"SEEMeta JSON root must be object: {path}")
        return _normalize_seemeta_payload(payload)
    raise ValueError(f"Unsupported seemeta payload type: {type(value).__name__}")


def generate_requirement_reports_from_campaign_specs(
    *,
    ipts: int,
    campaign_specs: list[Mapping[str, Any]],
    shared_root: Path | str | None = None,
    require_seemeta: bool = False,
    persist: bool = False,
) -> list[dict[str, Any]]:
    """Generate reports from operator-defined campaign dictionaries.

    Expected campaign spec shape (flexible):
      {
        "campaign": "dac_fe_01",            # or "campaign_identifier"
        "assembly_type": "DAC",            # optional campaign default
        "state_id": "s-01",                # optional campaign default
        "method_preferences": {...},         # optional campaign default
        "runs": [
          1234,
          {"run": 1235, "seemeta_json": "/path/seemeta_1235.json"},
          {"run_number": 1236, "seemeta": {...}, "assembly_type": "PE"}
        ]
      }
    """
    reports: list[dict[str, Any]] = []

    for campaign in campaign_specs:
        campaign_identifier = campaign.get("campaign_identifier", campaign.get("campaign"))
        if campaign_identifier is None:
            raise ValueError("Campaign spec is missing campaign identifier ('campaign' or 'campaign_identifier')")

        campaign_assembly = campaign.get("assembly_type")
        campaign_state_id = campaign.get("state_id")
        campaign_methods = campaign.get("method_preferences")
        runs = campaign.get("runs", [])
        if not isinstance(runs, list):
            raise ValueError("Campaign spec field 'runs' must be a list")

        for run_item in runs:
            if isinstance(run_item, int):
                run_number = run_item
                seemeta_payload = None
                run_assembly = campaign_assembly
                run_state_id = campaign_state_id
                run_methods = campaign_methods
            elif isinstance(run_item, Mapping):
                run_number = run_item.get("run_number", run_item.get("run"))
                if not isinstance(run_number, int):
                    raise ValueError("Run entry must include integer 'run' or 'run_number'")

                run_assembly = run_item.get("assembly_type", campaign_assembly)
                run_state_id = run_item.get("state_id", campaign_state_id)

                run_methods = campaign_methods
                if "method_preferences" in run_item:
                    run_methods = run_item.get("method_preferences")

                seemeta_source = run_item.get("seemeta", run_item.get("seemeta_json"))
                seemeta_payload = _load_seemeta_payload(seemeta_source)
            else:
                raise ValueError(f"Unsupported run entry type: {type(run_item).__name__}")

            reports.append(
                generate_requirement_report_for_run(
                    ipts=ipts,
                    campaign_identifier=campaign_identifier,
                    run_number=run_number,
                    shared_root=shared_root,
                    assembly_type=run_assembly,
                    seemeta=seemeta_payload,
                    state_id=run_state_id,
                    method_preferences=run_methods,
                    require_seemeta=require_seemeta,
                    persist=persist,
                )
            )

    return reports


def preflight_campaign_specs_seemeta(
    *,
    campaign_specs: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Preflight check for SEEMeta coverage across campaign spec run lists.

    Returns one entry per run with whether SEEMeta is available and where it
    was sourced from (explicit payload/path or `acquireMeta` fallback).
    """
    rows: list[dict[str, Any]] = []

    for campaign in campaign_specs:
        campaign_identifier = campaign.get("campaign_identifier", campaign.get("campaign"))
        if campaign_identifier is None:
            raise ValueError("Campaign spec is missing campaign identifier ('campaign' or 'campaign_identifier')")

        runs = campaign.get("runs", [])
        if not isinstance(runs, list):
            raise ValueError("Campaign spec field 'runs' must be a list")

        for run_item in runs:
            if isinstance(run_item, int):
                run_number = run_item
                explicit_source = None
                payload = None
            elif isinstance(run_item, Mapping):
                run_number = run_item.get("run_number", run_item.get("run"))
                if not isinstance(run_number, int):
                    raise ValueError("Run entry must include integer 'run' or 'run_number'")
                explicit_source = run_item.get("seemeta_json") if "seemeta_json" in run_item else None
                payload = _load_seemeta_payload(run_item.get("seemeta", run_item.get("seemeta_json")))
            else:
                raise ValueError(f"Unsupported run entry type: {type(run_item).__name__}")

            source = "none"
            if payload is None:
                payload = _try_acquire_seemeta_from_run(run_number)
                if payload is not None:
                    source = "acquireMeta"
            else:
                source = "seemeta_json" if explicit_source is not None else "seemeta"

            assembly = None
            if isinstance(payload, Mapping):
                normalized = _normalize_seemeta_payload(payload)
                maybe_type = normalized.get("assembly_type")
                if isinstance(maybe_type, str):
                    assembly = maybe_type

            rows.append(
                {
                    "campaign": str(campaign_identifier),
                    "run_number": run_number,
                    "seemeta_present": payload is not None,
                    "source": source,
                    "assembly_type": assembly,
                }
            )

    return rows
