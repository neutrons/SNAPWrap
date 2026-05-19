"""Data-layer for the Campaign Manager UI.

A thin aggregation layer over :mod:`snapwrap.reduction_artefacts`.  No
duplicated business logic — the model only reshapes backend output into
shapes the Qt table models consume, and adds simple "list all IPTS-level
campaigns" helpers.

This module is deliberately Qt-free so it can be tested without a
QApplication.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from snapwrap.reduction_artefacts import (
    list_artefact_records,
    list_campaigns,
)


_IPTS_RE = re.compile(r"^/SNS/SNAP/IPTS-(\d+)/shared/?$")


class CampaignManagerModel:
    """Pure-Python data model for the Campaign Manager."""

    # ── IPTS discovery ───────────────────────────────────────────────

    @staticmethod
    def discoverIPTSList(root: str | Path = "/SNS/SNAP") -> list[int]:
        """Return IPTS numbers that have an existing ``shared`` directory.

        Used by the IPTS picker; returns a sorted descending list so the
        most recent (highest-numbered) IPTS appears first.
        """
        root_path = Path(root)
        if not root_path.exists():
            return []
        out: list[int] = []
        for child in root_path.iterdir():
            if not child.is_dir():
                continue
            name = child.name
            if not name.startswith("IPTS-"):
                continue
            try:
                ipts = int(name.split("-", 1)[1])
            except (IndexError, ValueError):
                continue
            if (child / "shared").is_dir():
                out.append(ipts)
        out.sort(reverse=True)
        return out

    # ── Campaign discovery ───────────────────────────────────────────

    @staticmethod
    def getCampaigns(
        *,
        ipts: int,
        shared_root: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        """List campaigns registered under an IPTS."""
        return list_campaigns(ipts=ipts, shared_root=shared_root)

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
