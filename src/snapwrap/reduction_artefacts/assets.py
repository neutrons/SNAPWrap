"""Typed asset containers for heterogeneous reduction asset payloads.

Phase 3 persistence stores assets as JSON records. This module provides a
small typed layer so callers can work with strongly-typed metadata while still
supporting arbitrary runtime payload objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Generic, TypeVar


class AssetType(StrEnum):
    """Supported persisted asset types for reduction artefact workflows."""

    CIF = "cif"
    EOS_DESCRIPTION = "eos_description"
    UB_MATRIX = "ub_matrix"
    SEEMETA_JSON = "seemeta_json"
    MANUAL_PIXEL_MASK = "manual_pixel_mask"
    OTHER = "other"


class AssetStatus(StrEnum):
    """Lifecycle status for a persisted asset record."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    INVALID = "invalid"
    ARCHIVED = "archived"


class ApplicabilityScope(StrEnum):
    """Scope indicating whether an asset applies campaign-wide or per-run."""

    CAMPAIGN = "campaign"
    RUN = "run"


@dataclass(frozen=True)
class AssetApplicability:
    """Run/campaign applicability metadata for an asset."""

    scope: ApplicabilityScope = ApplicabilityScope.CAMPAIGN
    run_number: int | None = None

    def __post_init__(self) -> None:
        if self.scope == ApplicabilityScope.RUN and (self.run_number is None or self.run_number < 1):
            raise ValueError("run applicability requires run_number >= 1")
        if self.scope == ApplicabilityScope.CAMPAIGN and self.run_number is not None:
            raise ValueError("campaign applicability must not define run_number")

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope.value,
            "run_number": self.run_number,
        }


@dataclass(frozen=True)
class AssetRecord:
    """Typed representation of a persisted asset record."""

    record_id: str
    timestamp: str
    campaign_id: int
    campaign_slug: str
    ipts: int
    asset_id: str
    asset_type: AssetType
    version: int
    status: AssetStatus
    path: str
    provenance: dict[str, Any]
    applicability: AssetApplicability = AssetApplicability()
    checksum: str | None = None
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "AssetRecord":
        applicability_payload = row.get("applicability", {})
        if not isinstance(applicability_payload, dict):
            raise ValueError("asset applicability must be an object")

        scope_text = str(applicability_payload.get("scope", ApplicabilityScope.CAMPAIGN.value))
        run_number_raw = applicability_payload.get("run_number")
        run_number = run_number_raw if isinstance(run_number_raw, int) else None

        provenance = row.get("provenance")
        if not isinstance(provenance, dict):
            raise ValueError("asset provenance must be an object")

        metadata = row.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("asset metadata must be an object when provided")

        return cls(
            record_id=str(row["record_id"]),
            timestamp=str(row["timestamp"]),
            campaign_id=int(row["campaign_id"]),
            campaign_slug=str(row["campaign_slug"]),
            ipts=int(row["ipts"]),
            asset_id=str(row["asset_id"]),
            asset_type=AssetType(str(row["asset_type"])),
            version=int(row["version"]),
            status=AssetStatus(str(row["status"])),
            path=str(row["path"]),
            provenance=provenance,
            applicability=AssetApplicability(
                scope=ApplicabilityScope(scope_text),
                run_number=run_number,
            ),
            checksum=str(row["checksum"]) if row.get("checksum") is not None else None,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "record_id": self.record_id,
            "timestamp": self.timestamp,
            "campaign_id": self.campaign_id,
            "campaign_slug": self.campaign_slug,
            "ipts": self.ipts,
            "asset_id": self.asset_id,
            "asset_type": self.asset_type.value,
            "version": self.version,
            "status": self.status.value,
            "applicability": self.applicability.to_dict(),
            "path": self.path,
            "provenance": self.provenance,
        }
        if self.checksum is not None:
            row["checksum"] = self.checksum
        if self.metadata is not None:
            row["metadata"] = self.metadata
        return row


PayloadT = TypeVar("PayloadT")


@dataclass(frozen=True)
class LoadedAsset(Generic[PayloadT]):
    """Generic runtime container pairing persisted metadata with payload object."""

    record: AssetRecord
    payload: PayloadT
