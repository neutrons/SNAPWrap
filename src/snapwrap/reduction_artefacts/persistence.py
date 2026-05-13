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
    assets_dir: Path          # managed asset store: root/assets/{asset_type}/
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
        assets_dir=root / "assets",
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


def copy_to_asset_store(
    src_path: str | Path,
    asset_type: str,
    *,
    ipts: int,
    shared_root: Path | str | None = None,
    overwrite: bool = False,
) -> Path:
    """Copy a file into the managed asset store and return its destination path.

    The destination is::

        <reduction_artefacts_root>/assets/<asset_type>/<filename>

    The function is idempotent when ``overwrite=False`` and the destination
    already exists with identical content (checked by size + mtime).  If the
    file already exists with **different** content, ``FileExistsError`` is
    raised unless ``overwrite=True``.

    Args:
        src_path: Source file to copy.
        asset_type: One of the :class:`~snapwrap.reduction_artefacts.assets.AssetType`
            string values (e.g. ``"ub_matrix"``, ``"cif"``).
        ipts: IPTS number (used to locate the shared root).
        shared_root: Override for the IPTS shared root (useful in tests).
        overwrite: If ``True``, overwrite an existing destination file.

    Returns:
        Absolute ``Path`` of the file inside the asset store.

    Raises:
        FileNotFoundError: If ``src_path`` does not exist.
        FileExistsError: If the destination exists with different content
            and ``overwrite=False``.
    """
    import shutil

    src = Path(src_path)
    if not src.exists():
        raise FileNotFoundError(f"Asset source not found: {src}")

    root = _reduction_artefacts_root(ipts=ipts, shared_root=shared_root)
    dest_dir = root / "assets" / asset_type
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name

    if dest.exists() and not overwrite:
        # Idempotent if same size and mtime — already copied.
        src_stat = src.stat()
        dst_stat = dest.stat()
        if src_stat.st_size == dst_stat.st_size and abs(src_stat.st_mtime - dst_stat.st_mtime) < 2:
            return dest
        raise FileExistsError(
            f"Asset already exists at {dest} with different content. "
            "Use overwrite=True to replace it."
        )

    tmp = dest.with_name(f".{dest.name}.tmp")
    shutil.copy2(src, tmp)
    os.replace(tmp, dest)
    return dest


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


