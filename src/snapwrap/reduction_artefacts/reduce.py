"""reduce_from_manifest — drive snapwrap.reduce() from a run manifest.

This module reads a written run manifest (Phase 5 output) and translates the
``selected_artefacts`` list into the correct ``snapwrap.reduce`` keyword
arguments.

Artefact-to-reduce mapping
--------------------------
bin_mask
    The manifest carries one or more ``bin_mask`` artefacts.  Their ``path``
    values point to swiss-cheese JSON files.  Each file is loaded via
    ``snapwrap.maskUtils.swissCheese`` — ``load(filename=path)`` then
    ``makeMaskBinsTables()`` — and the resulting Mantid table workspace
    names (``maskBins_{unit}`` for each unit in the file) are collected
    into ``binMaskList``.
pixel_mask
    ``pixelMaskIndex`` is not directly settable from a JSON; instead the .nxs
    file is loaded into Mantid as a workspace and its index (position in
    MaskWorkspace group) is passed.  For now we load it and pass
    ``pixelMaskIndex=0``.  TODO: support multi-mask index.
attenuation_workspace
    ``attenuationWSName`` — load the NeXus workspace and pass its name.
crystal_species / crystal_box
    Not consumed by ``snapwrap.reduce`` directly; reserved for post-reduction
    analysis.  Logged but not forwarded.

Usage::

    from snapwrap.reduction_artefacts.reduce import reduce_from_manifest

    result = reduce_from_manifest(
        manifest_path="/SNS/SNAP/IPTS-33219/shared/snapwrap/..."
                      "reduction_artefacts/campaigns/dac_brucite_a/"
                      "manifests/run_65891_attempt_1.json",
        wrap=wrap,          # snapwrap.utils module (or any object exposing
                            # a ``reduce(runNumber, **kwargs)`` callable)
        keepUnfocussed=True,
        verbose=True,
    )
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_manifest(manifest_path: str | Path) -> dict[str, Any]:
    p = Path(manifest_path)
    if not p.exists():
        raise FileNotFoundError(f"Manifest not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _artefacts_by_type(manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Group selected_artefacts by artefact_type."""
    by_type: dict[str, list[dict[str, Any]]] = {}
    for entry in manifest.get("selected_artefacts", []):
        at = entry.get("artefact_type", "unknown")
        by_type.setdefault(at, []).append(entry)
    return by_type


# ── main API ──────────────────────────────────────────────────────────────────

