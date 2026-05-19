"""Tests for campaign_setup.py — spec-driven campaign setup."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from snapwrap.reduction_artefacts import preflight_spec, setup_campaign_from_spec


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def shared_root(tmp_path: Path) -> Path:
    sr = tmp_path / "shared"
    sr.mkdir()
    return sr


@pytest.fixture()
def minimal_spec(shared_root: Path) -> dict:
    """Minimal valid spec with no assets."""
    return {
        "ipts": 1,
        "campaign_slug": "test_campaign",
        "assembly_type": "DAC",
    }


@pytest.fixture()
def cif_file(shared_root: Path) -> Path:
    cif_dir = shared_root / "cif"
    cif_dir.mkdir()
    p = cif_dir / "sample.cif"
    p.write_text("# fake CIF\n")
    return p


@pytest.fixture()
def ub_file(shared_root: Path) -> Path:
    p = shared_root / "SNAP001UB1.mat"
    p.write_text("# fake UB\n")
    return p


@pytest.fixture()
def mask_file(shared_root: Path) -> Path:
    masks = shared_root / "masks"
    masks.mkdir()
    p = masks / "SNAP_001_dSpacing.json"
    p.write_text('{"fake": "mask"}\n')
    return p


@pytest.fixture()
def see_dir(shared_root: Path) -> Path:
    see = shared_root / "SEE"
    see.mkdir()
    return see


# ── preflight_spec ────────────────────────────────────────────────────────────

class TestPreflightSpec:
    def test_minimal_spec_no_problems(self, minimal_spec, shared_root):
        problems = preflight_spec(minimal_spec, shared_root=shared_root)
        assert problems == []

    def test_missing_asset_file_reported(self, shared_root):
        spec = {
            "ipts": 1,
            "campaign_slug": "c",
            "assembly_type": "DAC",
            "assets": [{"asset_type": "cif", "path": "cif/nonexistent.cif"}],
        }
        problems = preflight_spec(spec, shared_root=shared_root)
        assert any("nonexistent.cif" in p for p in problems)

    def test_existing_asset_file_no_problem(self, shared_root, cif_file):
        spec = {
            "ipts": 1,
            "campaign_slug": "test-c",
            "assembly_type": "DAC",
            "assets": [{"asset_type": "cif", "path": "cif/sample.cif"}],
        }
        problems = preflight_spec(spec, shared_root=shared_root)
        assert problems == []

    def test_missing_seemeta_reported(self, shared_root, see_dir):
        spec = {
            "ipts": 1,
            "campaign_slug": "test-c",
            "assembly_type": "DAC",
            "runs": [9999],
            "seemeta_dir": "SEE",
        }
        problems = preflight_spec(spec, shared_root=shared_root)
        assert any("SEE009999.json" in p for p in problems)

    def test_existing_seemeta_no_problem(self, shared_root, see_dir):
        (see_dir / "SEE000042.json").write_text("{}")
        spec = {
            "ipts": 1,
            "campaign_slug": "test-c",
            "assembly_type": "DAC",
            "runs": [42],
            "seemeta_dir": "SEE",
        }
        problems = preflight_spec(spec, shared_root=shared_root)
        assert problems == []

    def test_missing_bin_mask_reported(self, shared_root, ub_file):
        spec = {
            "ipts": 1,
            "campaign_slug": "test-c",
            "assembly_type": "DAC",
            "bin_masks": [{
                "artefact_id": "bm1",
                "mask_path": "masks/nonexistent.json",
                "source_run": 1,
                "ub_mat_paths": ["SNAP001UB1.mat"],
            }],
        }
        problems = preflight_spec(spec, shared_root=shared_root)
        assert any("nonexistent.json" in p for p in problems)

    def test_preflight_from_json_file(self, tmp_path, shared_root, minimal_spec):
        spec_path = tmp_path / "spec.json"
        spec_path.write_text(json.dumps(minimal_spec))
        problems = preflight_spec(spec_path, shared_root=shared_root)
        assert problems == []

    def test_preflight_missing_spec_file(self, tmp_path, shared_root):
        problems = preflight_spec(tmp_path / "no_such.json", shared_root=shared_root)
        assert len(problems) == 1
        assert "no_such.json" in problems[0]


# ── setup_campaign_from_spec — dry-run ────────────────────────────────────────

class TestSetupCampaignDryRun:
    def test_dry_run_returns_report(self, minimal_spec, shared_root):
        result = setup_campaign_from_spec(
            minimal_spec, shared_root=shared_root, dry_run=True
        )
        assert "dry_run_report" in result
        assert result["campaign_slug"] == "test_campaign"

    def test_dry_run_does_not_write_files(self, minimal_spec, shared_root):
        setup_campaign_from_spec(minimal_spec, shared_root=shared_root, dry_run=True)
        ra_root = shared_root / "snapwrap" / "reduction_artefacts"
        assert not ra_root.exists()


# ── setup_campaign_from_spec — real writes ────────────────────────────────────

class TestSetupCampaignFromSpec:
    def test_minimal_spec_bootstraps_campaign(self, minimal_spec, shared_root):
        result = setup_campaign_from_spec(minimal_spec, shared_root=shared_root)
        assert result["campaign_slug"] == "test_campaign"
        campaign_dir = (
            shared_root
            / "snapwrap"
            / "reduction_artefacts"
            / "campaigns"
            / "test_campaign"
        )
        assert campaign_dir.exists()
        assert (campaign_dir / "campaign.json").exists()

    def test_assets_ingested(self, shared_root, cif_file):
        spec = {
            "ipts": 1,
            "campaign_slug": "test_cif",
            "assembly_type": "DAC",
            "assets": [
                {
                    "asset_type": "cif",
                    "asset_id": "cif-sample",
                    "path": "cif/sample.cif",
                    "notes": "test CIF",
                }
            ],
        }
        result = setup_campaign_from_spec(spec, shared_root=shared_root)
        assert len(result["assets_ingested"]) == 1
        rec = result["assets_ingested"][0]
        assert rec["asset_id"] == "cif-sample"
        assert rec["asset_type"] == "cif"
        assert rec["version"] == 1

    def test_seemeta_ingested_for_runs(self, shared_root, see_dir):
        (see_dir / "SEE000010.json").write_text('{"type":"assembly.dac","components":[]}')
        (see_dir / "SEE000011.json").write_text('{"type":"assembly.dac","components":[]}')
        spec = {
            "ipts": 1,
            "campaign_slug": "test_see",
            "assembly_type": "DAC",
            "runs": [10, 11],
            "seemeta_dir": "SEE",
        }
        result = setup_campaign_from_spec(spec, shared_root=shared_root)
        see_assets = [
            a for a in result["assets_ingested"] if a["asset_type"] == "seemeta_json"
        ]
        assert len(see_assets) == 2
        run_numbers = {a["applicability"]["run_number"] for a in see_assets}
        assert run_numbers == {10, 11}

    def test_bin_mask_artefact_registered(self, shared_root, ub_file, mask_file):
        spec = {
            "ipts": 1,
            "campaign_slug": "test_mask",
            "assembly_type": "DAC",
            "bin_masks": [
                {
                    "artefact_id": "bm-dspacing",
                    "mask_path": "masks/SNAP_001_dSpacing.json",
                    "source_run": 1,
                    "ub_mat_paths": ["SNAP001UB1.mat"],
                    "width_coef": [1.0, 0.0],
                    "is_lite": True,
                    "notes": "test mask",
                }
            ],
        }
        result = setup_campaign_from_spec(spec, shared_root=shared_root)
        artefacts = result["artefacts_registered"]
        bin_masks = [a for a in artefacts if a["artefact_type"] == "bin_mask"]
        assert len(bin_masks) == 1
        assert bin_masks[0]["artefact_id"] == "bm-dspacing"
        assert bin_masks[0]["status"] == "active"

    def test_idempotent_bootstrap(self, minimal_spec, shared_root):
        """Running twice must not raise SlugConflictError."""
        setup_campaign_from_spec(minimal_spec, shared_root=shared_root)
        result2 = setup_campaign_from_spec(minimal_spec, shared_root=shared_root)
        assert result2["campaign_slug"] == "test_campaign"

    def test_invalid_spec_raises(self, shared_root):
        spec = {"ipts": 1, "assembly_type": "DAC"}  # missing campaign_slug
        with pytest.raises(Exception):  # jsonschema.ValidationError
            setup_campaign_from_spec(spec, shared_root=shared_root)

    def test_missing_source_raises(self, shared_root):
        spec = {
            "ipts": 1,
            "campaign_slug": "test_missing",
            "assembly_type": "DAC",
            "assets": [{"asset_type": "cif", "path": "cif/no_such.cif"}],
        }
        with pytest.raises(ValueError, match="preflight"):
            setup_campaign_from_spec(spec, shared_root=shared_root)

    def test_custom_seemeta_pattern(self, shared_root):
        see_dir = shared_root / "seemeta"
        see_dir.mkdir()
        (see_dir / "run_42_meta.json").write_text('{"type":"assembly.dac","components":[]}')
        spec = {
            "ipts": 1,
            "campaign_slug": "test_pattern",
            "assembly_type": "DAC",
            "runs": [42],
            "seemeta_dir": "seemeta",
            "seemeta_filename_pattern": "run_{run}_meta.json",
        }
        result = setup_campaign_from_spec(spec, shared_root=shared_root)
        see_assets = [
            a for a in result["assets_ingested"] if a["asset_type"] == "seemeta_json"
        ]
        assert len(see_assets) == 1
        assert see_assets[0]["applicability"]["run_number"] == 42

    def test_spec_loaded_from_json_file(self, tmp_path, shared_root, minimal_spec):
        spec_path = tmp_path / "spec.json"
        spec_path.write_text(json.dumps(minimal_spec))
        result = setup_campaign_from_spec(spec_path, shared_root=shared_root)
        assert result["campaign_slug"] == "test_campaign"
