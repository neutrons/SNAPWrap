"""Persistence helpers for reduction artefacts Phase 1.

This module provides a minimal campaign bootstrap workflow and JSONL helpers
that validate records against packaged JSON schemas.
"""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import fcntl
from jsonschema import Draft202012Validator

from .schema_paths import get_schema_path

_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")
_RESERVED_SLUGS = {"cache", "_state"}


class SlugConflictError(ValueError):
    """Raised when a campaign slug is already in use or invalid."""


@dataclass(frozen=True)
class CampaignPaths:
    """Resolved campaign paths under an IPTS reduction artefacts root."""

    root: Path
    state_path: Path
    campaigns_dir: Path
    campaign_dir: Path
    campaign_json: Path
    runs_index: Path
    assets_index: Path
    artefacts_index: Path
    crystal_species_index: Path


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


@contextmanager
def _exclusive_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _reduction_artefacts_root(ipts: int, shared_root: Path | str | None) -> Path:
    if shared_root is None:
        shared = Path(f"/SNS/SNAP/IPTS-{ipts}/shared")
    else:
        shared = Path(shared_root)
    return shared / "snapwrap" / "reduction_artefacts"


def _resolve_paths(ipts: int, campaign_slug: str, shared_root: Path | str | None) -> CampaignPaths:
    root = _reduction_artefacts_root(ipts=ipts, shared_root=shared_root)
    campaigns_dir = root / "campaigns"
    campaign_dir = campaigns_dir / campaign_slug
    return CampaignPaths(
        root=root,
        state_path=root / "_state.json",
        campaigns_dir=campaigns_dir,
        campaign_dir=campaign_dir,
        campaign_json=campaign_dir / "campaign.json",
        runs_index=campaign_dir / "runs.jsonl",
        assets_index=campaign_dir / "assets_index.jsonl",
        artefacts_index=campaign_dir / "artefacts_index.jsonl",
        crystal_species_index=campaign_dir / "crystal_species_index.jsonl",
    )


def _validate_slug(slug: str) -> None:
    if slug in _RESERVED_SLUGS or slug.startswith("_"):
        raise SlugConflictError(f"Campaign slug is reserved: {slug!r}")
    if not _SLUG_PATTERN.fullmatch(slug):
        raise SlugConflictError(
            "Campaign slug must match ^[a-z0-9][a-z0-9_-]{1,62}$ "
            f"(received {slug!r})"
        )


@lru_cache(maxsize=16)
def _schema_validator(schema_name: str) -> Draft202012Validator:
    schema_path = get_schema_path(schema_name)
    with schema_path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    return Draft202012Validator(schema)


def validate_record(record: dict[str, Any], schema_name: str) -> None:
    """Validate a record against one of the packaged schemas.

    Args:
        record: JSON-compatible record payload.
        schema_name: Schema file name (for example
            ``asset_record.schema.json``).
    """
    _schema_validator(schema_name).validate(record)


def append_jsonl_record(
    index_path: Path | str,
    record: dict[str, Any],
    *,
    schema_name: str | None = None,
) -> None:
    """Append a single record to a JSONL file (optionally schema-validated)."""
    if schema_name is not None:
        validate_record(record, schema_name)

    path = Path(index_path)
    lock_path = path.with_suffix(path.suffix + ".lock")
    line = json.dumps(record, separators=(",", ":"))
    if len(line.encode("utf-8")) > 4096:
        raise ValueError("JSONL record exceeds 4 KiB write bound")

    with _exclusive_lock(lock_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())


def read_jsonl_records(index_path: Path | str) -> list[dict[str, Any]]:
    """Read a JSONL file into a list of records.

    Blank lines are ignored. If a line cannot be parsed as JSON, a ValueError
    is raised with line-number context.
    """
    path = Path(index_path)
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed JSONL at {path}:{line_no}: {exc.msg}") from exc
            if not isinstance(parsed, dict):
                raise ValueError(f"Expected object at {path}:{line_no}, got {type(parsed).__name__}")
            records.append(parsed)
    return records


