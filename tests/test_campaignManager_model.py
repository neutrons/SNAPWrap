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
