"""Data-layer for the Campaign Manager UI.

A thin aggregation layer over :mod:`snapwrap.reduction_artefacts`.  No
duplicated business logic — the model only reshapes backend output into
shapes the Qt table models consume, and adds simple "list all IPTS-level
campaigns" helpers.

This module is deliberately Qt-free so it can be tested without a
QApplication.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from snapwrap.reduction_artefacts import (
    bootstrap_campaign,
    copy_artefact,
    delete_campaign,
    get_campaign_artefact_dir,
    get_campaign_paths,
    ingest_asset,
    list_artefact_records,
    list_asset_records,
    list_campaigns,
    list_crystal_species_records,
    read_jsonl_records,
    register_crystal_species_artefact,
    register_manual_bin_mask_artefact,
    register_pixel_mask_artefact,
    rename_campaign_slug,
    retire_artefact,
)


_IPTS_RE = re.compile(r"^/SNS/SNAP/IPTS-(\d+)/shared/?$")


def _generate_pixel_mask_thumbnail(
    nxs_path: str,
    artefact_id: str,
    artefact_dir: Path,
) -> str | None:
    """Render a 96×192 PNG showing masked pixels for a lite pixel mask.

    Inlines rowCol from maskUtils to avoid that module's top-level Mantid
    imports.  Uses the matplotlib Agg backend directly (no pyplot.show/use)
    so it doesn't interfere with Workbench's live plot backend.

    Returns the PNG path on success, None on any failure (wrong mode,
    missing deps, bad workspace, etc.).
    """
    def _rowcol(spec_id: int) -> tuple[int, int]:
        n_row_mod, n_col_mod = 3, 3
        n_row_pix, n_col_pix = 32, 32
        n_pix = n_row_pix * n_col_pix
        id_mod = spec_id // n_pix
        j_mod = id_mod // n_col_mod
        i_mod = id_mod % n_row_mod
        id_pix = spec_id - id_mod * n_pix
        j_pix = id_pix // n_col_pix
        i_pix = spec_id % n_row_pix
        j_mod = [3, 4, 5, 0, 1, 2].index(j_mod)
        j = j_mod * n_col_pix + j_pix
        i = i_mod * n_row_pix + i_pix
        i = n_row_pix * n_row_mod - i - 1
        return i, j

    try:
        import numpy as np  # type: ignore
        from mantid.simpleapi import Load  # type: ignore
        from mantid.api import AnalysisDataService as ADS  # type: ignore

        ws_name = f"_thumb_{artefact_id}"
        Load(Filename=nxs_path, OutputWorkspace=ws_name)
        ws = ADS.retrieve(ws_name)
        n = ws.getNumberHistograms()
        if n != 18_432:
            ADS.remove(ws_name)
            return None  # rowCol is lite-only

        img = np.zeros((96, 192), dtype=np.float32)
        for spec in range(n):
            if ws.readY(spec)[0] > 0.5:
                row, col = _rowcol(spec)
                img[row, col] = 1.0
        ADS.remove(ws_name)

        # Use the Agg backend directly — avoids calling matplotlib.use()
        # which would clobber Workbench's interactive backend.
        from matplotlib.backends.backend_agg import FigureCanvasAgg  # type: ignore
        from matplotlib.figure import Figure  # type: ignore

        fig = Figure(figsize=(4, 2), dpi=72)
        FigureCanvasAgg(fig)
        ax = fig.add_subplot(111)
        ax.imshow(img, cmap="binary", vmin=0, vmax=1,
                  interpolation="nearest", aspect="equal")
        ax.axis("off")

        png_path = artefact_dir / f"{artefact_id}_thumbnail.png"
        fig.savefig(str(png_path), bbox_inches="tight", pad_inches=0.05, dpi=72)
        return str(png_path)
    except Exception:
        return None


def _is_readable_dir(path: Path) -> bool:
    """Return True iff *path* is a directory the current process can list.

    Survives :class:`PermissionError` raised by ``is_dir`` / ``access`` on
    folders the user cannot stat — these are simply treated as
    inaccessible.  Most IPTS folders fall in this category for non-team
    members on SNS analysis nodes.
    """
    try:
        if not path.is_dir():
            return False
    except (PermissionError, OSError):
        return False
    # R_OK + X_OK is the POSIX combination required to ``ls`` a directory.
    try:
        return os.access(path, os.R_OK | os.X_OK)
    except OSError:
        return False


class CampaignManagerModel:
    """Pure-Python data model for the Campaign Manager."""

    # ── IPTS discovery ───────────────────────────────────────────────

    @staticmethod
    def discoverIPTSList(root: str | Path = "/SNS/SNAP") -> list[int]:
        """Return IPTS numbers that have a *readable* ``shared`` directory.

        IPTS folders the current user cannot access are silently skipped
        — this is the normal case on SNS analysis nodes where a typical
        user only has read access to the proposals they are listed on.

        Returns a sorted descending list so the most recent
        (highest-numbered) IPTS appears first.
        """
        root_path = Path(root)
        if not _is_readable_dir(root_path):
            return []

        out: list[int] = []
        try:
            children = list(root_path.iterdir())
        except (PermissionError, OSError):
            return []

        for child in children:
            name = child.name
            if not name.startswith("IPTS-"):
                continue
            try:
                ipts = int(name.split("-", 1)[1])
            except (IndexError, ValueError):
                continue
            if _is_readable_dir(child / "shared"):
                out.append(ipts)
        out.sort(reverse=True)
        return out

    # ── Campaign mutations ───────────────────────────────────────────

    @staticmethod
    def createCampaign(
        *,
        ipts: int,
        campaign_slug: str,
        assembly_type: str,
        description: str | None = None,
        owners: list[str] | None = None,
        shared_root: str | Path | None = None,
    ) -> dict[str, Any]:
        """Bootstrap a new campaign under an IPTS."""
        return bootstrap_campaign(
            ipts=ipts,
            campaign_slug=campaign_slug,
            assembly_type=assembly_type,
            description=description,
            owners=owners,
            shared_root=shared_root,
        )

    @staticmethod
    def deleteCampaign(
        *,
        ipts: int,
        campaign_identifier: int | str,
        shared_root: str | Path | None = None,
    ) -> dict[str, Any]:
        """Permanently delete a campaign and its entire directory tree."""
        return delete_campaign(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            shared_root=shared_root,
        )

    @staticmethod
    def renameCampaign(
        *,
        ipts: int,
        old_slug: str,
        new_slug: str,
        shared_root: str | Path | None = None,
    ) -> dict[str, Any]:
        """Rename a campaign slug (preserves aliases for backwards lookup)."""
        return rename_campaign_slug(
            ipts=ipts,
            old_slug=old_slug,
            new_slug=new_slug,
            shared_root=shared_root,
        )

    # ── Campaign discovery ───────────────────────────────────────────

    @staticmethod
    def getCampaigns(
        *,
        ipts: int,
        shared_root: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        """List campaigns registered under an IPTS."""
        return list_campaigns(ipts=ipts, shared_root=shared_root)

    # ── Asset queries and mutations ──────────────────────────────────

    @staticmethod
    def getAssets(
        *,
        ipts: int,
        campaign_identifier: int | str,
        shared_root: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        """Return one active record per asset_id — the most recently ingested.

        The backend index is append-only: re-ingesting the same asset_id
        adds a new record with a ``supersedes`` pointer rather than mutating
        the old one.  The backend contract says "resolution at read time uses
        the most recent active record for a given asset_id", so we apply that
        deduplication here so the UI shows one row per logical asset.
        """
        records = list_asset_records(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            shared_root=shared_root,
            status="active",
        )
        # Exclude asset types that are auto-created as provenance side-effects
        # of artefact registration (e.g. the .nxs source file recorded when a
        # pixel mask artefact is registered).  Users never intentionally ingest
        # these — showing them in the Assets panel only causes confusion.
        _SYSTEM_ASSET_TYPES = {"manual_pixel_mask"}
        # Iterate in append order; later records overwrite earlier ones for
        # the same asset_id, leaving only the most recent active entry.
        seen: dict[str, dict[str, Any]] = {}
        for rec in records:
            if rec.get("asset_type") in _SYSTEM_ASSET_TYPES:
                continue
            aid = rec.get("asset_id")
            if aid is not None:
                seen[aid] = rec
        return list(seen.values())

    @staticmethod
    def deleteAsset(
        *,
        ipts: int,
        campaign_identifier: int | str,
        asset_id: str,
        shared_root: str | Path | None = None,
    ) -> int:
        """Hard-delete all records for *asset_id* from the asset JSONL index.

        Rewrites the index atomically (temp file + rename), removing every
        record whose ``asset_id`` matches.  The physical file on disk is not
        touched.  Returns the number of records removed.
        """
        import json as _json

        paths = get_campaign_paths(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            shared_root=shared_root,
        )
        all_records = read_jsonl_records(paths.assets_index)
        keep = [r for r in all_records if r.get("asset_id") != asset_id]
        removed = len(all_records) - len(keep)
        if removed:
            tmp = paths.assets_index.with_suffix(".jsonl.tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                for rec in keep:
                    fh.write(_json.dumps(rec) + "\n")
            tmp.replace(paths.assets_index)
        return removed

    @staticmethod
    def ingestAsset(
        *,
        ipts: int,
        campaign_identifier: int | str,
        source_path: str | Path,
        asset_type: str,
        asset_id: str | None = None,
        applicability_scope: str = "campaign",
        run_number: int | None = None,
        notes: str | None = None,
        shared_root: str | Path | None = None,
    ) -> dict[str, Any]:
        """Copy a file into the managed asset store and register it."""
        return ingest_asset(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            source_path=source_path,
            asset_type=asset_type,
            asset_id=asset_id or None,
            applicability_scope=applicability_scope,
            run_number=run_number,
            notes=notes,
            shared_root=shared_root,
        )

    # ── Artefact creation ────────────────────────────────────────────

    @staticmethod
    def registerPixelMask(
        *,
        ipts: int,
        campaign_identifier: int | str,
        method: str,
        ws_name: str,
        is_lite: bool,
        nxs_path: str | None = None,
        ads_workspace: str | None = None,
        run_number: int | None = None,
        notes: str | None = None,
        shared_root: str | Path | None = None,
    ) -> dict[str, Any]:
        """Register a pixel mask artefact, auto-generating a versioned artefact ID.

        Three sources are supported via *method*:

        ``"pixel_mask.letterbox"``
            Uses the standard PE mask at the canonical path.  No extra
            inputs required.
        ``"pixel_mask.custom"``
            Registers an existing ``.nxs`` file given by *nxs_path*.
        ``"pixel_mask.workspace"``
            Saves the named ADS workspace (*ads_workspace*) into the
            campaign artefact directory as ``.nxs`` then registers it.

        For all methods the workspace is (or will be) loaded into
        *ws_name* during reduction.  The histogram count of the mask is
        validated against the expected lite (18 432) or native (1 179 648)
        pixel count and an error is raised on mismatch.

        The artefact ID is auto-generated as
        ``pixmask-{source}-{lite|native}[-vN]`` where ``-vN`` is appended
        if the base ID is already taken.
        """
        from snapwrap.reduction_artefacts.masking import STANDARD_PE_MASK_PATH

        _LITE_N = 18_432
        _NATIVE_N = 1_179_648
        lite_tag = "lite" if is_lite else "native"

        # ── Resolve / save the .nxs file ─────────────────────────────────
        if method == "pixel_mask.letterbox":
            resolved_path = str(STANDARD_PE_MASK_PATH)
        elif method == "pixel_mask.custom":
            if not nxs_path:
                raise ValueError("nxs_path is required for pixel_mask.custom")
            resolved_path = nxs_path
        elif method == "pixel_mask.workspace":
            if not ads_workspace:
                raise ValueError("ads_workspace is required for pixel_mask.workspace")
            artefact_dir = get_campaign_artefact_dir(
                ipts=ipts,
                campaign_identifier=campaign_identifier,
                shared_root=shared_root,
            )
            safe_stem = re.sub(r"[^a-z0-9_-]", "_", ads_workspace.lower())
            save_path = artefact_dir / f"pixmask_ws_{safe_stem}_{lite_tag}.nxs"
            from mantid.simpleapi import SaveNexus  # type: ignore
            SaveNexus(InputWorkspace=ads_workspace, Filename=str(save_path))
            resolved_path = str(save_path)
            # Switch method to custom for the registration call
            method = "pixel_mask.custom"
        else:
            raise ValueError(f"Unknown method: {method!r}")

        # ── Validate lite/native compatibility ────────────────────────────
        # Use Load (generic auto-detector) rather than LoadMask: .nxs mask
        # files (including PEMask.nxs) are Nexus-format workspaces and are
        # rejected by LoadMask which only handles XML and ISIS .msk files.
        try:
            from mantid.simpleapi import Load  # type: ignore
            from mantid.api import AnalysisDataService as ADS  # type: ignore

            _tmp = f"_pixmask_validate_{id(resolved_path)}"
            Load(Filename=resolved_path, OutputWorkspace=_tmp)
            n = ADS.retrieve(_tmp).getNumberHistograms()
            ADS.remove(_tmp)
            expected = _LITE_N if is_lite else _NATIVE_N
            if n != expected:
                actual_mode = "lite" if n == _LITE_N else ("native" if n == _NATIVE_N else f"{n}-pixel")
                raise ValueError(
                    f"Mask has {n} pixels ({actual_mode}) but isLite={is_lite} "
                    f"({lite_tag}, expected {expected}). "
                    "Lite and native masks are incompatible."
                )
        except ImportError:
            pass  # Not in a Mantid environment — skip validation

        # ── Auto-generate versioned artefact ID ───────────────────────────
        if method == "pixel_mask.letterbox":
            base_id = f"pixmask-pe-{lite_tag}"
        elif method == "pixel_mask.custom":
            stem = re.sub(r"[^a-z0-9-]", "-", Path(resolved_path).stem.lower())
            base_id = f"pixmask-{stem}-{lite_tag}"
        else:  # workspace (already reassigned to custom above)
            safe_stem = re.sub(r"[^a-z0-9-]", "-", (ads_workspace or "ws").lower())
            base_id = f"pixmask-ws-{safe_stem}-{lite_tag}"

        existing_ids = {
            rec.get("artefact_id")
            for rec in list_artefact_records(
                ipts=ipts,
                campaign_identifier=campaign_identifier,
                artefact_type="pixel_mask",
                shared_root=shared_root,
            )
        }
        artefact_id = base_id
        version = 2
        while artefact_id in existing_ids:
            artefact_id = f"{base_id}-v{version}"
            version += 1

        record = register_pixel_mask_artefact(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            artefact_id=artefact_id,
            nxs_path=resolved_path,
            method=method,
            ws_name=ws_name,
            run_number=run_number,
            notes=notes,
            shared_root=shared_root,
        )

        # Generate thumbnail for lite masks (rowCol is lite-only).
        if is_lite:
            artefact_dir_p = get_campaign_artefact_dir(
                ipts=ipts,
                campaign_identifier=campaign_identifier,
                shared_root=shared_root,
            )
            thumb = _generate_pixel_mask_thumbnail(resolved_path, artefact_id, artefact_dir_p)
            if thumb:
                record["thumbnail_path"] = thumb

        return record

    @staticmethod
    def registerBinMaskFromTransmission(
        *,
        ipts: int,
        campaign_identifier: int | str,
        run_number: int,
        lam_min: float | None = None,
        lam_max: float | None = None,
        dip_threshold: float = 0.98,
        keep_diagnostics: bool = True,
        monitor2_l2: float | None = None,
        shared_root: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        """Build a bin mask from the transmission monitor and register it.

        Monitor data lives in the native NeXus file; the resulting mask encodes
        wavelength-space notch positions that are independent of lite/native
        detector binning.  ``is_lite=True`` is passed to the backend so the
        spectraLst covers the standard SNAP DAC lite-mode pixel set.

        Calls ``build_swiss_cheese_from_transmission_monitor`` (Mantid
        required) to detect notch positions, saves the mask JSON to the
        campaign artefact directory, then registers each output file as an
        artefact.  Returns a list of registered artefact records (one per
        saved JSON file).
        """
        from snapwrap.reduction_artefacts.masking import (  # type: ignore
            build_swiss_cheese_from_transmission_monitor,
        )

        artefact_dir = get_campaign_artefact_dir(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            shared_root=shared_root,
        )
        file_prefix = f"binmask_monitor_run{run_number}"

        json_paths, notches, diag_png = build_swiss_cheese_from_transmission_monitor(
            run_number=run_number,
            is_lite=True,
            output_dir=artefact_dir,
            file_prefix=file_prefix,
            ipts=ipts,
            lam_min=lam_min,
            lam_max=lam_max,
            dip_threshold=dip_threshold,
            keep_diagnostics=keep_diagnostics,
            monitor2_l2=monitor2_l2,
        )

        # Collect existing artefact IDs to drive version bump.
        existing_ids = {
            rec.get("artefact_id")
            for rec in list_artefact_records(
                ipts=ipts,
                campaign_identifier=campaign_identifier,
                artefact_type="bin_mask",
                shared_root=shared_root,
            )
        }

        records = []
        base_id = f"binmask-monitor-run{run_number}"
        for json_path in json_paths:
            artefact_id = base_id
            version = 2
            while artefact_id in existing_ids:
                artefact_id = f"{base_id}-v{version}"
                version += 1
            existing_ids.add(artefact_id)

            record = register_manual_bin_mask_artefact(
                ipts=ipts,
                campaign_identifier=campaign_identifier,
                artefact_id=artefact_id,
                mask_json_path=str(json_path),
                run_number=run_number,
                shared_root=shared_root,
                method="bin_mask.from_transmission",
                metadata={
                    "notches": [[float(lo), float(hi)] for lo, hi in notches],
                    **({"monitor2_l2_override": float(monitor2_l2)} if monitor2_l2 is not None else {}),
                },
                thumbnail_path=str(diag_png) if diag_png is not None else None,
            )
            records.append(record)

        return records

    @staticmethod
    def registerManualNotchMask(
        *,
        ipts: int,
        campaign_identifier: int | str,
        notches: list[list[float]],
        units: str = "Wavelength",
        is_lite: bool = True,
        run_number: int | None = None,
        notes: str | None = None,
        shared_root: str | Path | None = None,
    ) -> dict[str, Any]:
        """Build and register a bin mask from a manually entered notch list.

        Calls ``build_swiss_cheese_from_notch_list`` (no Mantid detectors
        needed — pure JSON construction) and registers the result.
        Returns the registered artefact record.
        """
        from snapwrap.reduction_artefacts.masking import (  # type: ignore
            build_swiss_cheese_from_notch_list,
        )

        artefact_dir = get_campaign_artefact_dir(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            shared_root=shared_root,
        )
        file_prefix = (
            f"binmask_manual_run{run_number}"
            if run_number is not None
            else "binmask_manual_campaign"
        )

        json_paths = build_swiss_cheese_from_notch_list(
            notches=notches,
            units=units,
            is_lite=is_lite,
            output_dir=artefact_dir,
            file_prefix=file_prefix,
        )

        existing_ids = {
            rec.get("artefact_id")
            for rec in list_artefact_records(
                ipts=ipts,
                campaign_identifier=campaign_identifier,
                artefact_type="bin_mask",
                shared_root=shared_root,
            )
        }

        base_id = (
            f"binmask-manual-run{run_number}"
            if run_number is not None
            else "binmask-manual-campaign"
        )
        records = []
        for json_path in json_paths:
            artefact_id = base_id
            version = 2
            while artefact_id in existing_ids:
                artefact_id = f"{base_id}-v{version}"
                version += 1
            existing_ids.add(artefact_id)

            record = register_manual_bin_mask_artefact(
                ipts=ipts,
                campaign_identifier=campaign_identifier,
                artefact_id=artefact_id,
                mask_json_path=str(json_path),
                run_number=run_number,
                shared_root=shared_root,
                method="bin_mask.manual_entry",
                metadata={"notches": [[float(lo), float(hi)] for lo, hi in notches]},
                notes=notes,
            )
            records.append(record)

        return records[0] if len(records) == 1 else records

    @staticmethod
    def registerBinMaskFromWorkspaceHistory(
        *,
        ipts: int,
        campaign_identifier: int | str,
        ws_name: str,
        run_number: int | None = None,
        notes: str | None = None,
        shared_root: str | Path | None = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """Extract MaskBins history from an ADS workspace and register it as a bin mask.

        Calls ``extractFromWorkspaceHistory`` on *ws_name* to reconstruct the
        notch list from the workspace's Mantid algorithm history, saves the
        swiss-cheese JSON to the campaign artefact directory, and registers it.
        """
        from snapwrap.reduction_artefacts.masking import (  # type: ignore
            build_swiss_cheese_from_workspace_history,
        )

        artefact_dir = get_campaign_artefact_dir(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            shared_root=shared_root,
        )
        safe_stem = re.sub(r"[^a-z0-9_-]", "_", ws_name.lower())
        file_prefix = (
            f"binmask_ws_{safe_stem}_run{run_number}"
            if run_number is not None
            else f"binmask_ws_{safe_stem}"
        )

        json_paths = build_swiss_cheese_from_workspace_history(
            ws_name=ws_name,
            output_dir=artefact_dir,
            file_prefix=file_prefix,
        )

        existing_ids = {
            rec.get("artefact_id")
            for rec in list_artefact_records(
                ipts=ipts,
                campaign_identifier=campaign_identifier,
                artefact_type="bin_mask",
                shared_root=shared_root,
            )
        }

        safe_id = re.sub(r"[^a-z0-9-]", "-", ws_name.lower())
        base_id = (
            f"binmask-ws-{safe_id}-run{run_number}"
            if run_number is not None
            else f"binmask-ws-{safe_id}"
        )
        records = []
        for json_path in json_paths:
            artefact_id = base_id
            version = 2
            while artefact_id in existing_ids:
                artefact_id = f"{base_id}-v{version}"
                version += 1
            existing_ids.add(artefact_id)

            record = register_manual_bin_mask_artefact(
                ipts=ipts,
                campaign_identifier=campaign_identifier,
                artefact_id=artefact_id,
                mask_json_path=str(json_path),
                run_number=run_number,
                shared_root=shared_root,
                method="bin_mask.from_workspace_history",
                metadata={"source_workspace": ws_name},
                notes=notes,
            )
            records.append(record)

        return records[0] if len(records) == 1 else records

    @staticmethod
    def registerBinMaskFromJsonFile(
        *,
        ipts: int,
        campaign_identifier: int | str,
        json_path: str | Path,
        run_number: int | None = None,
        notes: str | None = None,
        shared_root: str | Path | None = None,
    ) -> dict[str, Any]:
        """Load a swiss-cheese JSON saved by ``swissCheese.save()`` and register it.

        Copies the file into the campaign artefact directory, calls
        ``swissCheese.load()`` to validate it, and calls
        ``swissCheese.makeMaskBinsTables()`` to leave ``maskBins_*`` table
        workspaces in the Mantid ADS ready for use.  Returns the registered
        artefact record.
        """
        from snapwrap.reduction_artefacts.masking import (  # type: ignore
            build_swiss_cheese_from_json_file,
        )

        json_path = Path(json_path)
        artefact_dir = get_campaign_artefact_dir(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            shared_root=shared_root,
        )
        safe_stem = re.sub(r"[^a-z0-9_-]", "_", json_path.stem.lower())
        file_prefix = (
            f"binmask_json_{safe_stem}_run{run_number}"
            if run_number is not None
            else f"binmask_json_{safe_stem}"
        )

        json_paths = build_swiss_cheese_from_json_file(
            json_path=json_path,
            output_dir=artefact_dir,
            file_prefix=file_prefix,
        )

        existing_ids = {
            rec.get("artefact_id")
            for rec in list_artefact_records(
                ipts=ipts,
                campaign_identifier=campaign_identifier,
                artefact_type="bin_mask",
                shared_root=shared_root,
            )
        }

        safe_id = re.sub(r"[^a-z0-9-]", "-", json_path.stem.lower())
        base_id = (
            f"binmask-json-{safe_id}-run{run_number}"
            if run_number is not None
            else f"binmask-json-{safe_id}"
        )
        artefact_id = base_id
        version = 2
        while artefact_id in existing_ids:
            artefact_id = f"{base_id}-v{version}"
            version += 1

        return register_manual_bin_mask_artefact(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            artefact_id=artefact_id,
            mask_json_path=str(json_paths[0]),
            run_number=run_number,
            shared_root=shared_root,
            method="bin_mask.from_json_file",
            metadata={"source_file": str(json_path)},
            notes=notes,
        )

    # ── Post-processing ──────────────────────────────────────────────

    @staticmethod
    def postprocessCrop(
        *,
        ipts: int,
        campaign_identifier: int | str,
        run_number: int,
        is_lite: bool,
        source_prefix: str = "reduced",
        diagnostics: bool = False,
        edge_bins: int = 0,
        min_coverage: float = 0.002,
        force_recompute: bool = False,
        shared_root: str | Path | None = None,
    ) -> str:
        """Crop notch-mask gaps from reduced/resampled workspaces.

        By default, if an active crop artefact already exists for this run
        whose stored parameters (bin masks, edge_bins, min_coverage) match
        the requested values, the stored gap map is re-applied directly
        without recomputing.  Set *force_recompute* to bypass this and
        always regenerate from scratch (retiring the old artefact first).

        End-gaps (at spectrum edges) are removed with ``CropWorkspaceRagged``;
        interior gaps are set to ``NaN``.

        Returns a log string summarising the operation (captured stdout from
        the underlying computation).
        """
        import contextlib
        import io
        import json

        from snapwrap.reduction_artefacts.persistence import (  # type: ignore
            list_artefact_records,
            register_cropped_workspace_artefact,
            retire_crop_artefacts,
        )
        from snapwrap.reduction_artefacts.postprocessing import (  # type: ignore
            apply_dspace_gaps,
            compute_dspace_gaps,
        )
        from snapwrap.utils import workspaceHandles  # type: ignore

        # ── Collect active bin-mask artefacts for this run ────────────
        bin_mask_records = list_artefact_records(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            run_number=run_number,
            artefact_type="bin_mask",
            status="active",
            shared_root=shared_root,
        )
        if not bin_mask_records:
            raise RuntimeError(
                f"No active bin-mask artefacts found for run {run_number}. "
                "Register a bin mask before cropping."
            )
        mask_paths = [rec["path"] for rec in bin_mask_records if rec.get("path")]
        if not mask_paths:
            raise RuntimeError(
                f"Active bin-mask artefact(s) found for run {run_number} but none "
                "have a 'path' field — check the artefact records."
            )
        applied_mask_ids = [r["artefact_id"] for r in bin_mask_records]

        # ── Try to reuse an existing matching crop artefact ───────────
        if not force_recompute:
            existing_crop = [
                r for r in list_artefact_records(
                    ipts=ipts,
                    campaign_identifier=campaign_identifier,
                    run_number=run_number,
                    status="active",
                    shared_root=shared_root,
                )
                if r.get("method") == "crop.notch_gaps"
            ]
            reuse_map: dict[str, tuple[str, list]] = {}
            for rec in existing_crop:
                meta = rec.get("metadata", {})
                if (
                    sorted(rec.get("input_asset_ids", [])) == sorted(applied_mask_ids)
                    and meta.get("edge_bins") == edge_bins
                    and abs(float(meta.get("min_coverage", -1.0)) - min_coverage) < 1e-9
                ):
                    group = meta.get("focus_group", "")
                    gap_path = rec.get("path", "")
                    if group and group not in reuse_map and gap_path and Path(gap_path).exists():
                        gap_json = json.loads(Path(gap_path).read_text(encoding="utf-8"))
                        gaps_for_group: list[list[tuple[float, float]]] = [
                            [tuple(g) for g in spec]  # type: ignore[misc]
                            for spec in gap_json.get(group, [])
                        ]
                        reuse_map[group] = (rec["artefact_id"], gaps_for_group)

            if reuse_map:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    handles = workspaceHandles(prefix=source_prefix, runNumber=run_number) or []
                    reused_ids: list[str] = []
                    for handle in handles:
                        group = handle.pixelGroup
                        if group not in reuse_map:
                            print(f"WARNING: no stored gap map for group '{group}' — skipping")
                            continue
                        aid, gaps_reuse = reuse_map[group]
                        out_ws = f"cropped_dsp_{group}_{run_number}"
                        apply_dspace_gaps(handle.wsName, gaps_reuse, out_ws)
                        print(f"Group '{group}': reused stored gap map from artefact '{aid}'")
                        reused_ids.append(aid)
                if not reused_ids:
                    raise RuntimeError(
                        f"No {source_prefix} workspaces found in ADS for run {run_number}."
                    )
                ids = ", ".join(reused_ids)
                return buf.getvalue() + f"\nReused {len(reused_ids)} existing crop artefact(s): {ids}.\n"

        # ── Recompute: retire existing crop artefacts first ───────────
        artefact_dir = get_campaign_artefact_dir(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            shared_root=shared_root,
        )
        artefact_dir.mkdir(parents=True, exist_ok=True)

        n_retired = retire_crop_artefacts(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            run_number=run_number,
            shared_root=shared_root,
        )

        # ── Compute gaps and apply; capture all print output ──────────
        registered: list[dict[str, Any]] = []
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            if n_retired:
                print(f"Retired {n_retired} previous crop artefact(s) for run {run_number}.")
            gap_map = compute_dspace_gaps(
                run_number=run_number,
                is_lite=is_lite,
                bin_mask_paths=mask_paths,
                diagnostics=diagnostics,
                edge_bins=edge_bins,
                min_coverage=min_coverage,
            )
            if not gap_map:
                raise RuntimeError("Gap computation returned no results.")

            handles = workspaceHandles(prefix=source_prefix, runNumber=run_number) or []

            for handle in handles:
                group = handle.pixelGroup
                if group not in gap_map:
                    continue
                gaps = gap_map[group]
                out_ws = f"cropped_dsp_{group}_{run_number}"
                apply_dspace_gaps(handle.wsName, gaps, out_ws)

                gap_file = artefact_dir / f"gap_map_{group}_{run_number}.json"
                gap_file.write_text(
                    json.dumps(
                        {group: [[list(g) for g in spec] for spec in gaps]}, indent=2
                    ),
                    encoding="utf-8",
                )

                record = register_cropped_workspace_artefact(
                    ipts=ipts,
                    campaign_identifier=campaign_identifier,
                    artefact_id=f"crop-{group}-{run_number}",
                    ws_name=out_ws,
                    source_ws_name=handle.wsName,
                    run_number=run_number,
                    focus_group=group,
                    gap_map_path=str(gap_file),
                    applied_bin_mask_ids=applied_mask_ids,
                    metadata={"edge_bins": edge_bins, "min_coverage": min_coverage},
                    shared_root=shared_root,
                )
                registered.append(record)

        if not registered:
            raise RuntimeError(
                f"No {source_prefix} workspaces found in ADS for run {run_number}."
            )

        ids = ", ".join(r.get("artefact_id", "?") for r in registered)
        return buf.getvalue() + f"\nRegistered {len(registered)} artefact(s): {ids}.\n"

    @staticmethod
    def retireCropArtefacts(
        *,
        ipts: int,
        campaign_identifier: int | str,
        run_number: int | None = None,
        shared_root: str | Path | None = None,
    ) -> str:
        """Archive all crop.notch_gaps artefacts for the given run (or all runs)."""
        from snapwrap.reduction_artefacts.persistence import retire_crop_artefacts  # type: ignore

        n = retire_crop_artefacts(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            run_number=run_number,
            shared_root=shared_root,
        )
        scope = f"run {run_number}" if run_number is not None else "all runs"
        return f"Retired {n} crop artefact(s) for {scope}."

    @staticmethod
    def postprocessResample(
        *,
        run_number: int | None = None,
        sample_factor: float = 1.0,
        units: str = "dsp",
    ) -> str:
        """Resample reduced workspaces using RebinRagged.

        Wraps ``snapwrap.utils.resample``.  stdout is captured and returned
        so the caller can display it in a log widget.
        """
        import contextlib
        import io

        from snapwrap.utils import resample  # type: ignore

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            resample(
                sampleFactor=sample_factor,
                prefix="reduced",
                units=units,
                runNumber=run_number,
            )
        return buf.getvalue()

    # ── Run queries ──────────────────────────────────────────────────

    @staticmethod
    def getRunSummaries(
        *,
        ipts: int,
        campaign_identifier: int | str,
        shared_root: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        """Derive a per-run summary from the campaign's *active* artefact records.

        Returns one dict per distinct ``run_context.run_number``, sorted
        descending (most recent run first):

        ``{"run_number": int, "artefact_count": int, "artefact_types": list[str]}``

        Records without a ``run_context.run_number`` are skipped.
        Only ``status == "active"`` records are counted.
        """
        records = list_artefact_records(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            shared_root=shared_root,
            status="active",
        )
        runs: dict[int, dict[str, Any]] = {}
        for rec in records:
            rc = rec.get("run_context") or {}
            rn = rc.get("run_number")
            if not isinstance(rn, int):
                continue
            if rn not in runs:
                runs[rn] = {"run_number": rn, "artefact_count": 0, "artefact_types": set()}
            runs[rn]["artefact_count"] += 1
            atype = rec.get("artefact_type")
            if atype:
                runs[rn]["artefact_types"].add(atype)

        # Crystal species are in a separate index — include run-scoped ones.
        cs_records = list_crystal_species_records(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            shared_root=shared_root,
        )
        for rec in cs_records:
            rn = rec.get("source_run")
            if not isinstance(rn, int):
                continue
            if rn not in runs:
                runs[rn] = {"run_number": rn, "artefact_count": 0, "artefact_types": set()}
            runs[rn]["artefact_count"] += 1
            runs[rn]["artefact_types"].add("crystal_species")

        # Convert sets to sorted lists for stable display
        for entry in runs.values():
            entry["artefact_types"] = sorted(entry["artefact_types"])
        return sorted(runs.values(), key=lambda x: x["run_number"], reverse=True)

    # ── Artefact queries ─────────────────────────────────────────────

    @staticmethod
    def getArtefacts(
        *,
        ipts: int,
        campaign_identifier: int | str,
        shared_root: str | Path | None = None,
        artefact_type: str | None = None,
        status: str | None = None,
        run_number: int | None = None,
    ) -> list[dict[str, Any]]:
        """List artefacts for a campaign with optional filters.

        Crystal species are stored in a separate index (`crystal_species_index.jsonl`)
        but are surfaced here normalised to the same record shape as regular artefacts
        so the Artefacts panel can display them in one table.
        """
        records = list_artefact_records(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            shared_root=shared_root,
            artefact_type=artefact_type,
            status=status,
            run_number=run_number,
        )

        # Crystal species live in a separate index — include them unless the
        # caller explicitly asked for a type that isn't crystal_species.
        if artefact_type is None or artefact_type == "crystal_species":
            # status filter: crystal species have no status field; treat them
            # as always "active" and exclude only when the caller wants retired.
            if status is None or status == "active":
                cs_records = list_crystal_species_records(
                    ipts=ipts,
                    campaign_identifier=campaign_identifier,
                    shared_root=shared_root,
                    source_run=run_number,
                )
                for rec in cs_records:
                    records.append({
                        "artefact_id": rec.get("record_id", ""),
                        "artefact_type": "crystal_species",
                        "status": "active",
                        "run_context": {"run_number": rec.get("source_run")},
                        "method": "crystal_species.register",
                        "created_at": rec.get("timestamp", ""),
                        "created_by": rec.get("created_by", ""),
                        "notes": rec.get("species_name", ""),
                        # Preserve full original record for detail views.
                        "_crystal_species": rec,
                    })

        # Attach thumbnail_path to pixel_mask records where the PNG exists.
        # Thumbnails are stored at a predictable path in the artefact dir,
        # so this works for records registered in previous sessions too.
        try:
            artefact_dir_p = get_campaign_artefact_dir(
                ipts=ipts,
                campaign_identifier=campaign_identifier,
                shared_root=shared_root,
            )
            for rec in records:
                if rec.get("artefact_type") == "pixel_mask" and "thumbnail_path" not in rec:
                    aid = rec.get("artefact_id", "")
                    if aid:
                        thumb = artefact_dir_p / f"{aid}_thumbnail.png"
                        if thumb.exists():
                            rec["thumbnail_path"] = str(thumb)
        except Exception:
            pass

        return records

    # ── Artefact mutations ───────────────────────────────────────────

    @staticmethod
    def retireArtefact(
        *,
        ipts: int,
        campaign_identifier: int | str,
        artefact_id: str,
        shared_root: str | Path | None = None,
    ) -> int:
        """Retire all active records with the given artefact_id.

        Returns the number of records updated from ``active`` → ``retired``.
        """
        return retire_artefact(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            artefact_id=artefact_id,
            shared_root=shared_root,
        )

    @staticmethod
    def deleteCrystalSpecies(
        *,
        ipts: int,
        campaign_identifier: int | str,
        record_id: str,
        shared_root: str | Path | None = None,
    ) -> int:
        """Hard-delete a crystal species by record_id from crystal_species_index.jsonl.

        Crystal species records have no ``status`` field, so soft-retire is not
        possible without backend changes.  This rewrites the index atomically
        (temp file + rename), removing every record whose ``record_id`` matches.
        Returns the number of records removed.
        """
        import json as _json

        paths = get_campaign_paths(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            shared_root=shared_root,
        )
        all_records = read_jsonl_records(paths.crystal_species_index)
        keep = [r for r in all_records if r.get("record_id") != record_id]
        removed = len(all_records) - len(keep)
        if removed:
            tmp = paths.crystal_species_index.with_suffix(".jsonl.tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                for rec in keep:
                    fh.write(_json.dumps(rec) + "\n")
            tmp.replace(paths.crystal_species_index)
        return removed

    @staticmethod
    def copyCrystalSpeciesToCampaign(
        *,
        cs_record: dict[str, Any],
        target_ipts: int,
        target_campaign: str,
        shared_root: str | Path | None = None,
    ) -> dict[str, Any]:
        """Copy a crystal species to another campaign.

        Ingests the CIF file into the target campaign's asset store, reads
        the source EOS JSON (if present), then registers a new species record
        in the target campaign.  The ``source_run`` is not carried over —
        the copied species is campaign-wide in the target.
        """
        import json as _json

        cif_path = cs_record.get("cifPath", "")
        eos_path_src = cs_record.get("eosPath")
        species_name = cs_record.get("species_name", "")
        role = cs_record.get("role", "sample")

        new_cif_path = cif_path
        if cif_path:
            cif_rec = ingest_asset(
                ipts=target_ipts,
                campaign_identifier=target_campaign,
                source_path=cif_path,
                asset_type="cif",
                shared_root=shared_root,
            )
            new_cif_path = cif_rec.get("path", cif_path)

        eos_params: dict[str, Any] | None = None
        if eos_path_src:
            try:
                eos_params = _json.loads(
                    Path(eos_path_src).read_text(encoding="utf-8")
                )
            except Exception:
                pass

        return CampaignManagerModel.registerCrystalSpecies(
            ipts=target_ipts,
            campaign_identifier=target_campaign,
            species_name=species_name,
            cif_path=new_cif_path,
            role=role,
            eos_params=eos_params,
            source_run=None,
            shared_root=shared_root,
        )

    @staticmethod
    def registerCrystalSpecies(
        *,
        ipts: int,
        campaign_identifier: int | str,
        species_name: str,
        cif_path: str,
        role: str = "sample",
        eos_params: dict | None = None,
        source_run: int | None = None,
        shared_root: str | Path | None = None,
    ) -> dict[str, Any]:
        """Register a crystal species artefact from a CIF (+ optional inline EOS).

        If *eos_params* is provided the dict is written as a ``.eos.json``
        file to the campaign artefact directory.  ``stability_pressure`` and
        ``stability_temperature`` keys are preserved in the file for future
        post-reduction use but are not consumed by the backend today.
        """
        import json as _json

        eos_path: str | None = None
        if eos_params:
            artefact_dir = get_campaign_artefact_dir(
                ipts=ipts,
                campaign_identifier=campaign_identifier,
                shared_root=shared_root,
            )
            safe_name = re.sub(r"[^a-z0-9_-]", "_", species_name.lower())
            eos_file = artefact_dir / f"eos_{safe_name}.json"
            eos_file.write_text(_json.dumps(eos_params, indent=2), encoding="utf-8")
            eos_path = str(eos_file)

        return register_crystal_species_artefact(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            species_name=species_name,
            cif_path=cif_path,
            role=role,
            eos_path=eos_path,
            source_run=source_run,
            shared_root=shared_root,
        )

    @staticmethod
    def copyArtefact(
        *,
        ipts: int,
        campaign_identifier: int | str,
        source_artefact_id: str,
        new_artefact_id: str,
        run_number: int | None = None,
        shared_root: str | Path | None = None,
        copy_file: bool = False,
        notes: str | None = None,
        created_by: str = "operator",
    ) -> dict[str, Any]:
        """Register a new artefact as a copy of an existing one."""
        return copy_artefact(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            source_artefact_id=source_artefact_id,
            new_artefact_id=new_artefact_id,
            run_number=run_number,
            shared_root=shared_root,
            copy_file=copy_file,
            notes=notes,
            created_by=created_by,
        )