def validate_jsonl_file(index_path: Path | str, schema_name: str) -> list[str]:
    """Return validation errors for a JSONL file (empty list means valid)."""
    path = Path(index_path)
    if not path.exists():
        return []

    validator = _schema_validator(schema_name)
    errors: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                errors.append(f"line {line_no}: malformed JSON ({exc.msg})")
                continue

            if not isinstance(parsed, dict):
                errors.append(f"line {line_no}: expected object, got {type(parsed).__name__}")
                continue

            for err in validator.iter_errors(parsed):
                loc = "/".join(str(p) for p in err.path) or "<root>"
                errors.append(f"line {line_no} ({loc}): {err.message}")
    return errors


def resolve_campaign_slug(
    *,
    ipts: int,
    campaign_identifier: int | str,
    shared_root: Path | str | None = None,
) -> str:
    """Resolve a campaign slug by id, canonical slug, or alias.

    Lookup precedence follows the planning contract:
    1) numeric ``campaign_id``
    2) exact ``campaign_slug``
    3) ``aliases`` mapping in ``_state.json``
    """
    if ipts < 1:
        raise ValueError("ipts must be >= 1")

    state_path = _reduction_artefacts_root(ipts=ipts, shared_root=shared_root) / "_state.json"
    if not state_path.exists():
        raise KeyError(f"State file does not exist: {state_path}")

    with state_path.open("r", encoding="utf-8") as handle:
        state = json.load(handle)

    campaigns = state.get("campaigns", {})
    aliases = state.get("aliases", {})

    resolved_id: int | None = None
    if isinstance(campaign_identifier, int):
        resolved_id = campaign_identifier
    elif isinstance(campaign_identifier, str):
        text = campaign_identifier.strip()
        if text.isdigit():
            resolved_id = int(text)

    if resolved_id is not None:
        for slug, rec in campaigns.items():
            if int(rec.get("campaign_id", -1)) == resolved_id:
                return slug
        raise KeyError(f"Unknown campaign_id: {resolved_id}")

    ident = str(campaign_identifier)
    if ident in campaigns:
        return ident

    target = aliases.get(ident)
    if target is not None:
        if target in campaigns:
            return target
        raise KeyError(f"Alias {ident!r} points to missing campaign slug {target!r}")

    raise KeyError(f"Unknown campaign identifier: {campaign_identifier!r}")


def rename_campaign_slug(
    *,
    ipts: int,
    old_slug: str,
    new_slug: str,
    shared_root: Path | str | None = None,
) -> dict[str, Any]:
    """Rename a campaign slug while preserving backwards lookup through aliases."""
    if ipts < 1:
        raise ValueError("ipts must be >= 1")

    _validate_slug(new_slug)

    root = _reduction_artefacts_root(ipts=ipts, shared_root=shared_root)
    state_path = root / "_state.json"
    state_lock = state_path.with_suffix(state_path.suffix + ".lock")
    campaigns_dir = root / "campaigns"

    with _exclusive_lock(state_lock):
        if not state_path.exists():
            raise KeyError(f"State file does not exist: {state_path}")

        with state_path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)

        if state.get("ipts") != ipts:
            raise ValueError(
                f"State file IPTS mismatch: expected {ipts}, found {state.get('ipts')}"
            )

        campaigns = state.setdefault("campaigns", {})
        aliases = state.setdefault("aliases", {})

        resolved_old = old_slug
        if resolved_old not in campaigns:
            alias_target = aliases.get(resolved_old)
            if alias_target is not None and alias_target in campaigns:
                resolved_old = alias_target
            else:
                raise KeyError(f"Unknown campaign slug: {old_slug!r}")

        if resolved_old == new_slug:
            rec = campaigns[resolved_old]
            return {
                "renamed": False,
                "campaign_slug": resolved_old,
                "campaign_id": rec["campaign_id"],
            }

        if new_slug in campaigns:
            raise SlugConflictError(f"Campaign slug already exists: {new_slug!r}")
        if new_slug in aliases:
            raise SlugConflictError(f"Campaign slug collides with existing alias: {new_slug!r}")

        old_dir = campaigns_dir / resolved_old
        new_dir = campaigns_dir / new_slug
        if new_dir.exists():
            raise FileExistsError(f"Target campaign directory already exists: {new_dir}")

        rec = campaigns.pop(resolved_old)
        campaigns[new_slug] = rec

        aliases[resolved_old] = new_slug
        if old_slug != resolved_old:
            aliases[old_slug] = new_slug

        for alias_key, alias_target in list(aliases.items()):
            if alias_target == resolved_old:
                aliases[alias_key] = new_slug

        _atomic_write_json(state_path, state)

        if old_dir.exists():
            old_dir.rename(new_dir)

        campaign_json = new_dir / "campaign.json"
        if campaign_json.exists():
            with campaign_json.open("r", encoding="utf-8") as handle:
                campaign_data = json.load(handle)
            campaign_data["campaign_slug"] = new_slug
            campaign_data["updated_at"] = _utc_now_iso()
            validate_record(campaign_data, "campaign.schema.json")
            _atomic_write_json(campaign_json, campaign_data)

    return {
        "renamed": True,
        "old_slug": resolved_old,
        "campaign_slug": new_slug,
        "campaign_id": rec["campaign_id"],
    }


