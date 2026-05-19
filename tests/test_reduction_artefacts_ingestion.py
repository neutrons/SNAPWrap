"""Tests for ingest_asset, ingest_seemeta_for_run, register_attenuation_artefact_planned,
and build_run_manifest (Phases 3–5).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from snapwrap.reduction_artefacts import (
    bootstrap_campaign,
    build_run_manifest,
    ingest_asset,
    ingest_seemeta_for_run,
    list_asset_records,
    read_jsonl_records,
    register_attenuation_artefact_planned,
    register_pixel_mask_artefact,
    register_swiss_cheese_artefact,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _shared_root(tmp_path: Path) -> Path:
    return tmp_path / "SNS" / "SNAP" / "IPTS-35214" / "shared"


def _bootstrap(tmp_path: Path, assembly_type: str = "DAC") -> Path:
    shared_root = _shared_root(tmp_path)
    bootstrap_campaign(
        ipts=35214,
        campaign_slug="test_camp",
        assembly_type=assembly_type,
        shared_root=shared_root,
    )
    return shared_root


def _write_file(path: Path, content: str = "stub") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ── ingest_asset ─────────────────────────────────────────────────────────────

def test_ingest_asset_copies_file_and_records(tmp_path: Path) -> None:
    shared_root = _bootstrap(tmp_path)
    src = _write_file(tmp_path / "sample.cif", "data_sample\n_cell_length_a 5.0\n")

    record = ingest_asset(
        ipts=35214,
        campaign_identifier="test_camp",
        source_path=src,
        asset_type="cif",
        shared_root=shared_root,
    )

    assert record["asset_type"] == "cif"
    assert record["asset_id"] == "sample"  # derived from stem
    assert record["version"] == 1
    assert record["status"] == "active"
    assert record["checksum"] is not None and len(record["checksum"]) == 64

    # File should be in the managed store.
    dest = Path(record["path"])
    assert dest.exists()
    assert dest.read_text() == src.read_text()


def test_ingest_asset_explicit_asset_id(tmp_path: Path) -> None:
    shared_root = _bootstrap(tmp_path)
    src = _write_file(tmp_path / "my.cif")

    record = ingest_asset(
        ipts=35214,
        campaign_identifier="test_camp",
        source_path=src,
        asset_type="cif",
        asset_id="custom_id",
        shared_root=shared_root,
    )
    assert record["asset_id"] == "custom_id"


def test_ingest_asset_supersedes_prior_active_version(tmp_path: Path) -> None:
    shared_root = _bootstrap(tmp_path)
    src_v1 = _write_file(tmp_path / "sample.cif", "version 1")

    r1 = ingest_asset(
        ipts=35214,
        campaign_identifier="test_camp",
        source_path=src_v1,
        asset_type="cif",
        asset_id="sample",
        shared_root=shared_root,
    )
    assert r1["version"] == 1

    # Update with new content.
    src_v2 = _write_file(tmp_path / "sample_v2.cif", "version 2")
    r2 = ingest_asset(
        ipts=35214,
        campaign_identifier="test_camp",
        source_path=src_v2,
        asset_type="cif",
        asset_id="sample",
        shared_root=shared_root,
        overwrite=True,
    )
    assert r2["version"] == 2
    assert r1["record_id"] in r2["provenance"]["supersedes"]


def test_ingest_asset_run_scope(tmp_path: Path) -> None:
    shared_root = _bootstrap(tmp_path)
    src = _write_file(tmp_path / "see.json", '{"assembly_type": "DAC"}')

    record = ingest_asset(
        ipts=35214,
        campaign_identifier="test_camp",
        source_path=src,
        asset_type="seemeta_json",
        applicability_scope="run",
        run_number=1234,
        shared_root=shared_root,
    )
    assert record["applicability"]["scope"] == "run"
    assert record["applicability"]["run_number"] == 1234


def test_ingest_asset_unknown_type_raises(tmp_path: Path) -> None:
    shared_root = _bootstrap(tmp_path)
    src = _write_file(tmp_path / "x.txt")
    with pytest.raises(ValueError, match="Unknown asset_type"):
        ingest_asset(
            ipts=35214,
            campaign_identifier="test_camp",
            source_path=src,
            asset_type="not_a_real_type",
            shared_root=shared_root,
        )


def test_ingest_asset_missing_source_raises(tmp_path: Path) -> None:
    shared_root = _bootstrap(tmp_path)
    with pytest.raises(FileNotFoundError):
        ingest_asset(
            ipts=35214,
            campaign_identifier="test_camp",
            source_path=tmp_path / "does_not_exist.cif",
            asset_type="cif",
            shared_root=shared_root,
        )


# ── ingest_seemeta_for_run ────────────────────────────────────────────────────

def test_ingest_seemeta_for_run(tmp_path: Path) -> None:
    shared_root = _bootstrap(tmp_path)
    src = _write_file(tmp_path / "SEE001234.json", '{"assembly_type": "DAC"}')

    record = ingest_seemeta_for_run(
        ipts=35214,
        campaign_identifier="test_camp",
        source_path=src,
        run_number=1234,
        shared_root=shared_root,
    )
    assert record["asset_id"] == "seemeta-1234"
    assert record["asset_type"] == "seemeta_json"
    assert record["applicability"]["run_number"] == 1234

    # Ingest again — should supersede.
    src2 = _write_file(tmp_path / "SEE001234_v2.json", '{"assembly_type": "DAC", "v": 2}')
    r2 = ingest_seemeta_for_run(
        ipts=35214,
        campaign_identifier="test_camp",
        source_path=src2,
        run_number=1234,
        shared_root=shared_root,
        overwrite=True,
    )
    assert r2["version"] == 2
    assert record["record_id"] in r2["provenance"]["supersedes"]


# ── register_attenuation_artefact_planned (Phase 4 PE) ───────────────────────

def test_register_attenuation_artefact_planned(tmp_path: Path) -> None:
    shared_root = _bootstrap(tmp_path, assembly_type="PE")

    record = register_attenuation_artefact_planned(
        ipts=35214,
        campaign_identifier="test_camp",
        artefact_id="atten_pe_test",
        shared_root=shared_root,
        notes="Placeholder until generator is implemented.",
    )

    assert record["artefact_type"] == "attenuation_workspace"
    assert record["status"] == "planned"
    assert record["path"] == "PENDING"
    assert record["method"] == "attenuation.from_seemeta"

    ra_root = shared_root / "snapwrap" / "reduction_artefacts"
    index = ra_root / "campaigns" / "test_camp" / "artefacts_index.jsonl"
    rows = read_jsonl_records(index)
    assert any(r.get("artefact_id") == "atten_pe_test" for r in rows)


# ── build_run_manifest (Phase 5) ─────────────────────────────────────────────

def _register_bin_mask(tmp_path: Path, shared_root: Path, run: int = 1001) -> dict:
    ub1 = _write_file(tmp_path / f"ub1_{run}.mat", "UB1")
    ub2 = _write_file(tmp_path / f"ub2_{run}.mat", "UB2")
    mask = _write_file(tmp_path / f"mask_{run}.json", '{"bins": []}')
    return register_swiss_cheese_artefact(
        ipts=35214,
        campaign_identifier="test_camp",
        artefact_id=f"bm_{run}",
        mask_json_path=str(mask),
        source_run=run,
        ub_mat_paths=[str(ub1), str(ub2)],
        width_coef=[1.0, 0.0],
        is_lite=True,
        shared_root=shared_root,
    )


def test_build_run_manifest_dac_with_artefacts(tmp_path: Path) -> None:
    shared_root = _bootstrap(tmp_path)
    _register_bin_mask(tmp_path, shared_root, run=1001)

    manifest = build_run_manifest(
        ipts=35214,
        campaign_identifier="test_camp",
        run_number=1001,
        shared_root=shared_root,
        assembly_type="DAC",
    )

    assert manifest["run_number"] == 1001
    assert manifest["assembly_type"] == "DAC"
    assert manifest["attempt_number"] == 1
    assert isinstance(manifest["selected_artefacts"], list)

    # bin_mask should be found; crystal_box will be missing.
    by_type = {s["artefact_type"]: s for s in manifest["selected_artefacts"]}
    assert "bin_mask" in by_type
    assert by_type["bin_mask"]["artefact_id"] == "bm_1001"

    manifest_path = Path(manifest["manifest_path"])
    assert manifest_path.exists()
    reloaded = json.loads(manifest_path.read_text())
    assert reloaded["run_number"] == 1001


def test_build_run_manifest_auto_increments_attempt(tmp_path: Path) -> None:
    shared_root = _bootstrap(tmp_path)

    m1 = build_run_manifest(
        ipts=35214,
        campaign_identifier="test_camp",
        run_number=1001,
        shared_root=shared_root,
        assembly_type="DAC",
    )
    m2 = build_run_manifest(
        ipts=35214,
        campaign_identifier="test_camp",
        run_number=1001,
        shared_root=shared_root,
        assembly_type="DAC",
    )
    assert m1["attempt_number"] == 1
    assert m2["attempt_number"] == 2
    assert Path(m1["manifest_path"]).exists()
    assert Path(m2["manifest_path"]).exists()
    assert m1["manifest_path"] != m2["manifest_path"]


def test_build_run_manifest_pe_assembly(tmp_path: Path) -> None:
    shared_root = _bootstrap(tmp_path, assembly_type="PE")
    nxs = _write_file(tmp_path / "mask.nxs", "NXS_STUB")
    register_pixel_mask_artefact(
        ipts=35214,
        campaign_identifier="test_camp",
        artefact_id="pm_pe_001",
        nxs_path=str(nxs),
        method="pixel_mask.letterbox",
        ws_name="pe_letterbox_mask",
        shared_root=shared_root,
    )

    manifest = build_run_manifest(
        ipts=35214,
        campaign_identifier="test_camp",
        run_number=2001,
        shared_root=shared_root,
        assembly_type="PE",
    )
    by_type = {s["artefact_type"]: s for s in manifest["selected_artefacts"]}
    assert "pixel_mask" in by_type
    assert by_type["pixel_mask"]["method"] == "pixel_mask.letterbox"


def test_build_run_manifest_assembly_from_campaign_json(tmp_path: Path) -> None:
    """If assembly_type is not passed, it should be read from campaign.json."""
    shared_root = _bootstrap(tmp_path, assembly_type="DAC")
    manifest = build_run_manifest(
        ipts=35214,
        campaign_identifier="test_camp",
        run_number=1001,
        shared_root=shared_root,
        # no assembly_type passed
    )
    assert manifest["assembly_type"] == "DAC"


def test_build_run_manifest_method_preference(tmp_path: Path) -> None:
    shared_root = _bootstrap(tmp_path)
    _register_bin_mask(tmp_path, shared_root, run=1001)

    manifest = build_run_manifest(
        ipts=35214,
        campaign_identifier="test_camp",
        run_number=1001,
        shared_root=shared_root,
        assembly_type="DAC",
        method_preferences={"bin_mask": "bin_mask.from_ub_pair"},
    )
    by_type = {s["artefact_type"]: s for s in manifest["selected_artefacts"]}
    # The registered artefact used swiss_cheese_ub method, not from_ub_pair,
    # so preferred method falls back to last candidate.
    assert "bin_mask" in by_type