def bootstrap_campaign_from_manifest(
    manifest_path: "str | Path",
    *,
    shared_root: "Path | str | None" = None,
    seemeta_dir: "Path | str | None" = None,
) -> dict[str, Any]:
    """Validate a campaign manifest, bootstrap the campaign, and register all assets.

    The manifest (v0.2.0 schema) is the **living document** for the campaign.
    After validation it is copied to ``campaigns/{slug}/manifest.json`` under
    the campaign root, where :func:`annotate_run` and
    :func:`add_candidate_species` will update it in-place over the campaign
    lifetime.

    Each ``candidate_species`` entry's CIF file is registered as a ``cif``
    asset in ``assets_index.jsonl``.  EOS parameters are embedded inline in the
    manifest and are not registered as separate assets.

    Each ``assembly_assets`` entry is registered in ``assets_index.jsonl``.

    Assembly type resolution order:

    1. ``manifest.campaign.assembly_type`` (explicit) — used directly.
    2. ``manifest.campaign.source_run`` — SEEMeta file
       ``{seemeta_dir}/SEE{source_run:06d}.json`` is loaded and
       :func:`infer_assembly_type_from_seemeta` is called.
    3. Neither present → ``ValueError``.

    When ``seemeta_dir`` is not supplied, defaults to
    ``/SNS/SNAP/IPTS-{ipts}/shared/SEE/``.

    Args:
        manifest_path: Path to the campaign manifest JSON file.
        shared_root: Override the IPTS shared root (used in tests).
        seemeta_dir: Override directory containing ``SEE*.json`` files.

    Returns:
        ``{"campaign": <campaign_record>,
           "candidate_species": [<per-species dict with cif_asset_record>],
           "assembly_assets": [<asset_records>],
           "manifest_path": "<absolute path to living manifest copy>"}``

    Raises:
        FileNotFoundError: Manifest file or SEEMeta file not found.
        jsonschema.ValidationError: Manifest fails schema validation.
        ValueError: Cannot determine assembly type.
        SlugConflictError: Campaign slug already in use.
    """
    from .requirements import infer_assembly_type_from_seemeta, normalize_assembly_type

    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Campaign manifest not found: {manifest_path}")

    with manifest_path.open("r", encoding="utf-8") as fh:
        manifest: dict[str, Any] = json.load(fh)

    validate_record(manifest, "campaign_manifest.schema.json")

    camp = manifest["campaign"]
    ipts: int = int(camp["ipts"])
    slug: str = camp["slug"]

    # ── Resolve assembly_type ────────────────────────────────────────────────
    if "assembly_type" in camp:
        assembly_type = normalize_assembly_type(camp["assembly_type"])
    elif "source_run" in camp:
        source_run_num: int = int(camp["source_run"])
        if seemeta_dir is None:
            see_dir = Path(f"/SNS/SNAP/IPTS-{ipts}/shared/SEE")
        else:
            see_dir = Path(seemeta_dir)
        see_file = see_dir / f"SEE{source_run_num:06d}.json"
        if not see_file.exists():
            raise FileNotFoundError(
                f"SEEMeta file not found for run {source_run_num}: {see_file}"
            )
        with see_file.open("r", encoding="utf-8") as fh:
            seemeta: dict[str, Any] = json.load(fh)
        assembly_type = infer_assembly_type_from_seemeta(seemeta)
    else:
        raise ValueError(
            f"Manifest for campaign {slug!r} must specify either "
            "'campaign.assembly_type' or 'campaign.source_run' (for SEEMeta inference)."
        )

    # ── Bootstrap the campaign directory structure ───────────────────────────
    campaign_record = bootstrap_campaign(
        ipts=ipts,
        campaign_slug=slug,
        assembly_type=assembly_type,
        shared_root=shared_root,
        description=camp.get("description"),
        owners=camp.get("owners"),
    )

    paths = _resolve_paths(ipts=ipts, campaign_slug=slug, shared_root=shared_root)
    living_manifest_path = paths.campaign_dir / "manifest.json"
    _atomic_write_json(living_manifest_path, manifest)

    # ── Register CIF assets for each candidate species ───────────────────────
    species_results: list[dict[str, Any]] = []
    for species in manifest.get("candidate_species", []):
        cif_asset_id = f"cif-{species['species_id']}"
        cif_record = register_asset_record(
            ipts=ipts,
            campaign_identifier=slug,
            asset_id=cif_asset_id,
            asset_type="cif",
            path=species["cif"],
            shared_root=shared_root,
            applicability_scope="campaign",
            provenance_source="imported",
            created_by=camp.get("owners", ["operator"])[0] if camp.get("owners") else "operator",
            notes=f"CIF for candidate species '{species['species_id']}'",
        )
        species_results.append({
            "species_id": species["species_id"],
            "role": species["role"],
            "cif_asset": cif_record,
        })

    # ── Register assembly assets ─────────────────────────────────────────────
    assembly_asset_records: list[dict[str, Any]] = []
    for asset_def in manifest.get("assembly_assets", []):
        applicability = asset_def.get("applicability", {})
        provenance = asset_def.get("provenance", {})
        record = register_asset_record(
            ipts=ipts,
            campaign_identifier=slug,
            asset_id=asset_def["asset_id"],
            asset_type=asset_def["asset_type"],
            path=asset_def["path"],
            shared_root=shared_root,
            applicability_scope=applicability.get("scope", "campaign"),
            run_number=applicability.get("run_number"),
            version=int(asset_def.get("version", 1)),
            metadata=asset_def.get("metadata"),
            provenance_source=provenance.get("source", "manual"),
            created_by=provenance.get("created_by", "operator"),
            notes=provenance.get("notes"),
        )
        assembly_asset_records.append(record)

    return {
        "campaign": campaign_record,
        "candidate_species": species_results,
        "assembly_assets": assembly_asset_records,
        "manifest_path": str(living_manifest_path),
    }


