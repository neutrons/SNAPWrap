"""Unit tests for the Campaign Manager Qt-free model layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from snapwrap.campaignManager.model import CampaignManagerModel
from snapwrap.reduction_artefacts.persistence import (
    bootstrap_campaign,
    register_swiss_cheese_artefact,
)


@pytest.fixture
def two_campaign_ipts(tmp_path: Path) -> tuple[int, Path]:
    """Bootstrap two campaigns under a temp IPTS shared root.

    Returns ``(ipts, shared_root)``.
    """
    ipts = 99001
    shared = tmp_path / f"IPTS-{ipts}" / "shared"
    shared.mkdir(parents=True)

    bootstrap_campaign(
        ipts=ipts,
        campaign_slug="alpha",
        assembly_type="DAC",
        description="alpha campaign",
        owners=["op"],
        shared_root=shared,
    )
    bootstrap_campaign(
        ipts=ipts,
        campaign_slug="beta",
        assembly_type="DAC",
        description="beta campaign",
        owners=["op"],
        shared_root=shared,
    )
    return ipts, shared


def test_discoverIPTSList_finds_iptses(tmp_path: Path) -> None:
    (tmp_path / "IPTS-1234" / "shared").mkdir(parents=True)
    (tmp_path / "IPTS-5678" / "shared").mkdir(parents=True)
    (tmp_path / "IPTS-9999").mkdir()  # no shared/, must be skipped
    (tmp_path / "not-an-ipts").mkdir()  # ignored

    out = CampaignManagerModel.discoverIPTSList(root=tmp_path)
    assert out == [5678, 1234]  # descending


def test_discoverIPTSList_handles_missing_root(tmp_path: Path) -> None:
    assert CampaignManagerModel.discoverIPTSList(root=tmp_path / "nope") == []


def test_discoverIPTSList_skips_unreadable_iptses(tmp_path: Path) -> None:
    """IPTS folders whose shared/ is not readable must be silently skipped."""
    import os
    import sys

    if sys.platform == "win32":
        pytest.skip("POSIX permission semantics")
    if os.geteuid() == 0:
        pytest.skip("root bypasses permission checks")

    (tmp_path / "IPTS-1111" / "shared").mkdir(parents=True)
    forbidden = tmp_path / "IPTS-2222" / "shared"
    forbidden.mkdir(parents=True)
    # Strip all permissions from the shared dir — its parent IPTS folder
    # is still listable, but `_is_readable_dir(shared)` must return False.
    forbidden.chmod(0o000)
    try:
        out = CampaignManagerModel.discoverIPTSList(root=tmp_path)
        assert out == [1111]
    finally:
        # Restore so pytest's tmp_path cleanup can succeed.
        forbidden.chmod(0o755)


def test_getCampaigns_returns_registered(two_campaign_ipts) -> None:
    ipts, shared = two_campaign_ipts
    out = CampaignManagerModel.getCampaigns(ipts=ipts, shared_root=shared)
    slugs = sorted(c["campaign_slug"] for c in out)
    assert slugs == ["alpha", "beta"]
    # The list_campaigns helper carries through the campaign_id field.
    assert all("campaign_id" in c for c in out)


def test_getCampaigns_empty_when_no_state(tmp_path: Path) -> None:
    shared = tmp_path / "IPTS-1" / "shared"
    shared.mkdir(parents=True)
    assert CampaignManagerModel.getCampaigns(ipts=1, shared_root=shared) == []


def test_getArtefacts_filters_pass_through(two_campaign_ipts, tmp_path: Path) -> None:
    ipts, shared = two_campaign_ipts

    # Register two bin-mask artefacts on the alpha campaign.
    mask_a = tmp_path / "a.json"
    mask_a.write_text(json.dumps({"binMaskList": []}))
    mask_b = tmp_path / "b.json"
    mask_b.write_text(json.dumps({"binMaskList": []}))

    register_swiss_cheese_artefact(
        ipts=ipts,
        campaign_identifier="alpha",
        artefact_id="binmask-1",
        mask_json_path=str(mask_a),
        source_run=100,
        ub_mat_paths=[],
        width_coef=[],
        is_lite=True,
        shared_root=shared,
        created_by="op",
    )
    register_swiss_cheese_artefact(
        ipts=ipts,
        campaign_identifier="alpha",
        artefact_id="binmask-2",
        mask_json_path=str(mask_b),
        source_run=200,
        ub_mat_paths=[],
        width_coef=[],
        is_lite=True,
        shared_root=shared,
        created_by="op",
    )

    all_rows = CampaignManagerModel.getArtefacts(
        ipts=ipts, campaign_identifier="alpha", shared_root=shared
    )
    assert len(all_rows) == 2

    only_one = CampaignManagerModel.getArtefacts(
        ipts=ipts,
        campaign_identifier="alpha",
        shared_root=shared,
        run_number=100,
    )
    assert len(only_one) == 1
    assert only_one[0]["artefact_id"] == "binmask-1"


def test_retireArtefact_marks_records_retired(two_campaign_ipts, tmp_path: Path) -> None:
    ipts, shared = two_campaign_ipts
    mask = tmp_path / "m.json"
    mask.write_text(json.dumps({"binMaskList": []}))

    register_swiss_cheese_artefact(
        ipts=ipts,
        campaign_identifier="alpha",
        artefact_id="binmask-to-retire",
        mask_json_path=str(mask),
        source_run=100,
        ub_mat_paths=[],
        width_coef=[],
        is_lite=True,
        shared_root=shared,
        created_by="op",
    )

    n = CampaignManagerModel.retireArtefact(
        ipts=ipts,
        campaign_identifier="alpha",
        artefact_id="binmask-to-retire",
        shared_root=shared,
    )
    assert n == 1

    actives = CampaignManagerModel.getArtefacts(
        ipts=ipts,
        campaign_identifier="alpha",
        shared_root=shared,
        status="active",
    )
    assert all(r.get("artefact_id") != "binmask-to-retire" for r in actives)

    retireds = CampaignManagerModel.getArtefacts(
        ipts=ipts,
        campaign_identifier="alpha",
        shared_root=shared,
        status="retired",
    )
    assert any(r.get("artefact_id") == "binmask-to-retire" for r in retireds)


def test_copyArtefact_registers_new_record(two_campaign_ipts, tmp_path: Path) -> None:
    ipts, shared = two_campaign_ipts
    mask = tmp_path / "src.json"
    mask.write_text(json.dumps({"binMaskList": []}))

    register_swiss_cheese_artefact(
        ipts=ipts,
        campaign_identifier="alpha",
        artefact_id="binmask-src",
        mask_json_path=str(mask),
        source_run=100,
        ub_mat_paths=[],
        width_coef=[],
        is_lite=True,
        shared_root=shared,
        created_by="op",
    )

    new_rec = CampaignManagerModel.copyArtefact(
        ipts=ipts,
        campaign_identifier="alpha",
        source_artefact_id="binmask-src",
        new_artefact_id="binmask-dst",
        run_number=200,
        shared_root=shared,
        notes="copied via UI test",
    )
    assert new_rec["artefact_id"] == "binmask-dst"
    assert new_rec["run_context"]["run_number"] == 200

    actives = CampaignManagerModel.getArtefacts(
        ipts=ipts,
        campaign_identifier="alpha",
        shared_root=shared,
        status="active",
    )
    ids = {r.get("artefact_id") for r in actives}
    assert "binmask-src" in ids and "binmask-dst" in ids


def test_registerPixelMask_registers_artefact(two_campaign_ipts, tmp_path: Path) -> None:
    from unittest.mock import patch

    ipts, shared = two_campaign_ipts
    nxs = tmp_path / "mask.nxs"
    nxs.write_bytes(b"fake nexus content")

    # Patch mantid out so the histogram-count validation is skipped — this
    # unit test covers registration logic only, not Mantid algorithm behaviour.
    with patch.dict("sys.modules", {"mantid.simpleapi": None, "mantid.api": None}):
        rec = CampaignManagerModel.registerPixelMask(
            ipts=ipts,
            campaign_identifier="alpha",
            nxs_path=str(nxs),
            method="pixel_mask.custom",
            is_lite=True,
            ws_name="pixmask_test",
            run_number=65891,
            notes="test registration",
            shared_root=shared,
        )

    assert rec["artefact_type"] == "pixel_mask"
    # ID is auto-generated: pixmask-<stem>-lite
    assert rec["artefact_id"].startswith("pixmask-")
    assert rec["artefact_id"].endswith("-lite")

    artefacts = CampaignManagerModel.getArtefacts(
        ipts=ipts, campaign_identifier="alpha", shared_root=shared, status="active"
    )
    assert any(a["artefact_id"] == rec["artefact_id"] for a in artefacts)


def test_registerPixelMask_auto_versions_duplicate_id(two_campaign_ipts, tmp_path: Path) -> None:
    from unittest.mock import patch

    ipts, shared = two_campaign_ipts
    nxs = tmp_path / "mask.nxs"
    nxs.write_bytes(b"fake nexus content")

    with patch.dict("sys.modules", {"mantid.simpleapi": None, "mantid.api": None}):
        rec1 = CampaignManagerModel.registerPixelMask(
            ipts=ipts, campaign_identifier="alpha", nxs_path=str(nxs),
            method="pixel_mask.custom", is_lite=True, ws_name="pm1", shared_root=shared,
        )
        rec2 = CampaignManagerModel.registerPixelMask(
            ipts=ipts, campaign_identifier="alpha", nxs_path=str(nxs),
            method="pixel_mask.custom", is_lite=True, ws_name="pm2", shared_root=shared,
        )

    assert rec1["artefact_id"] != rec2["artefact_id"]
    assert rec2["artefact_id"].endswith("-v2")


def test_getRunSummaries_derives_runs_from_artefacts(two_campaign_ipts, tmp_path: Path) -> None:
    ipts, shared = two_campaign_ipts
    mask1 = tmp_path / "m1.json"
    mask1.write_text(json.dumps({"binMaskList": []}))
    mask2 = tmp_path / "m2.json"
    mask2.write_text(json.dumps({"binMaskList": []}))

    register_swiss_cheese_artefact(
        ipts=ipts,
        campaign_identifier="alpha",
        artefact_id="mask-100",
        mask_json_path=str(mask1),
        source_run=100,
        ub_mat_paths=[],
        width_coef=[],
        is_lite=True,
        shared_root=shared,
        created_by="op",
    )
    register_swiss_cheese_artefact(
        ipts=ipts,
        campaign_identifier="alpha",
        artefact_id="mask-200",
        mask_json_path=str(mask2),
        source_run=200,
        ub_mat_paths=[],
        width_coef=[],
        is_lite=True,
        shared_root=shared,
        created_by="op",
    )
    # Second artefact for run 100
    register_swiss_cheese_artefact(
        ipts=ipts,
        campaign_identifier="alpha",
        artefact_id="mask-100b",
        mask_json_path=str(mask1),
        source_run=100,
        ub_mat_paths=[],
        width_coef=[],
        is_lite=True,
        shared_root=shared,
        created_by="op",
    )

    summaries = CampaignManagerModel.getRunSummaries(
        ipts=ipts, campaign_identifier="alpha", shared_root=shared
    )

    run_numbers = [s["run_number"] for s in summaries]
    assert run_numbers == [200, 100]  # descending
    counts = {s["run_number"]: s["artefact_count"] for s in summaries}
    assert counts[100] == 2
    assert counts[200] == 1
    # artefact_types should be populated
    types_by_run = {s["run_number"]: s["artefact_types"] for s in summaries}
    assert "bin_mask" in types_by_run[100]
    assert "bin_mask" in types_by_run[200]


def test_getRunSummaries_empty_when_no_run_context(two_campaign_ipts) -> None:
    ipts, shared = two_campaign_ipts
    summaries = CampaignManagerModel.getRunSummaries(
        ipts=ipts, campaign_identifier="alpha", shared_root=shared
    )
    assert summaries == []


def test_getAssets_returns_empty_for_new_campaign(two_campaign_ipts) -> None:
    ipts, shared = two_campaign_ipts
    assets = CampaignManagerModel.getAssets(
        ipts=ipts, campaign_identifier="alpha", shared_root=shared
    )
    assert assets == []


def test_ingestAsset_registers_and_getAssets_sees_it(two_campaign_ipts, tmp_path: Path) -> None:
    ipts, shared = two_campaign_ipts
    cif_file = tmp_path / "sample.cif"
    cif_file.write_text("# dummy cif")

    rec = CampaignManagerModel.ingestAsset(
        ipts=ipts,
        campaign_identifier="alpha",
        source_path=cif_file,
        asset_type="cif",
        asset_id="sample-cif",
        notes="test ingest",
        shared_root=shared,
    )
    assert rec["asset_id"] == "sample-cif"
    assert rec["asset_type"] == "cif"
    assert rec["status"] == "active"

    assets = CampaignManagerModel.getAssets(
        ipts=ipts, campaign_identifier="alpha", shared_root=shared
    )
    assert any(a["asset_id"] == "sample-cif" for a in assets)


def test_getAssets_deduplicates_by_asset_id(two_campaign_ipts, tmp_path: Path) -> None:
    ipts, shared = two_campaign_ipts
    cif_file = tmp_path / "sample.cif"
    cif_file.write_text("# dummy cif v1")
    cif_file2 = tmp_path / "sample2.cif"
    cif_file2.write_text("# dummy cif v2")

    CampaignManagerModel.ingestAsset(
        ipts=ipts, campaign_identifier="alpha", source_path=cif_file,
        asset_type="cif", asset_id="my-cif", shared_root=shared,
    )
    # Re-ingest the same logical asset_id from a different source file.
    # ingest_asset stores files by content hash so use distinct content.
    CampaignManagerModel.ingestAsset(
        ipts=ipts, campaign_identifier="alpha", source_path=cif_file2,
        asset_type="cif", asset_id="my-cif", shared_root=shared,
    )

    assets = CampaignManagerModel.getAssets(
        ipts=ipts, campaign_identifier="alpha", shared_root=shared
    )
    matching = [a for a in assets if a["asset_id"] == "my-cif"]
    assert len(matching) == 1  # only one row despite two ingests


def test_createCampaign_bootstraps_campaign(tmp_path: Path) -> None:
    ipts = 77001
    shared = tmp_path / f"IPTS-{ipts}" / "shared"
    shared.mkdir(parents=True)

    result = CampaignManagerModel.createCampaign(
        ipts=ipts,
        campaign_slug="gamma-test",
        assembly_type="PE",
        description="created via UI test",
        owners=["malcolm"],
        shared_root=shared,
    )

    assert result["campaign_slug"] == "gamma-test"

    campaigns = CampaignManagerModel.getCampaigns(ipts=ipts, shared_root=shared)
    slugs = {c["campaign_slug"] for c in campaigns}
    assert "gamma-test" in slugs


def test_registerCrystalSpecies_registers_artefact(two_campaign_ipts, tmp_path: Path) -> None:
    ipts, shared = two_campaign_ipts
    cif = tmp_path / "si.cif"
    cif.write_text("# dummy cif")

    rec = CampaignManagerModel.registerCrystalSpecies(
        ipts=ipts,
        campaign_identifier="alpha",
        species_name="silicon",
        cif_path=str(cif),
        role="calibrant",
        source_run=65900,
        shared_root=shared,
    )

    assert rec["species_name"] == "silicon"
    assert rec["role"] == "calibrant"
    assert rec["source_run"] == 65900
    assert rec["cifPath"] == str(cif)
    assert rec["eosPath"] is None


def test_registerCrystalSpecies_with_eos(two_campaign_ipts, tmp_path: Path) -> None:
    ipts, shared = two_campaign_ipts
    cif = tmp_path / "ice.cif"
    cif.write_text("# dummy cif")

    eos_params = {
        "eos_type": "birch-murnaghan",
        "V_0": 40.85,
        "K_0": 23.7,
        "K_prime": 4.15,
        "source": "Hemley et al., Nature 330 (1987)",
        "stability_pressure": [2.1, None],
        "stability_temperature": None,
    }

    rec = CampaignManagerModel.registerCrystalSpecies(
        ipts=ipts,
        campaign_identifier="alpha",
        species_name="ice-VII",
        cif_path=str(cif),
        eos_params=eos_params,
        shared_root=shared,
    )

    assert rec["species_name"] == "ice-VII"
    # eos_path should point to a written .eos.json file in the artefact dir
    assert rec["eosPath"] is not None
    import json
    written = json.loads(Path(rec["eosPath"]).read_text())
    assert written["eos_type"] == "birch-murnaghan"
    assert written["stability_pressure"] == [2.1, None]
