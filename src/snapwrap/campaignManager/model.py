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
    ingest_asset,
    list_artefact_records,
    list_asset_records,
    list_campaigns,
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
        artefact_id: str,
        nxs_path: str,
        method: str,
        ws_name: str,
        run_number: int | None = None,
        notes: str | None = None,
        shared_root: str | Path | None = None,
    ) -> dict[str, Any]:
        """Register a pixel mask artefact from an existing .nxs file."""
        return register_pixel_mask_artefact(
            ipts=ipts,
            campaign_identifier=campaign_identifier,
            artefact_id=artefact_id,
            nxs_path=nxs_path,
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
