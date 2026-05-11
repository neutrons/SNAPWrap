from __future__ import annotations

import json
from pathlib import Path

import pytest

from snapwrap.reduction_artefacts import (
    SlugConflictError,
    append_jsonl_record,
    bootstrap_campaign,
    rename_campaign_slug,
    read_jsonl_records,
    resolve_campaign_slug,
    validate_jsonl_file,
)


def _campaign_root(tmp_path: Path) -> Path:
    return tmp_path / "SNS" / "SNAP" / "IPTS-35214" / "shared"


def test_bootstrap_campaign_creates_expected_layout(tmp_path: Path) -> None:
    shared_root = _campaign_root(tmp_path)

    campaign = bootstrap_campaign(
        ipts=35214,
        campaign_slug="dac_fe_01",
        assembly_type="DAC",
        shared_root=shared_root,
        description="First DAC campaign",
        owners=["alice", "bob"],
    )

    ra_root = shared_root / "snapwrap" / "reduction_artefacts"
    campaign_dir = ra_root / "campaigns" / "dac_fe_01"

    assert campaign["campaign_id"] == 1
    assert (ra_root / "_state.json").exists()
    assert (campaign_dir / "campaign.json").exists()
    assert (campaign_dir / "runs.jsonl").exists()
    assert (campaign_dir / "assets_index.jsonl").exists()
    assert (campaign_dir / "artefacts_index.jsonl").exists()
    assert (campaign_dir / "manifests").is_dir()
    assert (campaign_dir / "assets").is_dir()
    assert (campaign_dir / "artefacts").is_dir()
    assert (campaign_dir / "logs").is_dir()

    with (ra_root / "_state.json").open("r", encoding="utf-8") as handle:
        state = json.load(handle)

    assert state["next_campaign_id"] == 2
    assert state["campaigns"]["dac_fe_01"]["campaign_id"] == 1


def test_bootstrap_campaign_uses_monotonic_ids_and_blocks_slug_conflict(tmp_path: Path) -> None:
    shared_root = _campaign_root(tmp_path)

    first = bootstrap_campaign(
        ipts=35214,
        campaign_slug="dac_fe_01",
        assembly_type="DAC",
        shared_root=shared_root,
    )
    second = bootstrap_campaign(
        ipts=35214,
        campaign_slug="dac_fe_02",
        assembly_type="DAC",
        shared_root=shared_root,
    )

    assert first["campaign_id"] == 1
    assert second["campaign_id"] == 2

    with pytest.raises(SlugConflictError):
        bootstrap_campaign(
            ipts=35214,
            campaign_slug="dac_fe_01",
            assembly_type="DAC",
            shared_root=shared_root,
        )


def test_append_and_read_jsonl_records_with_schema_validation(tmp_path: Path) -> None:
    shared_root = _campaign_root(tmp_path)
    campaign = bootstrap_campaign(
        ipts=35214,
        campaign_slug="pe_h2o_01",
        assembly_type="PE",
        shared_root=shared_root,
    )

    campaign_dir = (
        shared_root
        / "snapwrap"
        / "reduction_artefacts"
        / "campaigns"
        / campaign["campaign_slug"]
    )
    assets_index = campaign_dir / "assets_index.jsonl"

    record = {
        "record_id": "asset-rec-001",
        "timestamp": campaign["created_at"],
        "campaign_id": campaign["campaign_id"],
        "campaign_slug": campaign["campaign_slug"],
        "ipts": campaign["ipts"],
        "asset_id": "asset-001",
        "asset_type": "cif",
        "version": 1,
        "status": "active",
        "path": "assets/sample.cif",
        "provenance": {"source": "manual", "created_by": "operator"},
    }

    append_jsonl_record(assets_index, record, schema_name="asset_record.schema.json")
    loaded = read_jsonl_records(assets_index)

    assert len(loaded) == 1
    assert loaded[0]["asset_id"] == "asset-001"


def test_validate_jsonl_file_reports_bad_lines(tmp_path: Path) -> None:
    index_path = tmp_path / "assets_index.jsonl"
    index_path.write_text("{\"good\": 1}\nnot-json\n", encoding="utf-8")

    errors = validate_jsonl_file(index_path, "asset_record.schema.json")
    assert len(errors) >= 2
    assert any("malformed JSON" in err for err in errors)


def test_rename_campaign_slug_updates_state_and_directory(tmp_path: Path) -> None:
    shared_root = _campaign_root(tmp_path)
    campaign = bootstrap_campaign(
        ipts=35214,
        campaign_slug="dac_fe_01",
        assembly_type="DAC",
        shared_root=shared_root,
    )

    result = rename_campaign_slug(
        ipts=35214,
        old_slug="dac_fe_01",
        new_slug="dac_iron_01",
        shared_root=shared_root,
    )

    assert result["renamed"] is True
    assert result["campaign_slug"] == "dac_iron_01"
    assert result["campaign_id"] == campaign["campaign_id"]

    ra_root = shared_root / "snapwrap" / "reduction_artefacts"
    with (ra_root / "_state.json").open("r", encoding="utf-8") as handle:
        state = json.load(handle)

    assert "dac_iron_01" in state["campaigns"]
    assert "dac_fe_01" not in state["campaigns"]
    assert state["aliases"]["dac_fe_01"] == "dac_iron_01"
    assert (ra_root / "campaigns" / "dac_iron_01").exists()
    assert not (ra_root / "campaigns" / "dac_fe_01").exists()

    with (ra_root / "campaigns" / "dac_iron_01" / "campaign.json").open("r", encoding="utf-8") as handle:
        campaign_data = json.load(handle)
    assert campaign_data["campaign_slug"] == "dac_iron_01"


def test_resolve_campaign_slug_supports_alias_and_id_lookup(tmp_path: Path) -> None:
    shared_root = _campaign_root(tmp_path)
    campaign = bootstrap_campaign(
        ipts=35214,
        campaign_slug="pe_h2o_01",
        assembly_type="PE",
        shared_root=shared_root,
    )

    rename_campaign_slug(
        ipts=35214,
        old_slug="pe_h2o_01",
        new_slug="pe_water_01",
        shared_root=shared_root,
    )

    assert resolve_campaign_slug(
        ipts=35214,
        campaign_identifier="pe_water_01",
        shared_root=shared_root,
    ) == "pe_water_01"
    assert resolve_campaign_slug(
        ipts=35214,
        campaign_identifier="pe_h2o_01",
        shared_root=shared_root,
    ) == "pe_water_01"
    assert resolve_campaign_slug(
        ipts=35214,
        campaign_identifier=campaign["campaign_id"],
        shared_root=shared_root,
    ) == "pe_water_01"