# ── Sentinel for annotate_run unset kwargs ────────────────────────────────────

class _UnsetType:
    """Sentinel distinguishing 'not supplied' from explicit None."""
    def __repr__(self) -> str:
        return "<UNSET>"


_UNSET: Any = _UnsetType()


def annotate_run(
    *,
    ipts: int,
    campaign_identifier: int | str,
    run_number: int,
    shared_root: "Path | str | None" = None,
    ruby_before_gpa: "float | None" = _UNSET,
    ruby_after_gpa: "float | None" = _UNSET,
    ruby_nominal_gpa: "float | None" = _UNSET,
    observed_species: "list[dict[str, Any]] | None" = _UNSET,
) -> dict[str, Any]:
    """Partially update a single run record in the campaign's living manifest.

    Only supplied keyword arguments are written; omitted arguments leave the
    existing values intact.  This allows real-time updates in three separate
    calls:

    1. Before shutter opens: ``annotate_run(..., ruby_before_gpa=3.1)``
    2. After shutter closes: ``annotate_run(..., ruby_after_gpa=3.15,
       ruby_nominal_gpa=3.1)``
    3. Post-analysis: ``annotate_run(..., observed_species=[...])``

    The ``ruby_pressure_gpa`` object is created on first write; subsequent
    calls merge into it.

    Args:
        ipts: IPTS number.
        campaign_identifier: Campaign slug, alias, or numeric id.
        run_number: The run number to annotate.
        shared_root: Override IPTS shared root (used in tests).
        ruby_before_gpa: Ruby pressure (GPa) before neutron collection.
        ruby_after_gpa: Ruby pressure (GPa) after neutron collection.
        ruby_nominal_gpa: The pressure treated as canonical downstream.
        observed_species: Post-analysis list of observed-species dicts.
            Each must have at least ``species_id``; optionally
            ``lattice_params``, ``pressure_gpa``, ``artefact_path``.

    Returns:
        The updated run dict.

    Raises:
        KeyError: ``run_number`` not found in ``manifest.runs``.
        FileNotFoundError: Living manifest not found in campaign directory.
    """
    if ipts < 1:
        raise ValueError("ipts must be >= 1")

    campaign_slug = resolve_campaign_slug(
        ipts=ipts, campaign_identifier=campaign_identifier, shared_root=shared_root
    )
    paths = _resolve_paths(ipts=ipts, campaign_slug=campaign_slug, shared_root=shared_root)
    manifest_path = paths.campaign_dir / "manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Living manifest not found: {manifest_path}. "
            "Was the campaign bootstrapped from a manifest?"
        )

    lock_path = manifest_path.with_suffix(".json.lock")
    with _exclusive_lock(lock_path):
        with manifest_path.open("r", encoding="utf-8") as fh:
            manifest = json.load(fh)

        runs: list[dict[str, Any]] = manifest.get("runs", [])
        run_idx = next(
            (i for i, r in enumerate(runs) if r.get("run_number") == run_number),
            None,
        )
        if run_idx is None:
            raise KeyError(
                f"run_number {run_number} not declared in manifest.runs for campaign {campaign_slug!r}"
            )

        run = runs[run_idx]

        # ── Merge ruby pressure fields ───────────────────────────────────────
        ruby_fields = {
            "before": ruby_before_gpa,
            "after": ruby_after_gpa,
            "nominal": ruby_nominal_gpa,
        }
        has_ruby_update = any(
            not isinstance(v, _UnsetType) for v in ruby_fields.values()
        )
        if has_ruby_update:
            existing_ruby = run.get("ruby_pressure_gpa") or {}
            if not isinstance(existing_ruby, dict):
                existing_ruby = {}
            for field, value in ruby_fields.items():
                if not isinstance(value, _UnsetType):
                    existing_ruby[field] = value
            run["ruby_pressure_gpa"] = existing_ruby

        # ── Replace observed_species wholesale ──────────────────────────────
        if not isinstance(observed_species, _UnsetType):
            run["observed_species"] = observed_species

        runs[run_idx] = run
        manifest["runs"] = runs
        _atomic_write_json(manifest_path, manifest)

    return run


