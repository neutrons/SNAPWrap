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
    get_campaign_artefact_dir,
    ingest_asset,
    list_artefact_records,
    list_asset_records,
    list_campaigns,
    register_crystal_species_artefact,
    register_pixel_mask_artefact,
    retire_artefact,
)


_IPTS_RE = re.compile(r"^/SNS/SNAP/IPTS-(\d+)/shared/?$")


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
        # Iterate in append order; later records overwrite earlier ones for
        # the same asset_id, leaving only the most recent active entry.
        seen: dict[str, dict[str, Any]] = {}
        for rec in records:
            aid = rec.get("asset_id")
            if aid is not None:
                seen[aid] = rec
        return list(seen.values())

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

        return register_pixel_mask_artefact(
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
        """List artefacts for a campaign with optional filters."""
        return list_artefact_records(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            shared_root=shared_root,
            artefact_type=artefact_type,
            status=status,
            run_number=run_number,
        )

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
    def registerCrystalSpecies(
        *,
        ipts: int,
        campaign_identifier: int | str,
        species_name: str,
        cif_path: str,
        role: str = "sample",
        eos_path: str | None = None,
        source_run: int | None = None,
        shared_root: str | Path | None = None,
    ) -> dict[str, Any]:
        """Register a crystal species artefact from a CIF (+ optional EOS) file."""
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