def build_reduce_kwargs(
    manifest: dict[str, Any],
    *,
    cheese_loader: Any | None = None,
    verbose: bool = False,
    keepUnfocussed: bool = False,
    continueNoDifcal: bool = False,
    continueNoVan: bool = False,
    extra_kwargs: dict[str, Any] | None = None,
    selected_artefacts_override: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Translate a run manifest into ``snapwrap.reduce`` keyword arguments.

    This function is *pure* in the sense that it only builds the kwargs dict;
    it does not call ``reduce`` itself.  Mantid workspace loading side-effects
    are performed here via ``cheese_loader``.

    Args:
        manifest: Parsed run manifest dict (from ``build_run_manifest``).
        cheese_loader: A callable ``(path: str) -> list[str]`` that loads a
            swiss-cheese JSON mask and returns the list of Mantid workspace
            names produced (e.g. ``["maskBins_dSpacing", "maskBins_Wavelength"]``).
            When ``None``, a naive default loader is attempted (requires Mantid
            to be active in the calling process).
        verbose: Forwarded to ``reduce``.
        keepUnfocussed: Forwarded to ``reduce``.
        continueNoDifcal: Forwarded to ``reduce``.
        continueNoVan: Forwarded to ``reduce``.
        extra_kwargs: Any additional keyword arguments to merge in last
            (caller overrides).
        selected_artefacts_override: If provided, replaces
            ``manifest["selected_artefacts"]`` entirely.  Use this when the
            workflow queue has explicit user-chosen artefact records that should
            take precedence over auto-discovered manifest contents.  Each entry
            must be a full artefact record dict (with ``artefact_type``,
            ``artefact_id``, ``path``, etc.) — the same shape returned by
            :func:`~snapwrap.reduction_artefacts.list_artefact_records`.

    Returns:
        Dict suitable for ``wrap.reduce(run_number, **kwargs)``.

    Raises:
        RuntimeError: If a required artefact path is ``"PENDING"`` (planned
            but not yet fulfilled).
    """
    if selected_artefacts_override is not None:
        manifest = dict(manifest)
        manifest["selected_artefacts"] = selected_artefacts_override

    by_type = _artefacts_by_type(manifest)
    run_number: int = manifest["run_number"]
    kwargs: dict[str, Any] = {
        "verbose": verbose,
        "keepUnfocussed": keepUnfocussed,
        "continueNoDifcal": continueNoDifcal,
        "continueNoVan": continueNoVan,
    }

    # ── bin_mask → binMaskList ────────────────────────────────────────────────
    bin_mask_entries = by_type.get("bin_mask", [])
    if bin_mask_entries:
        bin_mask_ws_names: list[str] = []
        for entry in bin_mask_entries:
            path = entry.get("path", "")
            if path == "PENDING":
                raise RuntimeError(
                    f"bin_mask artefact {entry.get('artefact_id')!r} is still "
                    f"'planned' (path=PENDING).  Fulfil it before reducing."
                )
            ws_names = _load_bin_mask(
                path,
                artefact_id=entry.get("artefact_id"),
                run_number=run_number,
                cheese_loader=cheese_loader,
            )
            log.info("Loaded bin_mask %r → workspaces %s", path, ws_names)
            bin_mask_ws_names.extend(ws_names)
        if bin_mask_ws_names:
            kwargs["binMaskList"] = bin_mask_ws_names

    # ── pixel_mask → pixelMaskIndex ───────────────────────────────────────────
    pixel_mask_entries = by_type.get("pixel_mask", [])
    if pixel_mask_entries:
        # Use the first pixel mask.  Multi-mask support is deferred.
        entry = pixel_mask_entries[0]
        path = entry.get("path", "")
        if path == "PENDING":
            raise RuntimeError(
                f"pixel_mask artefact {entry.get('artefact_id')!r} is still 'planned'."
            )
        ws_name = entry.get("metadata", {}).get("ws_name", f"pixmask_run{run_number}")
        _load_pixel_mask(path, ws_name=ws_name)
        log.info("Loaded pixel_mask %r → workspace %r", path, ws_name)
        try:
            from .workspace_groups import adopt_into_artefact_group
            adopt_into_artefact_group([ws_name], run_number=run_number)
        except Exception:
            pass
        kwargs["pixelMaskIndex"] = 0  # TODO: multi-mask index support

    # ── attenuation_workspace → attenuationWSName ─────────────────────────────
    atten_entries = by_type.get("attenuation_workspace", [])
    if atten_entries:
        entry = atten_entries[0]
        path = entry.get("path", "")
        if path == "PENDING":
            raise RuntimeError(
                f"attenuation_workspace artefact {entry.get('artefact_id')!r} is "
                f"still 'planned' (path=PENDING).  Fulfil it before reducing."
            )
        ws_name = entry.get("metadata", {}).get("ws_name", f"atten_run{run_number}")
        _load_attenuation_workspace(path, ws_name=ws_name)
        log.info("Loaded attenuation_workspace %r → workspace %r", path, ws_name)
        try:
            from .workspace_groups import adopt_into_artefact_group
            adopt_into_artefact_group([ws_name], run_number=run_number)
        except Exception:
            pass
        kwargs["attenuationWSName"] = ws_name

    # ── crystal_species / crystal_box — informational only ────────────────────
    for ignored_type in ("crystal_species", "crystal_box"):
        if ignored_type in by_type:
            log.debug(
                "Artefact type %r is not passed to reduce() (post-reduction use only)",
                ignored_type,
            )

    # ── caller overrides ──────────────────────────────────────────────────────
    if extra_kwargs:
        kwargs.update(extra_kwargs)

    return kwargs


def reduce_from_manifest(
    manifest_path: str | Path,
    *,
    wrap: Any,
    cheese_loader: Any | None = None,
    verbose: bool = False,
    keepUnfocussed: bool = False,
    continueNoDifcal: bool = False,
    continueNoVan: bool = False,
    extra_kwargs: dict[str, Any] | None = None,
) -> Any:
    """Load a run manifest and call ``wrap.reduce(run_number, **kwargs)``.

    This is the primary entry point for manifest-driven reduction.

    Args:
        manifest_path: Path to the manifest JSON written by
            :func:`~snapwrap.reduction_artefacts.persistence.build_run_manifest`.
        wrap: An object exposing a ``reduce(runNumber, **kwargs)`` callable.
            In practice this is the ``snapwrap.utils`` module itself
            (``import snapwrap.utils as wrap``) — there is no SNAPWrap
            class.  Any duck-typed equivalent works.
        cheese_loader: Optional custom swiss-cheese loader callable — see
            :func:`build_reduce_kwargs`.
        verbose: Passed through to ``wrap.reduce``.
        keepUnfocussed: Passed through to ``wrap.reduce``.
        continueNoDifcal: Passed through to ``wrap.reduce``.
        continueNoVan: Passed through to ``wrap.reduce``.
        extra_kwargs: Additional keyword arguments merged last (caller wins).

    Returns:
        Whatever ``wrap.reduce`` returns (workspace handle, output path, …).

    Example::

        import snapwrap.utils as wrap
        from snapwrap.reduction_artefacts.reduce import reduce_from_manifest

        result = reduce_from_manifest(
            "/SNS/SNAP/.../manifests/run_65891_attempt_1.json",
            wrap=wrap,
            keepUnfocussed=True,
            verbose=True,
        )
    """
    manifest = _load_manifest(manifest_path)
    run_number: int = manifest["run_number"]
    log.info(
        "reduce_from_manifest: run=%d  manifest=%s",
        run_number,
        Path(manifest_path).name,
    )

    kwargs = build_reduce_kwargs(
        manifest,
        cheese_loader=cheese_loader,
        verbose=verbose,
        keepUnfocussed=keepUnfocussed,
        continueNoDifcal=continueNoDifcal,
        continueNoVan=continueNoVan,
        extra_kwargs=extra_kwargs,
    )

    log.info("Calling wrap.reduce(%d, %s)", run_number, _fmt_kwargs(kwargs))
    return wrap.reduce(run_number, **kwargs)


# ── internal loaders (thin wrappers around Mantid / cheese API) ───────────────

def _load_bin_mask(
    path: str,
    *,
    artefact_id: str | None = None,
    run_number: int | None = None,
    cheese_loader: Any | None = None,
) -> list[str]:
    """Load a swiss-cheese JSON mask and return the workspace name list.

    When ``cheese_loader`` is supplied it is called as::

        ws_names = cheese_loader(path)

    Otherwise the default loader uses ``snapwrap.maskUtils.swissCheese`` —
    the real public API.  After ``load(filename=path)`` and
    ``makeMaskBinsTables()`` the underlying ``swissCheese`` instance creates
    table workspaces with the hard-coded names ``maskBins_{unit}`` for each
    unit present in the file.

    If *artefact_id* is supplied those tables are renamed to
    ``{artefact_id}_{unit}`` so multiple campaigns / runs can keep
    distinct masks side-by-side in the ADS (instead of silently clobbering
    a previously-loaded ``maskBins_Wavelength``).

    If *run_number* is supplied the renamed tables are also adopted into
    the per-run artefact group ``wrap_artefacts_{run_number}``.
    """
    if cheese_loader is not None:
        return cheese_loader(path)

    # Default loader — uses the real snapwrap.maskUtils API.  Mantid must be
    # available in the calling process (it is needed by CreateEmptyTableWorkspace
    # inside makeMaskBinsTables).
    try:
        from snapwrap.maskUtils import swissCheese  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            f"snapwrap.maskUtils not importable; cannot load bin_mask from {path!r}. "
            "Supply cheese_loader explicitly."
        ) from exc

    sc = swissCheese()
    sc.load(filename=path)
    sc.makeMaskBinsTables()
    units = getattr(sc, "uniqueUnits", None) or ["dSpacing"]

    # Generic names produced by makeMaskBinsTables (hard-coded inside maskUtils).
    raw_names = [f"maskBins_{u}" for u in units]

    if artefact_id:
        # Rename to make the workspace identifiable when multiple campaigns
        # / runs are loaded in the same session.
        try:
            import mantid.simpleapi as sapi  # type: ignore[import]
        except ImportError:
            return raw_names

        new_names: list[str] = []
        for raw, u in zip(raw_names, units):
            target = f"{artefact_id}_{u}"
            if raw in sapi.mtd.getObjectNames():
                if raw != target:
                    # If target already exists (e.g. re-load of same mask in
                    # same session), delete it first so the rename succeeds.
                    if target in sapi.mtd.getObjectNames():
                        try:
                            sapi.DeleteWorkspace(Workspace=target)
                        except Exception:
                            pass
                    sapi.RenameWorkspace(InputWorkspace=raw, OutputWorkspace=target)
            new_names.append(target)

        if run_number is not None:
            try:
                from .workspace_groups import adopt_into_artefact_group
                adopt_into_artefact_group(new_names, run_number=run_number)
            except Exception:
                pass

        return new_names

    return raw_names


def _load_pixel_mask(path: str, *, ws_name: str) -> None:
    """Load a pixel mask .nxs into a Mantid workspace named ``ws_name``."""
    try:
        import mantid.simpleapi as sapi  # type: ignore[import]
        sapi.LoadNexus(Filename=path, OutputWorkspace=ws_name)
    except ImportError as exc:
        raise RuntimeError(
            f"Mantid not importable; cannot load pixel_mask from {path!r}."
        ) from exc


def _load_attenuation_workspace(path: str, *, ws_name: str) -> None:
    """Load an attenuation workspace .nxs into Mantid."""
    try:
        import mantid.simpleapi as sapi  # type: ignore[import]
        sapi.LoadNexus(Filename=path, OutputWorkspace=ws_name)
    except ImportError as exc:
        raise RuntimeError(
            f"Mantid not importable; cannot load attenuation_workspace from {path!r}."
        ) from exc


def _fmt_kwargs(kwargs: dict[str, Any]) -> str:
    """Human-readable single-line repr of kwargs (truncates long lists)."""
    parts = []
    for k, v in kwargs.items():
        if isinstance(v, list) and len(v) > 4:
            parts.append(f"{k}=[…{len(v)} items]")
        else:
            parts.append(f"{k}={v!r}")
    return ", ".join(parts)


# ── reduceSEE: smart wrapper around wrap.reduce ───────────────────────────────

def resolve_ipts_for_run(run_number: int) -> int:
    """Derive the IPTS number for a SNAP run via Mantid's ``GetIPTS``.

    Raises:
        RuntimeError: Mantid is not importable, or the path returned by
            ``GetIPTS`` does not contain an ``IPTS-<n>`` segment.
    """
    import re
    try:
        from mantid.simpleapi import GetIPTS  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "Mantid not importable; cannot derive IPTS automatically. "
            "Pass ipts= explicitly."
        ) from exc
    ipts_path = GetIPTS(Instrument="SNAP", RunNumber=run_number)
    m = re.search(r"IPTS-(\d+)", str(ipts_path))
    if not m:
        raise RuntimeError(f"Could not parse IPTS number from path: {ipts_path}")
    return int(m.group(1))


# Backwards-compatible private alias (used internally).
_resolve_ipts_for_run = resolve_ipts_for_run


def _find_campaign_for_run(
    *,
    ipts: int,
    run_number: int,
    shared_root: str | Path | None,
) -> str:
    """Scan all campaigns under ``ipts`` and return the one that owns ``run_number``.

    A campaign is deemed to own a run if **any** of the following hold:
      * its ``assets_index.jsonl`` contains a record with that ``run_number``
        (e.g. a SEEMeta asset ingested at setup-time),
      * its ``manifests/`` directory contains a ``run_<n>_attempt_*.json`` file,
      * its living ``manifest.json`` lists the run.

    Raises:
        KeyError: if zero campaigns or more than one campaign claim the run.
    """
    from .persistence import _reduction_artefacts_root

    root = _reduction_artefacts_root(ipts=ipts, shared_root=shared_root)
    state_path = root / "_state.json"
    if not state_path.exists():
        raise KeyError(
            f"No reduction-artefacts state found for IPTS-{ipts}: {state_path}. "
            "Run the campaign setup script first."
        )

    with state_path.open("r", encoding="utf-8") as fh:
        state = json.load(fh)

    matches: list[str] = []
    for slug in state.get("campaigns", {}):
        campaign_dir = root / "campaigns" / slug
        if _campaign_owns_run(campaign_dir, run_number):
            matches.append(slug)

    if not matches:
        raise KeyError(
            f"Run {run_number} is not declared in any campaign under IPTS-{ipts}. "
            "Either add it to a campaign spec and re-run setup, or pass "
            "campaign= explicitly to reduceSEE()."
        )
    if len(matches) > 1:
        raise KeyError(
            f"Run {run_number} appears in multiple campaigns: {matches}. "
            "Disambiguate by passing campaign=<slug> to reduceSEE()."
        )
    return matches[0]


def _campaign_owns_run(campaign_dir: Path, run_number: int) -> bool:
    """Return True if any artefact in ``campaign_dir`` ties to ``run_number``."""
    # 1. Existing run-attempt manifests are the strongest signal.
    if any((campaign_dir / "manifests").glob(f"run_{run_number}_attempt_*.json")):
        return True

    # 2. Living manifest (only present for manifest-bootstrapped campaigns).
    living = campaign_dir / "manifest.json"
    if living.exists():
        try:
            with living.open("r", encoding="utf-8") as fh:
                m = json.load(fh)
            for run in m.get("runs", []):
                if int(run.get("run_number", -1)) == run_number:
                    return True
        except (OSError, json.JSONDecodeError):
            pass

    # 3. Any run-scoped asset record (SEEMeta, run-specific UB, …).
    assets_index = campaign_dir / "assets_index.jsonl"
    if assets_index.exists():
        try:
            with assets_index.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    # run_number may live at the top level (legacy) or under
                    # applicability.run_number (current asset schema).
                    rn = rec.get("run_number")
                    if rn is None:
                        rn = (rec.get("applicability") or {}).get("run_number")
                    if rn is not None and int(rn) == run_number:
                        return True
        except OSError:
            pass

    return False


def reduceSEE(
    run_number: int,
    *,
    wrap: Any | None = None,
    campaign: int | str | None = None,
    ipts: int | None = None,
    shared_root: str | Path | None = None,
    cheese_loader: Any | None = None,
    rebuild_manifest: bool = False,
    extra_kwargs: dict[str, Any] | None = None,
    **reduce_kwargs: Any,
) -> Any:
    """Smart reduction wrapper — auto-discovers artefacts and calls ``wrap.reduce``.

    The intent is to keep the familiar operator pattern::

        import snapwrap.utils as wrap
        from snapwrap.reduction_artefacts import reduceSEE

        for run in [65891, 65892, 65893]:
            reduceSEE(run, keepUnfocussed=True, verbose=True)

    while delegating all artefact-aware bookkeeping (which bin-mask to load,
    which pixel-mask to apply, which attenuation workspace to use, etc.) to
    the library.

    Behaviour:

    1. If ``ipts`` is not given, it is derived from ``run_number`` via
       ``GetIPTS`` (Mantid must be available).
    2. If ``campaign`` is not given, the run is looked up across every
       campaign registered under that IPTS; exactly one match is required.
    3. The latest run-manifest is reused unless ``rebuild_manifest=True``,
       in which case a new attempt is built first.
    4. The manifest's ``selected_artefacts`` are translated into the correct
       ``wrap.reduce`` keyword arguments (``binMaskList``, ``pixelMaskIndex``,
       ``attenuationWSName``).
    5. ``**reduce_kwargs`` is merged last — anything the caller passes wins,
       so manual overrides remain possible.
    6. ``wrap`` defaults to the ``snapwrap.utils`` module if not provided.

    Args:
        run_number: Run to reduce.
        wrap: Object exposing ``reduce(runNumber, **kwargs)``.  Defaults to
            the ``snapwrap.utils`` module.
        campaign: Campaign slug, alias, or numeric id.  Auto-discovered if
            ``None``.
        ipts: IPTS number.  Derived via ``GetIPTS`` if ``None``.
        shared_root: Override for the IPTS shared root (for tests).
        cheese_loader: Optional custom swiss-cheese loader; the library's
            default uses ``snapwrap.maskUtils.swissCheese`` and works in
            production.
        rebuild_manifest: If ``True``, build a fresh attempt manifest before
            reducing instead of reusing the latest one.
        extra_kwargs: Reserved for advanced use — merged before
            ``**reduce_kwargs``.
        **reduce_kwargs: Passed through to ``wrap.reduce`` (``verbose``,
            ``keepUnfocussed``, ``continueNoDifcal``, ``continueNoVan``,
            and any future kwargs).

    Returns:
        Whatever ``wrap.reduce`` returns.
    """
    from .persistence import _resolve_paths, build_run_manifest, resolve_campaign_slug

    # ── 1. wrap default ──────────────────────────────────────────────────────
    if wrap is None:
        from snapwrap import utils as wrap  # type: ignore[no-redef]

    # ── 2. IPTS ──────────────────────────────────────────────────────────────
    if ipts is None:
        ipts = _resolve_ipts_for_run(run_number)
    log.info("reduceSEE: run=%d  ipts=%d", run_number, ipts)

    # ── 3. campaign ──────────────────────────────────────────────────────────
    if campaign is None:
        campaign_slug = _find_campaign_for_run(
            ipts=ipts, run_number=run_number, shared_root=shared_root,
        )
        log.info("reduceSEE: auto-discovered campaign %r for run %d",
                 campaign_slug, run_number)
    else:
        campaign_slug = resolve_campaign_slug(
            ipts=ipts, campaign_identifier=campaign, shared_root=shared_root,
        )

    # ── 4. locate-or-build manifest ──────────────────────────────────────────
    paths = _resolve_paths(ipts=ipts, campaign_slug=campaign_slug, shared_root=shared_root)
    manifests_dir = paths.campaign_dir / "manifests"
    existing = sorted(manifests_dir.glob(f"run_{run_number}_attempt_*.json"))

    if rebuild_manifest or not existing:
        log.info("reduceSEE: building new manifest attempt (rebuild=%s, prior=%d)",
                 rebuild_manifest, len(existing))
        manifest = build_run_manifest(
            ipts=ipts,
            campaign_identifier=campaign_slug,
            run_number=run_number,
            shared_root=shared_root,
        )
        manifest_path = Path(manifest["manifest_path"])
    else:
        manifest_path = existing[-1]
        log.info("reduceSEE: reusing latest manifest %s", manifest_path.name)

    # ── 5. delegate ──────────────────────────────────────────────────────────
    merged_extra: dict[str, Any] = dict(extra_kwargs or {})
    merged_extra.update(reduce_kwargs)

    # build_reduce_kwargs only recognises a fixed set of kwargs by name; the
    # rest go through extra_kwargs (caller wins).
    direct_keys = {"verbose", "keepUnfocussed", "continueNoDifcal", "continueNoVan"}
    direct = {k: merged_extra.pop(k) for k in list(merged_extra) if k in direct_keys}

    return reduce_from_manifest(
        manifest_path,
        wrap=wrap,
        cheese_loader=cheese_loader,
        extra_kwargs=merged_extra or None,
        **direct,
    )