def add_candidate_species(
    *,
    ipts: int,
    campaign_identifier: int | str,
    species_def: dict[str, Any],
    shared_root: "Path | str | None" = None,
) -> dict[str, Any]:
    """Add a newly-discovered candidate species to a campaign manifest mid-campaign.

    The species CIF is registered as a ``cif`` asset in ``assets_index.jsonl``.
    The manifest's ``candidate_species`` list is extended atomically.

    Args:
        ipts: IPTS number.
        campaign_identifier: Campaign slug, alias, or numeric id.
        species_def: Dict matching the ``candidate_species`` item schema.
            Must include ``species_id``, ``role``, and ``cif``.
        shared_root: Override IPTS shared root (used in tests).

    Returns:
        The registered CIF asset record.

    Raises:
        ValueError: ``species_id`` already exists in the manifest.
        KeyError: Required fields missing from ``species_def``.
        FileNotFoundError: Living manifest not found.
    """
    if ipts < 1:
        raise ValueError("ipts must be >= 1")
    for required in ("species_id", "role", "cif"):
        if required not in species_def:
            raise KeyError(f"species_def is missing required field: {required!r}")

    campaign_slug = resolve_campaign_slug(
        ipts=ipts, campaign_identifier=campaign_identifier, shared_root=shared_root
    )
    paths = _resolve_paths(ipts=ipts, campaign_slug=campaign_slug, shared_root=shared_root)
    manifest_path = paths.campaign_dir / "manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Living manifest not found: {manifest_path}. "
            "Was the campaign bootstrapped from a manifest?"
        )

    lock_path = manifest_path.with_suffix(".json.lock")
    with _exclusive_lock(lock_path):
        with manifest_path.open("r", encoding="utf-8") as fh:
            manifest = json.load(fh)

        existing_ids = {s["species_id"] for s in manifest.get("candidate_species", [])}
        new_id = species_def["species_id"]
        if new_id in existing_ids:
            raise ValueError(
                f"species_id {new_id!r} already exists in campaign {campaign_slug!r}"
            )

        # Ensure artefact_path defaults to null
        entry = {**species_def}
        entry.setdefault("artefact_path", None)
        entry.setdefault("stability_pressure", [None, None])

        manifest.setdefault("candidate_species", []).append(entry)
        _atomic_write_json(manifest_path, manifest)

    # Register the CIF asset outside the manifest lock (register_asset_record has its own lock)
    camp = manifest.get("campaign", {})
    cif_record = register_asset_record(
        ipts=ipts,
        campaign_identifier=campaign_slug,
        asset_id=f"cif-{new_id}",
        asset_type="cif",
        path=species_def["cif"],
        shared_root=shared_root,
        applicability_scope="campaign",
        provenance_source="manual",
        created_by=(camp.get("owners", ["operator"]) or ["operator"])[0],
        notes=f"CIF for candidate species '{new_id}' (added mid-campaign)",
    )
    return cif_record