def bootstrap_campaign(
    *,
    ipts: int,
    campaign_slug: str,
    assembly_type: str,
    shared_root: Path | str | None = None,
    description: str | None = None,
    owners: list[str] | None = None,
    schema_version: str = "0.1.0",
) -> dict[str, Any]:
    """Create a new campaign and initialize persistence files.

    This function implements the Phase 1 bootstrap algorithm from the planning
    document with a `_state.json` allocator and append-only index skeleton.
    """
    if ipts < 1:
        raise ValueError("ipts must be >= 1")

    _validate_slug(campaign_slug)
    paths = _resolve_paths(ipts=ipts, campaign_slug=campaign_slug, shared_root=shared_root)
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.campaigns_dir.mkdir(parents=True, exist_ok=True)

    state_lock = paths.state_path.with_suffix(paths.state_path.suffix + ".lock")
    now = _utc_now_iso()

    with _exclusive_lock(state_lock):
        if paths.state_path.exists():
            with paths.state_path.open("r", encoding="utf-8") as handle:
                state = json.load(handle)
        else:
            state = {
                "schema_version": schema_version,
                "ipts": ipts,
                "next_campaign_id": 1,
                "campaigns": {},
                "aliases": {},
            }

        if state.get("ipts") != ipts:
            raise ValueError(
                f"State file IPTS mismatch: expected {ipts}, found {state.get('ipts')}"
            )

        campaigns = state.setdefault("campaigns", {})
        aliases = state.setdefault("aliases", {})
        if campaign_slug in campaigns or campaign_slug in aliases:
            raise SlugConflictError(f"Campaign slug already exists: {campaign_slug!r}")

        campaign_id = int(state.get("next_campaign_id", 1))
        state["next_campaign_id"] = campaign_id + 1
        campaigns[campaign_slug] = {
            "campaign_id": campaign_id,
            "created_at": now,
            "status": "active",
        }
        _atomic_write_json(paths.state_path, state)

    if paths.campaign_dir.exists():
        raise FileExistsError(f"Campaign directory already exists: {paths.campaign_dir}")
    paths.campaign_dir.mkdir(parents=True, exist_ok=False)
    (paths.campaign_dir / "manifests").mkdir()
    (paths.campaign_dir / "assets").mkdir()
    (paths.campaign_dir / "artefacts").mkdir()
    (paths.campaign_dir / "logs").mkdir()

    campaign_record: dict[str, Any] = {
        "campaign_id": campaign_id,
        "campaign_slug": campaign_slug,
        "ipts": ipts,
        "assembly_type": assembly_type,
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "schema_version": schema_version,
    }
    if description:
        campaign_record["description"] = description
    if owners:
        campaign_record["owners"] = owners

    validate_record(campaign_record, "campaign.schema.json")
    _atomic_write_json(paths.campaign_json, campaign_record)

    for index_path in (paths.runs_index, paths.assets_index, paths.artefacts_index):
        index_path.touch(exist_ok=True)

    return campaign_record


