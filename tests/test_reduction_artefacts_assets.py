from __future__ import annotations

from snapwrap.reduction_artefacts import (
    ApplicabilityScope,
    AssetRecord,
    AssetType,
    LoadedAsset,
)


def _sample_asset_row() -> dict[str, object]:
    return {
        "record_id": "asset-cif-1",
        "timestamp": "2026-05-12T00:00:00Z",
        "campaign_id": 7,
        "campaign_slug": "bruciteA",
        "ipts": 33219,
        "asset_id": "cif-sample-01",
        "asset_type": "cif",
        "version": 1,
        "status": "active",
        "applicability": {"scope": "campaign", "run_number": None},
        "path": "assets/sample_01.cif",
        "provenance": {"source": "manual", "created_by": "operator"},
        "metadata": {"sample": "brucite"},
    }


def test_asset_record_round_trip() -> None:
    row = _sample_asset_row()
    record = AssetRecord.from_dict(row)

    assert record.asset_type == AssetType.CIF
    assert record.applicability.scope == ApplicabilityScope.CAMPAIGN
    assert record.applicability.run_number is None
    assert record.to_dict()["asset_type"] == "cif"


def test_loaded_asset_can_wrap_heterogeneous_payloads() -> None:
    record = AssetRecord.from_dict(_sample_asset_row())

    cif_payload = "data_example\n_cell_length_a 3.0"
    mask_payload = {"masked_bins": [1, 2, 3]}

    loaded_cif: LoadedAsset[str] = LoadedAsset(record=record, payload=cif_payload)
    loaded_mask: LoadedAsset[dict[str, list[int]]] = LoadedAsset(
        record=record,
        payload=mask_payload,
    )

    assert isinstance(loaded_cif.payload, str)
    assert isinstance(loaded_mask.payload, dict)
    assert loaded_mask.payload["masked_bins"] == [1, 2, 3]
