"""campaign_setup — library functions for spec-driven campaign setup.

Operators author a small JSON spec file (validated against
``campaign_setup_spec.schema.json``) that lives in their IPTS shared folder.
Calling :func:`setup_campaign_from_spec` reads that file and drives the full
bootstrap + ingestion sequence without requiring any bespoke Python scripts per
campaign.

A spec file is intentionally thin — it names files that already exist on disk
and declares metadata.  It does not contain any asset *content*.

Typical operator workflow::

    # 1.  Copy the template into the IPTS shared folder and edit it:
    #     /SNS/SNAP/IPTS-33219/shared/campaigns/brucite_a.json

    # 2.  Run from the repo root (or Mantid Workbench):
    #     python scripts/setup_campaign.py \\
    #         --spec /SNS/SNAP/IPTS-33219/shared/campaigns/brucite_a.json

    # 3.  Verify:
    #     python scripts/show_run_resolution.py \\
    #         --ipts 33219 --campaign dac_brucite_a --run 65891
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

#: Default sub-directory inside ``shared/`` for each asset type when the
#: operator supplies a bare filename (no ``/``).  Lets the spec be terse:
#: ``"path": "EntryWithCollCode43421.cif"`` resolves to
#: ``<shared>/cif/EntryWithCollCode43421.cif``.
ASSET_DEFAULT_SUBDIR: dict[str, str] = {
    "cif": "cif",
    "ub_matrix": "ub",
    "manual_pixel_mask": "masks",
    "seemeta_json": "SEE",
}


def _resolve_path(raw: str, shared_root: Path) -> Path:
    """Return an absolute Path, resolving *raw* relative to *shared_root*."""
    p = Path(raw)
    return p if p.is_absolute() else shared_root / p


def _resolve_asset_path(raw: str, shared_root: Path, asset_type: str) -> Path:
    """Resolve an asset path with type-aware default-folder fallback.

    Resolution order:

    1. If *raw* is absolute → use as-is.
    2. If *raw* contains a path separator (e.g. ``"cif/foo.cif"``) → resolve
       against *shared_root*.
    3. If *raw* is a bare filename → resolve against
       ``shared_root/{ASSET_DEFAULT_SUBDIR[asset_type]}/{raw}``.

    This lets operators write the terse form ``"path": "foo.cif"`` and have
    it picked up from the canonical ``shared/cif/`` location, while still
    accepting explicit relative or absolute paths when needed.
    """
    p = Path(raw)
    if p.is_absolute():
        return p
    if len(p.parts) > 1:
        return shared_root / p
    sub = ASSET_DEFAULT_SUBDIR.get(asset_type, "")
    return shared_root / sub / p if sub else shared_root / p


def _load_spec(spec_path_or_dict: dict[str, Any] | str | Path) -> dict[str, Any]:
    """Return spec as a dict, loading from disk when a path is supplied."""
    if isinstance(spec_path_or_dict, dict):
        return spec_path_or_dict
    p = Path(spec_path_or_dict)
    if not p.exists():
        raise FileNotFoundError(f"Spec file not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _validate_spec(spec: dict[str, Any]) -> None:
    """Validate *spec* against the campaign_setup_spec schema."""
    from .persistence import validate_record
    validate_record(spec, schema_name="campaign_setup_spec.schema.json")


# ── preflight ─────────────────────────────────────────────────────────────────

def preflight_spec(
    spec: dict[str, Any] | str | Path,
    shared_root: Path | str | None = None,
) -> list[str]:
    """Return a list of problems found in *spec* without writing anything.

    Problems include schema validation errors and missing source files.
    An empty list means the spec is ready to execute.

    Args:
        spec: Spec dict or path to a spec JSON file.
        shared_root: Override for the IPTS shared root.  Defaults to
            ``/SNS/SNAP/IPTS-<ipts>/shared``.

    Returns:
        List of human-readable problem strings (empty → all OK).
    """
    problems: list[str] = []

    try:
        spec_dict = _load_spec(spec)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return [str(exc)]

    try:
        _validate_spec(spec_dict)
    except Exception as exc:  # jsonschema.ValidationError
        problems.append(f"Schema validation: {exc}")

    ipts = spec_dict.get("ipts", 0)
    if shared_root is None:
        shared_root = Path(f"/SNS/SNAP/IPTS-{ipts}/shared")
    shared_root = Path(shared_root)

    for asset in spec_dict.get("assets", []):
        raw = asset.get("path", "")
        if raw:
            p = _resolve_asset_path(raw, shared_root, asset.get("asset_type", ""))
            if not p.exists():
                problems.append(f"Missing asset file: {p}")

    for bm in spec_dict.get("bin_masks", []):
        raw = bm.get("mask_path", "")
        if raw:
            p = _resolve_path(raw, shared_root)
            if not p.exists():
                problems.append(f"Missing bin_mask file: {p}")
        for ub_raw in bm.get("ub_mat_paths", []):
            p = _resolve_path(ub_raw, shared_root)
            if not p.exists():
                problems.append(f"Missing ub_mat file: {p}")

    for pm in spec_dict.get("pixel_masks", []):
        raw = pm.get("nxs_path", "")
        if raw:
            p = _resolve_path(raw, shared_root)
            if not p.exists():
                problems.append(f"Missing pixel_mask file: {p}")

    seemeta_dir_raw = spec_dict.get("seemeta_dir", "SEE")
    pattern = spec_dict.get("seemeta_filename_pattern", "SEE{run:06d}.json")
    if seemeta_dir_raw is not None:
        seemeta_dir = _resolve_path(seemeta_dir_raw, shared_root)
        for run in spec_dict.get("runs", []):
            try:
                fname = pattern.format(run=run)
            except (KeyError, ValueError) as exc:
                problems.append(
                    f"seemeta_filename_pattern {pattern!r} invalid for run {run}: {exc}"
                )
                continue
            p = seemeta_dir / fname
            if not p.exists():
                problems.append(f"Missing SEEMeta file: {p}")

    return problems


# ── main entry point ──────────────────────────────────────────────────────────

def setup_campaign_from_spec(
    spec: dict[str, Any] | str | Path,
    *,
    shared_root: Path | str | None = None,
    dry_run: bool = False,
    created_by: str = "operator",
    skip_preflight: bool = False,
) -> dict[str, Any]:
    """Bootstrap a campaign and ingest all assets described in *spec*.

    This is the single library entry point that replaces bespoke per-campaign
    Python scripts.  It:

    1. Loads and validates the spec.
    2. Runs a preflight check (all source files present).
    3. Bootstraps the campaign directory (idempotent).
    4. Ingests each asset listed under ``assets``.
    5. Ingests SEEMeta for every run in ``runs`` (auto-detected from
       ``seemeta_dir``).
    6. Registers each ``bin_mask`` artefact.
    7. Registers each ``pixel_mask`` artefact.
    8. Pre-declares each ``planned_attenuation`` artefact.

    Args:
        spec: Operator spec dict **or** path to a ``campaign_setup_spec.json``
            file.  Relative paths inside the spec are resolved against
            *shared_root*.
        shared_root: Override for the IPTS shared root.  Defaults to
            ``/SNS/SNAP/IPTS-<ipts>/shared`` (derived from ``ipts`` in spec).
        dry_run: When ``True``, validate and report without writing anything.
        created_by: Provenance author stored in all written records.
        skip_preflight: Skip file-existence checks (useful when spec paths
            are already absolute and validated externally).

    Returns:
        Summary dict with keys:
        - ``"campaign_slug"`` — the resolved slug
        - ``"assets_ingested"`` — list of asset record dicts
        - ``"artefacts_registered"`` — list of artefact record dicts
        - ``"problems"`` — list of non-fatal warning strings

    Raises:
        FileNotFoundError: Spec file not found.
        ValueError: Spec fails schema validation or a required source file
            is missing (and ``dry_run=False``).
    """
    from .persistence import (
        SlugConflictError,
        bootstrap_campaign,
        ingest_asset,
        ingest_seemeta_for_run,
        list_asset_records,
        register_attenuation_artefact_planned,
        register_manual_bin_mask_artefact,
        register_pixel_mask_artefact,
        register_swiss_cheese_artefact,
        resolve_campaign_slug,
    )

    spec_dict = _load_spec(spec)
    _validate_spec(spec_dict)

    ipts: int = spec_dict["ipts"]
    campaign_slug: str = spec_dict["campaign_slug"]

    if shared_root is None:
        shared_root = Path(f"/SNS/SNAP/IPTS-{ipts}/shared")
    shared_root = Path(shared_root)

    # ── Resolve assembly_type ─────────────────────────────────────────────────
    # Auto-derived from the first run's SEEMeta when not specified in spec.
    if "assembly_type" in spec_dict and spec_dict["assembly_type"]:
        assembly_type: str = spec_dict["assembly_type"]
    else:
        from .requirements import infer_assembly_type_from_run
        runs = spec_dict.get("runs", [])
        if not runs:
            raise ValueError(
                "Cannot derive assembly_type: spec has neither 'assembly_type' "
                "nor any 'runs' to read SEEMeta from."
            )
        seemeta_dir = spec_dict.get("seemeta_dir", "SEE")
        pattern = spec_dict.get("seemeta_filename_pattern", "SEE{run:06d}.json")
        assembly_type = infer_assembly_type_from_run(
            runs[0],
            ipts=ipts,
            shared_root=shared_root,
            seemeta_dir=seemeta_dir,
            filename_pattern=pattern,
        )
        spec_dict["assembly_type"] = assembly_type  # so dry-run report shows it
        log.info("assembly_type auto-derived from SEEMeta of run %d → %s",
                 runs[0], assembly_type)

    # ── Preflight ─────────────────────────────────────────────────────────────
    if not skip_preflight:
        problems = preflight_spec(spec_dict, shared_root=shared_root)
        if problems:
            bullet_list = "\n".join(f"  • {p}" for p in problems)
            raise ValueError(
                f"Spec preflight failed ({len(problems)} problem(s)):\n{bullet_list}"
            )

    log.info("Setting up campaign %r for IPTS %d (dry_run=%s)", campaign_slug, ipts, dry_run)

    if dry_run:
        return _dry_run_report(spec_dict, shared_root=shared_root)

    # ── Bootstrap ─────────────────────────────────────────────────────────────
    try:
        bootstrap_campaign(
            ipts=ipts,
            campaign_slug=campaign_slug,
            assembly_type=assembly_type,
            shared_root=shared_root,
            description=spec_dict.get("description", ""),
            owners=spec_dict.get("owners", []),
        )
        log.info("Campaign %r bootstrapped.", campaign_slug)
    except SlugConflictError:
        log.info("Campaign %r already exists — skipping bootstrap.", campaign_slug)

    assets_ingested: list[dict[str, Any]] = []
    artefacts_registered: list[dict[str, Any]] = []
    warnings: list[str] = []

    # ── Ingest listed assets ──────────────────────────────────────────────────
    for entry in spec_dict.get("assets", []):
        raw_path = entry["path"]
        src = _resolve_asset_path(raw_path, shared_root, entry["asset_type"])
        asset_id = entry.get("asset_id") or src.stem
        run_number = entry.get("run_number")
        scope = "run" if run_number is not None else "campaign"

        log.info("Ingesting %s asset %r from %s", entry["asset_type"], asset_id, src)
        record = ingest_asset(
            ipts=ipts,
            campaign_identifier=campaign_slug,
            source_path=src,
            asset_type=entry["asset_type"],
            asset_id=asset_id,
            shared_root=shared_root,
            applicability_scope=scope,
            run_number=run_number,
            provenance_source=entry.get("provenance_source", "imported"),
            created_by=created_by,
            notes=entry.get("notes"),
        )
        assets_ingested.append(record)
        log.info("  ✓ %s v%d  checksum=%s…", asset_id, record["version"], record["checksum"][:12])

    # ── Ingest SEEMeta for each run ───────────────────────────────────────────
    seemeta_dir_raw = spec_dict.get("seemeta_dir", "SEE")
    pattern = spec_dict.get("seemeta_filename_pattern", "SEE{run:06d}.json")
    if seemeta_dir_raw is not None:
        seemeta_dir = _resolve_path(seemeta_dir_raw, shared_root)
        for run in spec_dict.get("runs", []):
            fname = pattern.format(run=run)
            see_path = seemeta_dir / fname
            log.info("Ingesting SEEMeta run %d from %s", run, see_path)
            record = ingest_seemeta_for_run(
                ipts=ipts,
                campaign_identifier=campaign_slug,
                source_path=see_path,
                run_number=run,
                shared_root=shared_root,
                created_by=created_by,
            )
            assets_ingested.append(record)
            log.info("  ✓ SEEMeta run %d  checksum=%s…", run, record["checksum"][:12])

    # ── Register bin-mask artefacts ───────────────────────────────────────────
    for bm in spec_dict.get("bin_masks", []):
        mask_path = str(_resolve_path(bm["mask_path"], shared_root))
        ub_mat_paths = [
            str(_resolve_path(p, shared_root)) for p in bm["ub_mat_paths"]
        ]
        log.info("Registering bin_mask artefact %r", bm["artefact_id"])
        record = register_swiss_cheese_artefact(
            ipts=ipts,
            campaign_identifier=campaign_slug,
            artefact_id=bm["artefact_id"],
            mask_json_path=mask_path,
            source_run=bm["source_run"],
            ub_mat_paths=ub_mat_paths,
            width_coef=bm.get("width_coef", [1.0, 0.0]),
            is_lite=bm.get("is_lite", True),
            shared_root=shared_root,
            notes=bm.get("notes"),
            created_by=created_by,
        )
        artefacts_registered.append(record)
        log.info("  ✓ bin_mask %r registered.", record["artefact_id"])

    # ── Register manually-imported bin-mask artefacts ─────────────────────────
    for mbm in spec_dict.get("manual_bin_masks", []):
        mask_path = str(_resolve_path(mbm["mask_path"], shared_root))
        run_number = mbm.get("run_number")
        aid = mbm["artefact_id"]
        # Idempotency: skip if already registered and active.
        from .persistence import list_artefact_records as _lar
        if _lar(ipts=ipts, campaign_identifier=campaign_slug, shared_root=shared_root,
                artefact_id=aid, status="active"):
            log.info("  ↷ manual bin_mask %r already active — skipping.", aid)
            continue
        log.info("Registering manual bin_mask artefact %r", aid)
        record = register_manual_bin_mask_artefact(
            ipts=ipts,
            campaign_identifier=campaign_slug,
            artefact_id=aid,
            mask_json_path=mask_path,
            run_number=run_number,
            shared_root=shared_root,
            notes=mbm.get("notes"),
            created_by=created_by,
        )
        artefacts_registered.append(record)
        log.info("  ✓ manual bin_mask %r registered.", record["artefact_id"])

    # ── Register pixel-mask artefacts ─────────────────────────────────────────
    for pm in spec_dict.get("pixel_masks", []):
        nxs_path = str(_resolve_path(pm["nxs_path"], shared_root))
        run_number = pm.get("run_number")
        log.info("Registering pixel_mask artefact %r", pm["artefact_id"])
        record = register_pixel_mask_artefact(
            ipts=ipts,
            campaign_identifier=campaign_slug,
            artefact_id=pm["artefact_id"],
            nxs_path=nxs_path,
            method=pm["method"],
            ws_name=pm["ws_name"],
            shared_root=shared_root,
            run_number=run_number,
            notes=pm.get("notes"),
            created_by=created_by,
        )
        artefacts_registered.append(record)
        log.info("  ✓ pixel_mask %r registered.", record["artefact_id"])

    # ── Pre-declare planned attenuation artefacts ─────────────────────────────
    for pa in spec_dict.get("planned_attenuations", []):
        log.info("Pre-declaring planned attenuation %r", pa["artefact_id"])
        record = register_attenuation_artefact_planned(
            ipts=ipts,
            campaign_identifier=campaign_slug,
            artefact_id=pa["artefact_id"],
            shared_root=shared_root,
            notes=pa.get("notes"),
            created_by=created_by,
        )
        artefacts_registered.append(record)
        log.info("  ✓ planned attenuation %r pre-declared.", record["artefact_id"])

    summary = {
        "campaign_slug": campaign_slug,
        "assets_ingested": assets_ingested,
        "artefacts_registered": artefacts_registered,
        "problems": warnings,
    }
    log.info(
        "Campaign %r setup complete: %d assets, %d artefacts.",
        campaign_slug,
        len(assets_ingested),
        len(artefacts_registered),
    )
    return summary


# ── dry-run report ────────────────────────────────────────────────────────────

def _dry_run_report(
    spec: dict[str, Any],
    shared_root: Path,
) -> dict[str, Any]:
    """Return a report of what *would* be ingested without writing anything."""
    ipts = spec["ipts"]
    lines: list[str] = [
        f"[dry-run] Campaign {spec['campaign_slug']!r} — IPTS {ipts}",
        f"  assembly_type : {spec['assembly_type']}",
        f"  description   : {spec.get('description', '')}",
        f"  owners        : {spec.get('owners', [])}",
        "",
        "  Assets to ingest:",
    ]
    for entry in spec.get("assets", []):
        p = _resolve_asset_path(entry["path"], shared_root, entry["asset_type"])
        scope = f"run={entry['run_number']}" if "run_number" in entry else "campaign"
        exists = "✓" if p.exists() else "✗ MISSING"
        lines.append(f"    [{entry['asset_type']:<22}] {p.name:<40} {scope}  {exists}")

    seemeta_dir_raw = spec.get("seemeta_dir", "SEE")
    pattern = spec.get("seemeta_filename_pattern", "SEE{run:06d}.json")
    if seemeta_dir_raw is not None:
        seemeta_dir = _resolve_path(seemeta_dir_raw, shared_root)
        lines.append("")
        lines.append("  SEEMeta to ingest:")
        for run in spec.get("runs", []):
            p = seemeta_dir / pattern.format(run=run)
            exists = "✓" if p.exists() else "✗ MISSING"
            lines.append(f"    run {run:<8} {p.name:<30} {exists}")

    if spec.get("bin_masks"):
        lines.append("")
        lines.append("  Bin-mask artefacts to register:")
        for bm in spec["bin_masks"]:
            p = _resolve_path(bm["mask_path"], shared_root)
            exists = "✓" if p.exists() else "✗ MISSING"
            lines.append(f"    {bm['artefact_id']:<45} {p.name}  {exists}")

    if spec.get("manual_bin_masks"):
        lines.append("")
        lines.append("  Manual bin-mask artefacts to register:")
        for mbm in spec["manual_bin_masks"]:
            p = _resolve_path(mbm["mask_path"], shared_root)
            exists = "✓" if p.exists() else "✗ MISSING"
            run_tag = f"  run={mbm['run_number']}" if "run_number" in mbm else ""
            lines.append(f"    {mbm['artefact_id']:<45} {p.name}{run_tag}  {exists}")

    if spec.get("pixel_masks"):
        lines.append("")
        lines.append("  Pixel-mask artefacts to register:")
        for pm in spec["pixel_masks"]:
            p = _resolve_path(pm["nxs_path"], shared_root)
            exists = "✓" if p.exists() else "✗ MISSING"
            lines.append(f"    {pm['artefact_id']:<45} {p.name}  {exists}")

    if spec.get("planned_attenuations"):
        lines.append("")
        lines.append("  Planned attenuations to pre-declare:")
        for pa in spec["planned_attenuations"]:
            lines.append(f"    {pa['artefact_id']}")

    report = "\n".join(lines)
    print(report)
    return {"dry_run_report": report, "campaign_slug": spec["campaign_slug"]}


# ── primary user-facing entry point ──────────────────────────────────────────

def auto_register_bin_mask_for_campaign(
    *,
    ipts: int,
    campaign_identifier: int | str,
    source_run: int,
    shared_root: Path | str | None = None,
    is_lite: bool = True,
    width_coef: list[float] | None = None,
    created_by: str = "operator",
    artefact_id: str | None = None,
    notes: str | None = None,
    dry_run: bool = False,
    prefer: str = "monitor",
    n_diamonds: int = 2,
    keep_diagnostics: bool = False,
    monitor2_l2: float | None = None,
) -> list[dict[str, Any]]:
    """Compute and register a swiss-cheese bin-mask automatically.

    Strategy is controlled by *prefer*:

    * ``prefer="monitor"`` (default) — always build a notch mask from the
      transmission monitor.  Robust, fully automatic, no UB matrices needed.

    * ``prefer="ub"`` — build a UB-derived swiss-cheese mask:

        1. Look for ``ub_matrix`` assets registered for *source_run*.
        2. If found → use them directly.
        3. If not found → attempt to determine them from peaks via
           :func:`build_swiss_cheese_from_run`; the resulting ``.mat``
           files are saved to ``{campaign_dir}/artefacts/masks/ubs/``
           and **registered as ``ub_matrix`` assets** so they are reused
           on subsequent runs.
        4. If UB creation fails (e.g. too few peaks) → emit a warning and
           transparently fall back to a monitor-derived notch mask.

    Mask JSON files are written to the canonical campaign artefact dir:
    ``{campaign_dir}/artefacts/masks``.

    Args:
        ipts: IPTS number.
        campaign_identifier: Campaign id (int) or slug (str).
        source_run: Run number used as donor / source for mask generation.
        shared_root: Override IPTS shared root.
        is_lite: Lite-mode flag (default True).
        width_coef: Notch-width polynomial coefficients for the UB-derived
            mask (default ``[1.0, 0.0]``).  Ignored for monitor-derived masks.
        created_by: Provenance author.
        artefact_id: Override artefact identifier.  Defaults depend on the
            method chosen (``"binmask-run{N}"`` or ``"binmask-notches-run{N}"``).
        notes: Optional notes recorded on the artefact.
        dry_run: When ``True``, report what would happen without writing.
        prefer: ``"monitor"`` (default) or ``"ub"`` — see above.
        n_diamonds: Number of diamonds expected when auto-determining UBs.
        keep_diagnostics: When ``True``, intermediate Mantid workspaces
            produced by the builders (raw-event ws, MD ws, monitor spectra,
            etc.) are adopted into ``wrap_diagnostics_{source_run}`` for
            inspection in Workbench.  Default ``False`` — campaign setup
            keeps the workspace tree clean by default.
        monitor2_l2: Optional corrected L2 distance (metres) for ``monitor2``.
            When provided, the monitor instrument component is moved to this
            position (in TOF, before unit conversion) so that wavelength
            calibration is accurate.  Applies only to monitor-derived masks.

    Returns:
        List of artefact record dicts (empty on dry-run).
    """
    from .persistence import (
        get_campaign_artefact_dir,
        resolve_campaign_slug,
    )

    if prefer not in ("monitor", "ub"):
        raise ValueError(f"prefer must be 'monitor' or 'ub', got {prefer!r}")

    slug = resolve_campaign_slug(
        ipts=ipts,
        campaign_identifier=campaign_identifier,
        shared_root=shared_root,
    )
    output_dir = get_campaign_artefact_dir(
        ipts=ipts,
        campaign_identifier=slug,
        shared_root=shared_root,
        subdir="masks",
    )

    if prefer == "ub":
        try:
            return _build_ub_mask(
                ipts=ipts,
                slug=slug,
                source_run=source_run,
                output_dir=output_dir,
                shared_root=shared_root,
                is_lite=is_lite,
                width_coef=width_coef,
                created_by=created_by,
                artefact_id=artefact_id,
                notes=notes,
                dry_run=dry_run,
                n_diamonds=n_diamonds,
                keep_diagnostics=keep_diagnostics,
            )
        except Exception as exc:
            print(
                f"  ⚠ UB-derived mask failed ({type(exc).__name__}: {exc})."
                "\n    Falling back to monitor-derived notch mask."
            )

    # Default / fallback: monitor-derived
    return _build_monitor_mask(
        ipts=ipts,
        slug=slug,
        source_run=source_run,
        output_dir=output_dir,
        shared_root=shared_root,
        is_lite=is_lite,
        created_by=created_by,
        artefact_id=artefact_id,
        notes=notes,
        dry_run=dry_run,
        keep_diagnostics=keep_diagnostics,
        monitor2_l2=monitor2_l2,
    )


def _build_ub_mask(
    *,
    ipts: int,
    slug: str,
    source_run: int,
    output_dir: Path,
    shared_root: Path | str | None,
    is_lite: bool,
    width_coef: list[float] | None,
    created_by: str,
    artefact_id: str | None,
    notes: str | None,
    dry_run: bool,
    n_diamonds: int,
    keep_diagnostics: bool = False,
) -> list[dict[str, Any]]:
    """Build a UB-derived swiss-cheese mask, auto-creating UBs if needed.

    Internal helper; see :func:`auto_register_bin_mask_for_campaign`.
    """
    from .masking import (
        build_swiss_cheese_from_run,
        build_swiss_cheese_from_ub_files,
    )
    from .persistence import (
        ingest_asset,
        list_artefact_records,
        list_asset_records,
        register_swiss_cheese_artefact,
    )

    aid = artefact_id or f"binmask-run{source_run}"
    coefs = list(width_coef) if width_coef is not None else [1.0, 0.0]

    # ── Idempotency check ────────────────────────────────────────────────────
    existing = list_artefact_records(
        ipts=ipts,
        campaign_identifier=slug,
        shared_root=shared_root,
        artefact_id=aid,
        status="active",
    )
    if existing:
        print(
            f"  Auto bin-mask: active artefact {aid!r} already registered "
            f"({len(existing)} record(s)) — skipping generation."
        )
        return existing

    # ── Step 1: look for already-registered UB assets for this run ───────────
    ub_records = list_asset_records(
        ipts=ipts,
        campaign_identifier=slug,
        shared_root=shared_root,
        asset_type="ub_matrix",
        status="active",
        run_number=source_run,
    )

    if ub_records:
        ub_paths = [r["path"] for r in ub_records]
        print(
            f"  Auto bin-mask: UB-derived (run {source_run}, "
            f"using {len(ub_paths)} pre-registered UB file(s)) → {aid}"
        )
        if dry_run:
            print(f"    [dry-run] would write masks to {output_dir}")
            return []
        mask_paths = build_swiss_cheese_from_ub_files(
            ub_paths=ub_paths,
            run_number=source_run,
            width_coef=coefs,
            is_lite=is_lite,
            output_dir=output_dir,
            file_prefix=f"SNAP_{source_run}",
            ipts=ipts,
            keep_diagnostics=keep_diagnostics,
        )
    else:
        # ── Step 1.5: scan canonical dir for orphan UB .mat files ────────────
        # The library convention is that UB files for run N live at
        #   {output_dir}/ubs/SNAP{N}UB*.mat
        # — auto-generated by previous runs, or hand-placed there by the
        # operator.  If we find any, ingest them as ub_matrix assets so
        # they are visible to all subsequent calls, then use them directly.
        orphan_ubs = sorted((output_dir / "ubs").glob(f"SNAP{source_run}UB*.mat"))
        if orphan_ubs:
            print(
                f"  Auto bin-mask: found {len(orphan_ubs)} unregistered UB "
                f"file(s) in {output_dir / 'ubs'} — ingesting as assets..."
            )
            if dry_run:
                print(f"    [dry-run] would ingest {len(orphan_ubs)} UB asset(s)")
                return []
            ub_paths = []
            for ub_path in orphan_ubs:
                rec = ingest_asset(
                    ipts=ipts,
                    campaign_identifier=slug,
                    source_path=ub_path,
                    asset_type="ub_matrix",
                    asset_id=ub_path.stem,
                    shared_root=shared_root,
                    applicability_scope="run",
                    run_number=source_run,
                    provenance_source="generated",
                    created_by=created_by,
                    notes=f"Auto-discovered for run {source_run}",
                )
                ub_paths.append(rec["path"])
                print(f"    ✓ registered UB asset {rec['asset_id']}")
            mask_paths = build_swiss_cheese_from_ub_files(
                ub_paths=ub_paths,
                run_number=source_run,
                width_coef=coefs,
                is_lite=is_lite,
                output_dir=output_dir,
                file_prefix=f"SNAP_{source_run}",
                ipts=ipts,
                keep_diagnostics=keep_diagnostics,
            )
        else:
            # ── Step 2: nothing on disk either → determine UBs from peaks ────
            print(
                f"  Auto bin-mask: no UBs registered or on disk for run "
                f"{source_run}; attempting peak-find + UB determination..."
            )
            if dry_run:
                print(
                    f"    [dry-run] would run build_swiss_cheese_from_run "
                    f"(n_diamonds={n_diamonds}) into {output_dir}"
                )
                return []
            mask_paths, new_ub_paths = build_swiss_cheese_from_run(
                run_number=source_run,
                width_coef=coefs,
                is_lite=is_lite,
                output_dir=output_dir,
                file_prefix=f"SNAP_{source_run}",
                ipts=ipts,
                n_diamonds=n_diamonds,
                keep_diagnostics=keep_diagnostics,
            )
            # Register the freshly-created UBs so they are reused next time.
            ub_paths = []
            for ub_path in new_ub_paths:
                rec = ingest_asset(
                    ipts=ipts,
                    campaign_identifier=slug,
                    source_path=ub_path,
                    asset_type="ub_matrix",
                    asset_id=ub_path.stem,        # e.g. "SNAP65891UB1"
                    shared_root=shared_root,
                    applicability_scope="run",
                    run_number=source_run,
                    provenance_source="generated",
                    created_by=created_by,
                    notes=f"Auto-generated from run {source_run}",
                )
                ub_paths.append(rec["path"])
                print(f"    ✓ registered UB asset {rec['asset_id']}")

    # ── Step 3: register the artefact ────────────────────────────────────────
    records: list[dict[str, Any]] = []
    for mp in mask_paths:
        rec = register_swiss_cheese_artefact(
            ipts=ipts,
            campaign_identifier=slug,
            artefact_id=aid,
            mask_json_path=str(mp),
            source_run=source_run,
            ub_mat_paths=ub_paths,
            width_coef=coefs,
            is_lite=is_lite,
            shared_root=shared_root,
            notes=notes,
            created_by=created_by,
        )
        records.append(rec)
        print(f"    ✓ registered {mp.name}")
    return records


def _build_monitor_mask(
    *,
    ipts: int,
    slug: str,
    source_run: int,
    output_dir: Path,
    shared_root: Path | str | None,
    is_lite: bool,
    created_by: str,
    artefact_id: str | None,
    notes: str | None,
    dry_run: bool,
    keep_diagnostics: bool = False,
    monitor2_l2: float | None = None,
) -> list[dict[str, Any]]:
    """Build a monitor-derived notch mask. Internal helper."""
    from .masking import build_swiss_cheese_from_transmission_monitor
    from .persistence import list_artefact_records, register_swiss_cheese_artefact

    aid = artefact_id or f"binmask-notches-run{source_run}"

    # ── Idempotency check ────────────────────────────────────────────────────
    existing = list_artefact_records(
        ipts=ipts,
        campaign_identifier=slug,
        shared_root=shared_root,
        artefact_id=aid,
        status="active",
    )
    if existing:
        print(
            f"  Auto bin-mask: active artefact {aid!r} already registered "
            f"({len(existing)} record(s)) — skipping generation."
        )
        return existing

    print(f"  Auto bin-mask: monitor-derived (run {source_run}) → {aid}")
    if dry_run:
        print(f"    [dry-run] would write notch mask to {output_dir}")
        return []

    mask_paths, _ = build_swiss_cheese_from_transmission_monitor(
        run_number=source_run,
        is_lite=is_lite,
        output_dir=output_dir,
        file_prefix=f"SNAP_{source_run}",
        ipts=ipts,
        keep_diagnostics=keep_diagnostics,
        monitor2_l2=monitor2_l2,
    )
    records: list[dict[str, Any]] = []
    for mp in mask_paths:
        rec = register_swiss_cheese_artefact(
            ipts=ipts,
            campaign_identifier=slug,
            artefact_id=aid,
            mask_json_path=str(mp),
            source_run=source_run,
            ub_mat_paths=[],
            width_coef=[],
            is_lite=is_lite,
            shared_root=shared_root,
            notes=notes,
            created_by=created_by,
        )
        records.append(rec)
        print(f"    ✓ registered {mp.name}")
    return records


def run_campaign_setup(
    spec: dict[str, Any] | str | Path,
    *,
    dry_run: bool = False,
    created_by: str = "operator",
    shared_root: Path | str | None = None,
    auto_artefacts: bool = True,
    mask_source_run: int | None = None,
    mask_prefer: str = "monitor",
    keep_diagnostics: bool = False,
    monitor2_l2: float | None = None,
) -> dict[str, Any]:
    """Set up a campaign from a spec file or dict — the single callable for interactive use.

    This is the function to call from Mantid Workbench or a Jupyter notebook
    instead of running ``scripts/setup_campaign.py`` on the command line.  It
    combines preflight reporting, optional dry-run preview, and the full
    bootstrap + ingestion sequence into one call.

    Args:
        spec: Either a path to a ``campaign_setup_spec.json`` file (the one
            that lives in the IPTS shared folder) **or** an already-parsed
            dict.  Relative paths *inside* the spec are resolved against
            *shared_root*.
        dry_run: When ``True``, print a preview of what would be ingested and
            return without writing anything.  Useful for checking the spec
            before committing.
        created_by: Provenance author stored in all written records.
            Default ``"operator"``; pass your FedID for traceability.
        shared_root: Override the IPTS shared root.  Defaults to
            ``/SNS/SNAP/IPTS-<ipts>/shared`` derived from the spec.
        auto_artefacts: When ``True`` (default) and the assembly is DAC,
            automatically generate and register a bin-mask artefact.
        mask_source_run: Override the donor run for the auto bin-mask.
            Defaults to the first run in the spec.
        mask_prefer: ``"monitor"`` (default) — build the bin-mask from the
            transmission monitor; or ``"ub"`` — build a UB-derived
            swiss-cheese mask, attempting to determine UBs from peaks if
            none are registered (registering any newly-found UBs as
            ``ub_matrix`` assets), and falling back to monitor-derived
            on failure.
        keep_diagnostics: When ``True``, intermediate Mantid workspaces
            produced during mask generation are adopted into a per-run
            diagnostics group (``wrap_diagnostics_{run}``) so the operator
            can inspect them in Mantid Workbench.  Default ``False`` —
            campaign setup keeps the ADS tree clean.  See
            :func:`purge_artefacts_for_run` for end-of-reduction cleanup.
        monitor2_l2: Optional corrected L2 distance (metres) for ``monitor2``.
            Applied before wavelength conversion when building a
            monitor-derived notch mask.  Use when the NeXus instrument
            geometry has an incorrect monitor2 position.

    Returns:
        On a real run: a summary dict with keys
        ``"campaign_slug"``, ``"assets_ingested"``,
        ``"artefacts_registered"``, ``"problems"``.

        On a dry run: ``{"dry_run_report": <str>, "campaign_slug": <str>}``.

    Raises:
        FileNotFoundError: The spec file path does not exist.
        ValueError: The spec fails schema validation **or** a required source
            file is missing (preflight failure) and ``dry_run=False``.

    Example — typical Workbench usage::

        from snapwrap.reduction_artefacts import run_campaign_setup

        run_campaign_setup(
            "/SNS/SNAP/IPTS-33219/shared/campaigns/brucite_a.json",
            dry_run=True,           # safe preview first
            created_by="loveday",
        )

        run_campaign_setup(
            "/SNS/SNAP/IPTS-33219/shared/campaigns/brucite_a.json",
            created_by="loveday",   # real run
        )
    """
    spec_dict = _load_spec(spec)

    # Resolve shared_root early so preflight and dry-run report both use it.
    if shared_root is None:
        ipts = spec_dict.get("ipts", 0)
        shared_root = Path(f"/SNS/SNAP/IPTS-{ipts}/shared")
    shared_root = Path(shared_root)

    # ── Preflight (always) ────────────────────────────────────────────────────
    problems = preflight_spec(spec_dict, shared_root=shared_root)
    if problems:
        bullet_list = "\n".join(f"  ✗  {p}" for p in problems)
        msg = f"Preflight found {len(problems)} problem(s):\n{bullet_list}"
        if dry_run:
            # In dry-run mode just print the problems — don't raise.
            print(msg)
            print()
        else:
            raise ValueError(msg)
    else:
        print(f"✓ Preflight passed — all source files present.\n")

    # ── Delegate to setup_campaign_from_spec ──────────────────────────────────
    summary = setup_campaign_from_spec(
        spec_dict,
        shared_root=shared_root,
        dry_run=dry_run,
        created_by=created_by,
        skip_preflight=True,   # already done above
    )

    if dry_run:
        # Announce the auto-bin-mask plan the live path would execute, so the
        # operator sees what will happen on a real run.
        if auto_artefacts:
            assembly = str(spec_dict.get("assembly_type", "")).upper()
            runs = spec_dict.get("runs", [])
            print()
            print("  Auto bin-mask plan:")
            if assembly != "DAC":
                print(f"    (skipped — assembly_type={assembly!r}, "
                      "auto bin-mask only runs for DAC)")
            elif spec_dict.get("bin_masks"):
                print("    (skipped — bin_masks already declared in spec)")
            elif not runs:
                print("    (skipped — no runs in spec)")
            else:
                src_run = mask_source_run if mask_source_run is not None else runs[0]
                if mask_prefer == "ub":
                    strategy = ("UB-derived swiss-cheese "
                                "(falls back to monitor notches if UBs unavailable)")
                else:
                    strategy = "notches from transmission monitor"
                campaign_dir = (
                    Path(shared_root) / "campaigns" / spec_dict["campaign_slug"]
                )
                mask_dir = campaign_dir / "artefacts" / "masks"
                print(f"    strategy     : {strategy}")
                print(f"    source run   : {src_run}")
                print(f"    output dir   : {mask_dir}")
                print(f"    diagnostics  : "
                      f"{'kept in wrap_diagnostics_'+str(src_run) if keep_diagnostics else 'discarded'}")
        return summary

    # ── Auto artefact generation (assembly-type driven) ───────────────────────
    if auto_artefacts:
        # spec_dict["assembly_type"] is populated by setup_campaign_from_spec
        # (either from the spec or via SEEMeta auto-detection).
        assembly = str(spec_dict.get("assembly_type", "")).upper()
        runs = spec_dict.get("runs", [])
        if assembly == "DAC" and runs and not spec_dict.get("bin_masks"):
            print("\nAuto-generating bin-mask artefact for DAC assembly...")
            try:
                src_run = mask_source_run if mask_source_run is not None else runs[0]
                auto_records = auto_register_bin_mask_for_campaign(
                    ipts=spec_dict["ipts"],
                    campaign_identifier=summary["campaign_slug"],
                    source_run=src_run,
                    shared_root=shared_root,
                    created_by=created_by,
                    prefer=mask_prefer,
                    keep_diagnostics=keep_diagnostics,
                    monitor2_l2=monitor2_l2,
                )
                summary["artefacts_registered"].extend(auto_records)
            except Exception as exc:
                print(f"  ⚠ auto bin-mask generation failed: {exc}")
                summary.setdefault("problems", []).append(
                    f"auto bin-mask failed: {exc}"
                )

    # ── Print summary ─────────────────────────────────────────────────────────
    slug = summary["campaign_slug"]
    n_assets = len(summary["assets_ingested"])
    n_artefacts = len(summary["artefacts_registered"])

    print(f"\n{'═' * 60}")
    print(f"  Campaign {slug!r} — setup complete")
    print(f"{'═' * 60}")
    print(f"  Assets ingested     : {n_assets}")
    print(f"  Artefacts registered: {n_artefacts}")

    if summary["assets_ingested"]:
        print("\n  Assets:")
        for a in summary["assets_ingested"]:
            scope = a["applicability"]["scope"]
            run_tag = (
                f"  run={a['applicability']['run_number']}" if scope == "run" else ""
            )
            print(
                f"    [{a['asset_type']:<22}] {a['asset_id']:<35} "
                f"v{a['version']}  {scope}{run_tag}"
            )

    if summary["artefacts_registered"]:
        print("\n  Artefacts:")
        for r in summary["artefacts_registered"]:
            print(
                f"    [{r['artefact_type']:<22}] {r['artefact_id']:<35} "
                f"status={r['status']}"
            )

    runs = spec_dict.get("runs", [])
    if runs:
        ipts = spec_dict["ipts"]
        print(
            f"\nTip: inspect artefact resolution with:\n"
            f"  from snapwrap.reduction_artefacts import build_run_manifest\n"
            f"  build_run_manifest(ipts={ipts}, campaign_identifier={slug!r}, "
            f"run_number={runs[0]})"
        )

    return summary


# ─────────────────────────────────────────────────────────────────────────────
# run_campaign — the single high-level entry point for operator config scripts
# ─────────────────────────────────────────────────────────────────────────────

def run_campaign(
    *,
    campaign_slug: str,
    runs: list[int],
    assets: list[dict[str, Any]] | None = None,
    description: str = "",
    created_by: str = "operator",
    ipts: int | None = None,
    shared_root: Path | str | None = None,
    mask_source_run: int | None = None,
    mask_prefer: str = "monitor",
    keep_diagnostics: bool = False,
    monitor2_l2: float | None = None,
    reduce_options: dict[str, Any] | None = None,
    manual_bin_masks: list[dict[str, Any]] | None = None,
    dry_run: bool = False,
    setup_only: bool = False,
    reduce_only: bool = False,
) -> dict[str, Any]:
    """One-call orchestrator: setup the campaign, then reduce every run.

    The intent is that operator "config scripts" contain *only* declarations
    (run numbers, asset list, slug, options) plus a single call to this
    function — no orchestration code of their own.

    Pipeline:
      1. IPTS is derived from ``runs[0]`` via ``GetIPTS`` unless given.
      2. ``shared_root`` defaults to ``/SNS/SNAP/IPTS-<ipts>/shared``.
      3. A spec dict is assembled and passed to :func:`run_campaign_setup`,
         which performs preflight, bootstrap, asset ingestion, SEEMeta
         ingestion and auto bin-mask generation.
      4. Each run is reduced via :func:`reduceSEE` with ``reduce_options``
         forwarded as ``wrap.reduce`` kwargs.

    Args:
        campaign_slug: Short, unique, machine-friendly identifier for the
            campaign within the IPTS (e.g. ``"dac_brucite_a"``).
        runs: Run numbers to include in the campaign and reduce.
        assets: Raw assets (CIFs, optional UB matrices, …) to ingest at
            setup time.  Defaults to ``[]``.
        description: Free-text description stored in ``campaign.json``.
        created_by: FedID / author recorded in provenance fields.
        ipts: IPTS number.  Auto-derived from ``runs[0]`` if ``None``.
        shared_root: Override the IPTS shared root (useful in tests).
        mask_source_run: Donor run for auto bin-mask generation.  Defaults
            to ``runs[0]``.
        mask_prefer: ``"monitor"`` (default) or ``"ub"`` — strategy for the
            auto bin-mask.
        keep_diagnostics: Keep intermediate Mantid workspaces from mask
            generation in a per-run diagnostic group.
        monitor2_l2: Optional corrected L2 distance (metres) for ``monitor2``.
            Passed to the monitor-derived notch mask builder so the
            instrument component is repositioned before wavelength conversion.
        reduce_options: Kwargs forwarded to ``wrap.reduce`` per run
            (e.g. ``{"keepUnfocussed": True, "verbose": True}``).
        manual_bin_masks: List of manually-created bin-mask entries to
            register as supplemental artefacts.  Each entry is a dict with
            keys ``artefact_id``, ``mask_path``, and optionally
            ``run_number`` and ``notes``.  These are registered via
            :func:`register_manual_bin_mask_artefact` and will appear in
            ``binMaskList`` alongside any auto-generated masks at
            reduction time.
        dry_run: When ``True``, preview setup and announce reductions
            without writing to disk or calling ``wrap.reduce``.
        setup_only: Skip the reduction phase.
        reduce_only: Skip the setup phase (campaign must already exist).

    Returns:
        Dict with keys ``"ipts"``, ``"shared_root"``, ``"campaign_slug"``,
        ``"setup_summary"`` (or ``None``), ``"reduce_results"`` (list of
        ``wrap.reduce`` return values; ``None`` entries for dry-run/skipped).
    """
    from .reduce import reduceSEE, resolve_ipts_for_run

    assets = assets or []
    reduce_options = reduce_options or {}

    # ── IPTS / shared_root resolution ─────────────────────────────────────
    if ipts is None:
        if not runs:
            raise ValueError("runs is empty — provide at least one run number.")
        ipts = resolve_ipts_for_run(runs[0])
    if shared_root is None:
        shared_root = Path(f"/SNS/SNAP/IPTS-{ipts}/shared")
    shared_root = Path(shared_root)

    print(f"IPTS: {ipts}  shared: {shared_root}")
    print(f"Campaign: {campaign_slug}  runs: {runs}\n")

    # ── Setup phase ───────────────────────────────────────────────────────
    setup_summary: dict[str, Any] | None = None
    if not reduce_only:
        spec = {
            "ipts": ipts,
            "campaign_slug": campaign_slug,
            "description": description,
            "owners": [created_by],
            "runs": list(runs),
            "assets": list(assets),
            "manual_bin_masks": list(manual_bin_masks or []),
        }
        setup_summary = run_campaign_setup(
            spec,
            dry_run=dry_run,
            created_by=created_by,
            shared_root=shared_root,
            mask_source_run=mask_source_run,
            mask_prefer=mask_prefer,
            keep_diagnostics=keep_diagnostics,
            monitor2_l2=monitor2_l2,
        )

    # ── Reduce phase ──────────────────────────────────────────────────────
    reduce_results: list[Any] = []
    if not setup_only:
        for run in runs:
            print(f"\n── Run {run} {'(dry-run)' if dry_run else ''} ──")
            if dry_run:
                print(f"  [dry-run] would call reduceSEE({run}, **{reduce_options})")
                reduce_results.append(None)
                continue
            result = reduceSEE(
                run,
                ipts=ipts,
                shared_root=shared_root,
                campaign=campaign_slug,
                rebuild_manifest=True,
                **reduce_options,
            )
            reduce_results.append(result)

    return {
        "ipts": ipts,
        "shared_root": shared_root,
        "campaign_slug": campaign_slug,
        "setup_summary": setup_summary,
        "reduce_results": reduce_results,
    }