def register_asset_record(
    *,
    ipts: int,
    campaign_identifier: int | str,
    asset_id: str,
    asset_type: str,
    path: str,
    shared_root: Path | str | None = None,
    applicability_scope: str = "campaign",
    run_number: int | None = None,
    version: int = 1,
    status: str = "active",
    checksum: str | None = None,
    metadata: dict[str, Any] | None = None,
    provenance_source: str = "manual",
    created_by: str = "operator",
    notes: str | None = None,
) -> dict[str, Any]:
    """Register a single asset record in a campaign ``assets_index.jsonl``.

    This is the minimal Phase 3 ingestion primitive used to persist campaign or
    run-scoped assets while preserving append-only history.
    """
    if ipts < 1:
        raise ValueError("ipts must be >= 1")
    if not asset_id.strip():
        raise ValueError("asset_id must be non-empty")
    if not path.strip():
        raise ValueError("path must be non-empty")

    campaign_slug = resolve_campaign_slug(
        ipts=ipts,
        campaign_identifier=campaign_identifier,
        shared_root=shared_root,
    )
    paths = _resolve_paths(ipts=ipts, campaign_slug=campaign_slug, shared_root=shared_root)

    if not paths.campaign_json.exists():
        raise FileNotFoundError(f"Missing campaign.json: {paths.campaign_json}")

    with paths.campaign_json.open("r", encoding="utf-8") as handle:
        campaign = json.load(handle)

    campaign_id = int(campaign.get("campaign_id", 0))
    if campaign_id < 1:
        raise ValueError(f"Invalid campaign_id in {paths.campaign_json}")

    record: dict[str, Any] = {
        "record_id": f"asset-{asset_id}-v{version}-{_utc_now_iso()}",
        "timestamp": _utc_now_iso(),
        "campaign_id": campaign_id,
        "campaign_slug": campaign_slug,
        "ipts": ipts,
        "asset_id": asset_id,
        "asset_type": asset_type,
        "version": version,
        "status": status,
        "applicability": {
            "scope": applicability_scope,
            "run_number": run_number if applicability_scope == "run" else None,
        },
        "path": path,
        "provenance": {
            "source": provenance_source,
            "created_by": created_by,
        },
    }
    if checksum:
        record["checksum"] = checksum
    if notes:
        record["provenance"]["notes"] = notes
    if metadata is not None:
        record["metadata"] = metadata

    append_jsonl_record(
        paths.assets_index,
        record,
        schema_name="asset_record.schema.json",
    )
    return record


def list_asset_records(
    *,
    ipts: int,
    campaign_identifier: int | str,
    shared_root: Path | str | None = None,
    asset_type: str | None = None,
    status: str | None = None,
    run_number: int | None = None,
) -> list[dict[str, Any]]:
    """List persisted asset records for a campaign with optional filters."""
    if ipts < 1:
        raise ValueError("ipts must be >= 1")

    campaign_slug = resolve_campaign_slug(
        ipts=ipts,
        campaign_identifier=campaign_identifier,
        shared_root=shared_root,
    )
    paths = _resolve_paths(ipts=ipts, campaign_slug=campaign_slug, shared_root=shared_root)
    records = read_jsonl_records(paths.assets_index)

    filtered: list[dict[str, Any]] = []
    for row in records:
        if asset_type is not None and row.get("asset_type") != asset_type:
            continue
        if status is not None and row.get("status") != status:
            continue
        if run_number is not None:
            applicability = row.get("applicability")
            if not isinstance(applicability, dict):
                continue
            if applicability.get("scope") != "run":
                continue
            if applicability.get("run_number") != run_number:
                continue
        filtered.append(row)
    return filtered


