"""Tests for Phase C crystallography asset/artefact integration.

C1: AssetType.EOS_DESCRIPTION exists and validates through the schema.
C2: load_eos_description parses .eos.json files correctly.
C3: LoadedAsset[crystalSpecies] type is expressible (structural check).
C4: register_crystal_species_artefact appends to crystal_species_index.jsonl.

No Mantid is required by this test module.  build_crystal_species() itself
needs Mantid and is tested separately in test_sample_meta_from_cif.py.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from snapwrap.reduction_artefacts import (
    AssetType,
    LoadedAsset,
    bootstrap_campaign,
    list_crystal_species_records,
    load_eos_description,
    register_asset_record,
    register_crystal_species_artefact,
)
from snapwrap.reduction_artefacts.assets import AssetRecord, AssetApplicability, AssetStatus


# ── helpers ──────────────────────────────────────────────────────────────────

def _write_eos_json(path: Path, **overrides) -> Path:
    """Write a minimal valid .eos.json file and return its path."""
    data = {
        "eos_type": "vinet",
        "V_0": 31.724,
        "K_0": 295.2,
        "K_prime": 4.32,
        "source": "test",
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _asset_record(path: str = "sample.cif", asset_type: str = "cif") -> AssetRecord:
    return AssetRecord(
        record_id="r-001",
        timestamp="2026-05-12T00:00:00Z",
        campaign_id=1,
        campaign_slug="test-campaign",
        ipts=33219,
        asset_id="asset-001",
        asset_type=AssetType(asset_type),
        version=1,
        status=AssetStatus.ACTIVE,
        path=path,
        provenance={"source": "manual", "created_by": "tester"},
        applicability=AssetApplicability(),
    )


# ── C1: AssetType.EOS_DESCRIPTION ────────────────────────────────────────────

def test_asset_type_eos_description_exists():
    assert AssetType.EOS_DESCRIPTION == "eos_description"


def test_asset_type_eos_description_round_trips_in_asset_record():
    record = _asset_record(path="sample.eos.json", asset_type="eos_description")
    assert record.asset_type == AssetType.EOS_DESCRIPTION
    assert record.to_dict()["asset_type"] == "eos_description"
    # from_dict must also accept the new value
    restored = AssetRecord.from_dict(record.to_dict())
    assert restored.asset_type == AssetType.EOS_DESCRIPTION


def test_asset_type_eos_description_validates_against_schema():
    """Register an EOS_DESCRIPTION asset in a real campaign and check schema."""
    with tempfile.TemporaryDirectory() as tmp:
        bootstrap_campaign(
            ipts=1,
            campaign_slug="eos-schema-test",
            assembly_type="DAC",
            shared_root=tmp,
        )
        rec = register_asset_record(
            ipts=1,
            campaign_identifier="eos-schema-test",
            asset_id="eos-w-01",
            asset_type="eos_description",
            path="assets/W_vinet.eos.json",
            shared_root=tmp,
        )
    assert rec["asset_type"] == "eos_description"


# ── C2: load_eos_description ─────────────────────────────────────────────────

def test_load_eos_description_returns_correct_fields(tmp_path):
    p = _write_eos_json(tmp_path / "W.eos.json")
    eos = load_eos_description(p)
    assert eos.eos_type == "vinet"
    assert abs(eos.V_0 - 31.724) < 1e-6
    assert abs(eos.K_0 - 295.2) < 1e-6
    assert abs(eos.K_prime - 4.32) < 1e-6
    assert eos.source == "test"


def test_load_eos_description_missing_file():
    with pytest.raises(FileNotFoundError, match="not found"):
        load_eos_description("/nonexistent/path/to/file.eos.json")


def test_load_eos_description_missing_required_field(tmp_path):
    p = tmp_path / "bad.eos.json"
    p.write_text(json.dumps({"eos_type": "vinet", "V_0": 1.0}), encoding="utf-8")
    with pytest.raises(ValueError, match="missing required fields"):
        load_eos_description(p)


def test_load_eos_description_unsupported_eos_type(tmp_path):
    p = _write_eos_json(tmp_path / "bad.eos.json", eos_type="polynomial")
    with pytest.raises(ValueError, match="not supported"):
        load_eos_description(p)


def test_load_eos_description_ignores_unknown_keys(tmp_path):
    data = {
        "eos_type": "birch-murnaghan",
        "V_0": 20.0,
        "K_0": 200.0,
        "K_prime": 4.0,
        "source": "test",
        "unknown_future_field": "ignored",
    }
    p = tmp_path / "extended.eos.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    eos = load_eos_description(p)  # must not raise
    assert eos.eos_type == "birch-murnaghan"


def test_load_eos_description_all_three_eos_types(tmp_path):
    for eos_type in ("vinet", "birch-murnaghan", "murnaghan"):
        p = _write_eos_json(tmp_path / f"{eos_type}.eos.json", eos_type=eos_type)
        eos = load_eos_description(p)
        assert eos.eos_type == eos_type


# ── C3: LoadedAsset[crystalSpecies] structural check ─────────────────────────

def test_loaded_asset_accepts_arbitrary_payload_type():
    """LoadedAsset[T] is generic — verify it can wrap a mock species dict."""
    record = _asset_record()
    fake_species = {"name": "ice-VII", "crystalSystem": "cubic", "unitCell": {"a": 3.32}}
    la: LoadedAsset = LoadedAsset(record=record, payload=fake_species)
    assert la.payload["name"] == "ice-VII"
    assert la.record.asset_type == AssetType.CIF


# ── C4: register_crystal_species_artefact + list_crystal_species_records ─────

def test_register_crystal_species_artefact_basic(tmp_path):
    bootstrap_campaign(
        ipts=1,
        campaign_slug="cs-test",
        assembly_type="DAC",
        shared_root=tmp_path,
    )
    rec = register_crystal_species_artefact(
        ipts=1,
        campaign_identifier="cs-test",
        species_name="ice-VII",
        cif_path="/data/ice7.cif",
        role="sample",
        source_run=12345,
        refined_a=3.32,
        refined_b=3.32,
        refined_c=3.32,
        refined_pressure_gpa=10.5,
        unitCell_updated=True,
        shared_root=tmp_path,
    )
    assert rec["species_name"] == "ice-VII"
    assert rec["role"] == "sample"
    assert abs(rec["refined_a"] - 3.32) < 1e-9
    assert abs(rec["refinedPressure_GPa"] - 10.5) < 1e-9
    assert rec["unitCell_updated"] is True


def test_register_crystal_species_artefact_persists_to_jsonl(tmp_path):
    bootstrap_campaign(
        ipts=1,
        campaign_slug="cs-persist",
        assembly_type="DAC",
        shared_root=tmp_path,
    )
    register_crystal_species_artefact(
        ipts=1,
        campaign_identifier="cs-persist",
        species_name="W",
        cif_path="/data/W.cif",
        shared_root=tmp_path,
    )
    register_crystal_species_artefact(
        ipts=1,
        campaign_identifier="cs-persist",
        species_name="Re",
        cif_path="/data/Re.cif",
        role="calibrant",
        shared_root=tmp_path,
    )
    all_records = list_crystal_species_records(
        ipts=1,
        campaign_identifier="cs-persist",
        shared_root=tmp_path,
    )
    assert len(all_records) == 2
    names = {r["species_name"] for r in all_records}
    assert names == {"W", "Re"}


def test_list_crystal_species_records_filter_by_role(tmp_path):
    bootstrap_campaign(
        ipts=1,
        campaign_slug="cs-filter",
        assembly_type="DAC",
        shared_root=tmp_path,
    )
    for name, role in [("ice-VII", "sample"), ("NaCl", "calibrant"), ("Au", "calibrant")]:
        register_crystal_species_artefact(
            ipts=1,
            campaign_identifier="cs-filter",
            species_name=name,
            cif_path=f"/data/{name}.cif",
            role=role,
            shared_root=tmp_path,
        )
    calibrants = list_crystal_species_records(
        ipts=1,
        campaign_identifier="cs-filter",
        role="calibrant",
        shared_root=tmp_path,
    )
    assert len(calibrants) == 2
    assert all(r["role"] == "calibrant" for r in calibrants)


def test_list_crystal_species_records_filter_by_run(tmp_path):
    bootstrap_campaign(
        ipts=1,
        campaign_slug="cs-run-filter",
        assembly_type="DAC",
        shared_root=tmp_path,
    )
    for run in [100, 101, 100]:
        register_crystal_species_artefact(
            ipts=1,
            campaign_identifier="cs-run-filter",
            species_name="ice-VII",
            cif_path="/data/ice7.cif",
            source_run=run,
            shared_root=tmp_path,
        )
    run100 = list_crystal_species_records(
        ipts=1,
        campaign_identifier="cs-run-filter",
        source_run=100,
        shared_root=tmp_path,
    )
    assert len(run100) == 2


def test_register_crystal_species_artefact_records_asset_ids(tmp_path):
    bootstrap_campaign(
        ipts=1,
        campaign_slug="cs-assetids",
        assembly_type="DAC",
        shared_root=tmp_path,
    )
    rec = register_crystal_species_artefact(
        ipts=1,
        campaign_identifier="cs-assetids",
        species_name="W",
        cif_path="/data/W.cif",
        eos_path="/data/W.eos.json",
        cif_asset_id="cif-w-01",
        eos_asset_id="eos-w-01",
        shared_root=tmp_path,
    )
    assert rec["cif_asset_id"] == "cif-w-01"
    assert rec["eos_asset_id"] == "eos-w-01"
    assert rec["eosPath"] == "/data/W.eos.json"