def register_swiss_cheese_artefact(
    *,
    ipts: int,
    campaign_identifier: int | str,
    artefact_id: str,
    mask_json_path: str,
    source_run: int,
    ub_mat_paths: list[str],
    width_coef: list[float],
    is_lite: bool,
    shared_root: Path | str | None = None,
    version: int = 1,
    status: str = "active",
    notes: str | None = None,
    created_by: str = "operator",
) -> dict[str, Any]:
    """Register a DAC swiss-cheese bin-mask artefact in ``artefacts_index.jsonl``.

    Also registers each UB matrix ``.mat`` file as a ``ub_matrix`` asset
    record in ``assets_index.jsonl`` and cross-links them via
    ``input_asset_ids``.

    Args:
        ipts: IPTS experiment number.
        campaign_identifier: Campaign id (int) or slug (str).
        artefact_id: Unique identifier for this artefact, e.g.
            ``"dac_mask_bruciteA_run65891"``.
        mask_json_path: Absolute path to the saved swiss-cheese JSON file.
        source_run: Run number from which the UBs were determined.
        ub_mat_paths: Ordered list of absolute paths to the saved ISAW ``.mat``
            UB files.  These are registered as ``ub_matrix`` assets and their
            ``asset_id`` values appear as ``input_asset_ids`` in the artefact
            record.
        width_coef: Polynomial width coefficients used during mask build
            (stored in metadata for reproducibility).
        is_lite: Whether the mask targets Lite (18 432-pixel) mode.
        shared_root: Override for the IPTS shared root (useful in tests).
        version: Record version number (default 1).
        status: Artefact status (default ``"active"``).
        notes: Optional free-text notes stored in ``provenance``.
        created_by: Creator identifier (default ``"operator"``).

    Returns:
        The artefact record dict appended to ``artefacts_index.jsonl``.
    """
    if ipts < 1:
        raise ValueError("ipts must be >= 1")
    if not artefact_id.strip():
        raise ValueError("artefact_id must be non-empty")
    if not mask_json_path.strip():
        raise ValueError("mask_json_path must be non-empty")

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

    # ── Register each UB mat as a ub_matrix asset ─────────────────────────
    ub_asset_ids: list[str] = []
    for idx, ub_path in enumerate(ub_mat_paths, start=1):
        ub_asset_id = f"ub-{artefact_id}-{idx}"
        register_asset_record(
            ipts=ipts,
            campaign_identifier=campaign_slug,
            asset_id=ub_asset_id,
            asset_type="ub_matrix",
            path=ub_path,
            shared_root=shared_root,
            applicability_scope="run",
            run_number=source_run,
            version=version,
            status=status,
            provenance_source="generated",
            created_by=created_by,
            notes=notes,
            metadata={
                "source_run": source_run,
                "crystal_index": idx,
                "width_coef": width_coef,
                "is_lite": is_lite,
            },
        )
        ub_asset_ids.append(ub_asset_id)

    # ── Register the artefact ─────────────────────────────────────────────
    now = _utc_now_iso()
    record: dict[str, Any] = {
        "record_id": f"artefact-{artefact_id}-v{version}-{now}",
        "timestamp": now,
        "campaign_id": campaign_id,
        "campaign_slug": campaign_slug,
        "ipts": ipts,
        "artefact_id": artefact_id,
        "artefact_type": "bin_mask",
        "intended_use": "pre_reduction",
        "method": "swiss_cheese_ub",
        "version": version,
        "status": status,
        "run_context": {
            "run_number": source_run,
            "state_id": None,
        },
        "input_asset_ids": ub_asset_ids,
        "path": mask_json_path,
        "provenance": {
            "created_by": created_by,
            "tool": "snapwrap.reduction_artefacts.masking.build_swiss_cheese_from_run",
        },
        "metadata": {
            "width_coef": width_coef,
            "is_lite": is_lite,
            "n_diamonds": len(ub_mat_paths),
        },
    }
    if notes:
        record["provenance"]["notes"] = notes

    append_jsonl_record(
        paths.artefacts_index,
        record,
        schema_name="artefact_record.schema.json",
    )
    return record