def register_crystal_species_artefact(
    *,
    ipts: int,
    campaign_identifier: int | str,
    species_name: str,
    cif_path: str | None,
    role: str = "sample",
    eos_path: str | None = None,
    source_run: int | None = None,
    refined_a: float | None = None,
    refined_b: float | None = None,
    refined_c: float | None = None,
    refined_pressure_gpa: float | None = None,
    unitCell_updated: bool = False,
    cif_asset_id: str | None = None,
    eos_asset_id: str | None = None,
    shared_root: Path | str | None = None,
) -> dict[str, Any]:
    """Append a ``crystalSpecies`` artefact record to the campaign index.

    Each call appends one line to
    ``<campaign_dir>/crystal_species_index.jsonl``.  The index is
    append-only: records are never deleted or modified in place.

    Args:
        ipts: IPTS experiment number.
        campaign_identifier: Campaign id (int) or slug (str).
        species_name: Human-readable species name (e.g. ``"ice-VII"``).
        cif_path: Absolute or relative path to the source CIF file.
        role: ``"sample"`` or ``"calibrant"`` (passed through from the
            ``crystalSpecies``).
        eos_path: Path to the EOS description JSON file, if any.
        source_run: Run number that triggered this build, if applicable.
        refined_a: Refined lattice parameter *a* in Å, if available.
        refined_b: Refined lattice parameter *b* in Å, if available.
        refined_c: Refined lattice parameter *c* in Å, if available.
        refined_pressure_gpa: Pressure used/recovered during refinement (GPa).
        unitCell_updated: Whether ``refine()`` updated the unit cell.
        cif_asset_id: ``asset_id`` of the CIF asset record, for cross-linking.
        eos_asset_id: ``asset_id`` of the EOS asset record, for cross-linking.
        shared_root: Override for the IPTS shared root (useful in tests).

    Returns:
        The dict appended to ``crystal_species_index.jsonl``.
    """
    if ipts < 1:
        raise ValueError("ipts must be >= 1")
    if not species_name.strip():
        raise ValueError("species_name must be non-empty")

    campaign_slug = resolve_campaign_slug(
        ipts=ipts,
        campaign_identifier=campaign_identifier,
        shared_root=shared_root,
    )
    paths = _resolve_paths(ipts=ipts, campaign_slug=campaign_slug, shared_root=shared_root)

    if not paths.campaign_json.exists():
        raise FileNotFoundError(f"Missing campaign.json: {paths.campaign_json}")

    with paths.campaign_json.open("r", encoding="utf-8") as handle:
        campaign = json.load(handle)

    campaign_id = int(campaign.get("campaign_id", 0))
    if campaign_id < 1:
        raise ValueError(f"Invalid campaign_id in {paths.campaign_json}")

    now = _utc_now_iso()
    record: dict[str, Any] = {
        "record_id": f"cs-{species_name}-{now}",
        "timestamp": now,
        "campaign_id": campaign_id,
        "campaign_slug": campaign_slug,
        "ipts": ipts,
        "species_name": species_name,
        "role": role,
        "cifPath": cif_path,
        "eosPath": eos_path,
        "source_run": source_run,
        "refined_a": refined_a,
        "refined_b": refined_b,
        "refined_c": refined_c,
        "refinedPressure_GPa": refined_pressure_gpa,
        "unitCell_updated": unitCell_updated,
    }
    if cif_asset_id is not None:
        record["cif_asset_id"] = cif_asset_id
    if eos_asset_id is not None:
        record["eos_asset_id"] = eos_asset_id

    append_jsonl_record(paths.crystal_species_index, record)
    return record


def list_crystal_species_records(
    *,
    ipts: int,
    campaign_identifier: int | str,
    shared_root: Path | str | None = None,
    role: str | None = None,
    source_run: int | None = None,
) -> list[dict[str, Any]]:
    """Return crystal species index records for a campaign, with optional filters."""
    if ipts < 1:
        raise ValueError("ipts must be >= 1")

    campaign_slug = resolve_campaign_slug(
        ipts=ipts,
        campaign_identifier=campaign_identifier,
        shared_root=shared_root,
    )
    paths = _resolve_paths(ipts=ipts, campaign_slug=campaign_slug, shared_root=shared_root)
    records = read_jsonl_records(paths.crystal_species_index)

    filtered: list[dict[str, Any]] = []
    for row in records:
        if role is not None and row.get("role") != role:
            continue
        if source_run is not None and row.get("source_run") != source_run:
            continue
        filtered.append(row)
    return filtered
    return filtered
