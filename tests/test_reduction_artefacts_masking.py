"""Tests for masking.py (swiss-cheese builder) and register_swiss_cheese_artefact.

All Mantid and diamondUB imports are mocked so these tests run without Mantid.

Test groups
-----------
M1  build_swiss_cheese_from_run  — argument validation (no Mantid needed)
M2  build_swiss_cheese_from_run  — happy-path with full mocking
M3  build_swiss_cheese_from_ub_files — argument validation
M4  build_swiss_cheese_from_ub_files — happy-path with mocking
R1  register_swiss_cheese_artefact  — record structure and schema validation
R2  register_swiss_cheese_artefact  — error conditions
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from snapwrap.reduction_artefacts.persistence import (
    bootstrap_campaign,
    list_asset_records,
    read_jsonl_records,
    register_swiss_cheese_artefact,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def campaign_root(tmp_path: Path):
    """Bootstrap a minimal campaign and return (shared_root, ipts, slug)."""
    shared = tmp_path / "shared"
    shared.mkdir()
    ipts = 99901

    bootstrap_campaign(
        ipts=ipts,
        campaign_slug="dac_brucite",
        assembly_type="DAC",
        shared_root=shared,
        owners=["tester"],
    )
    return shared, ipts, "dac_brucite"


@pytest.fixture()
def fake_nexus(tmp_path: Path) -> Path:
    """A zero-byte file standing in for a nexus file."""
    p = tmp_path / "SNAP_65891.nxs.h5"
    p.touch()
    return p


@pytest.fixture()
def fake_ubs(tmp_path: Path) -> list[Path]:
    """Two fake ISAW .mat files."""
    ub_dir = tmp_path / "ubs"
    ub_dir.mkdir()
    ubs = []
    for i in (1, 2):
        p = ub_dir / f"SNAP65891UB{i}.mat"
        p.write_text(f"fake UB {i}")
        ubs.append(p)
    return ubs


# ---------------------------------------------------------------------------
# M1: build_swiss_cheese_from_run — validation (no Mantid)
# ---------------------------------------------------------------------------

class TestBuildFromRunValidation:
    def test_empty_width_coef_raises(self, tmp_path: Path, fake_nexus: Path):
        from snapwrap.reduction_artefacts.masking import build_swiss_cheese_from_run

        with pytest.raises(ValueError, match="width_coef"):
            build_swiss_cheese_from_run(
                65891, [], True,
                tmp_path / "out", "mask",
                ipts=33219,
                nexus_path=fake_nexus,
            )

    def test_missing_nexus_raises(self, tmp_path: Path):
        from snapwrap.reduction_artefacts.masking import build_swiss_cheese_from_run

        with pytest.raises(FileNotFoundError, match="nexus"):
            build_swiss_cheese_from_run(
                65891, [0.02], True,
                tmp_path / "out", "mask",
                ipts=33219,
                nexus_path=tmp_path / "nonexistent.nxs.h5",
            )


# ---------------------------------------------------------------------------
# M2: build_swiss_cheese_from_run — happy path with mocking
# ---------------------------------------------------------------------------

class TestBuildFromRunHappyPath:
    def _make_mock_sc(self, output_dir: Path, prefix: str):
        """Return a swissCheese mock whose save() writes a fake JSON."""
        sc = MagicMock()

        def fake_save(dir_str, pfx):
            (Path(dir_str) / f"{pfx}_Wavelength.json").write_text(
                json.dumps({"units": "Wavelength", "isLite": True, "xmins": [], "xmaxs": [], "spectraLsts": []})
            )

        sc.save.side_effect = fake_save
        return sc

    def test_calls_pipeline_in_order(self, tmp_path: Path, fake_nexus: Path):
        from snapwrap.reduction_artefacts.masking import build_swiss_cheese_from_run

        mock_sc = self._make_mock_sc(tmp_path / "out", "mask")
        mock_pk = MagicMock()
        mock_pk.UBList = [MagicMock(), MagicMock()]
        mock_pk.CreatePeaksWSAndSave.side_effect = lambda cid, p: Path(p).write_text(f"UB{cid}")

        mock_dub = MagicMock()
        mock_dub.generatePeaksWorkspace.return_value = ("snapwrap_PKS_65891", "/SNS/SNAP/IPTS-33219/")
        mock_dub.peakInfo.return_value = mock_pk
        mock_sc_class = MagicMock(return_value=mock_sc)

        with patch.dict(sys.modules, {
            "snapwrap.diamondUB": mock_dub,
            "snapwrap.maskUtils": MagicMock(swissCheese=mock_sc_class),
        }):
            # Re-import to pick up the mocked modules
            import importlib
            import snapwrap.reduction_artefacts.masking as _masking
            importlib.reload(_masking)
            mask_paths, ub_paths = _masking.build_swiss_cheese_from_run(
                65891, [0.02], True,
                tmp_path / "out", "mask",
                ipts=33219,
                nexus_path=fake_nexus,
            )

        mock_dub.generatePeaksWorkspace.assert_called_once()
        mock_dub.findDiamUB.assert_called_once_with(mock_pk)
        assert len(ub_paths) == 2
        assert ub_paths[0].name == "SNAP65891UB1.mat"
        assert ub_paths[1].name == "SNAP65891UB2.mat"
        assert mock_sc.notchFromUB.call_count == 2
        assert len(mask_paths) == 1
        assert mask_paths[0].name == "mask_Wavelength.json"

    def test_raises_when_too_few_ubs(self, tmp_path: Path, fake_nexus: Path):
        import importlib

        mock_pk = MagicMock()
        mock_pk.UBList = [MagicMock()]  # only 1 — need 2

        mock_dub = MagicMock()
        mock_dub.generatePeaksWorkspace.return_value = ("snapwrap_PKS_65891", "")
        mock_dub.peakInfo.return_value = mock_pk

        with patch.dict(sys.modules, {
            "snapwrap.diamondUB": mock_dub,
            "snapwrap.maskUtils": MagicMock(),
        }):
            import snapwrap.reduction_artefacts.masking as _masking
            importlib.reload(_masking)
            with pytest.raises(RuntimeError, match="findDiamUB found only 1"):
                _masking.build_swiss_cheese_from_run(
                    65891, [0.02], True,
                    tmp_path / "out", "mask",
                    ipts=33219,
                    nexus_path=fake_nexus,
                )

    def test_ipts_and_run_set_on_peakinfo(self, tmp_path: Path, fake_nexus: Path):
        import importlib

        mock_sc = self._make_mock_sc(tmp_path / "out", "mask")
        mock_pk = MagicMock()
        mock_pk.UBList = [MagicMock(), MagicMock()]
        mock_pk.CreatePeaksWSAndSave.side_effect = lambda cid, p: Path(p).write_text("")

        mock_dub = MagicMock()
        mock_dub.generatePeaksWorkspace.return_value = ("snapwrap_PKS_65891", "")
        mock_dub.peakInfo.return_value = mock_pk

        with patch.dict(sys.modules, {
            "snapwrap.diamondUB": mock_dub,
            "snapwrap.maskUtils": MagicMock(swissCheese=MagicMock(return_value=mock_sc)),
        }):
            import snapwrap.reduction_artefacts.masking as _masking
            importlib.reload(_masking)
            _masking.build_swiss_cheese_from_run(
                65891, [0.02], True,
                tmp_path / "out", "mask",
                ipts=33219,
                nexus_path=fake_nexus,
            )

        assert mock_pk.ipts == 33219
        assert mock_pk.runNumber == 65891


# ---------------------------------------------------------------------------
# M3: build_swiss_cheese_from_ub_files — validation
# ---------------------------------------------------------------------------

class TestBuildFromUBFilesValidation:
    def test_empty_ub_paths_raises(self, tmp_path, fake_nexus):
        from snapwrap.reduction_artefacts.masking import build_swiss_cheese_from_ub_files

        with pytest.raises(ValueError, match="ub_paths"):
            build_swiss_cheese_from_ub_files(
                [], 65891, [0.02], True,
                tmp_path / "out", "mask",
                ipts=33219,
                nexus_path=fake_nexus,
            )

    def test_empty_width_coef_raises(self, tmp_path, fake_nexus, fake_ubs):
        from snapwrap.reduction_artefacts.masking import build_swiss_cheese_from_ub_files

        with pytest.raises(ValueError, match="width_coef"):
            build_swiss_cheese_from_ub_files(
                fake_ubs, 65891, [], True,
                tmp_path / "out", "mask",
                ipts=33219,
                nexus_path=fake_nexus,
            )

    def test_missing_ub_file_raises(self, tmp_path, fake_nexus):
        from snapwrap.reduction_artefacts.masking import build_swiss_cheese_from_ub_files

        with pytest.raises(FileNotFoundError, match="UB matrix file not found"):
            build_swiss_cheese_from_ub_files(
                [tmp_path / "ghost.mat"], 65891, [0.02], True,
                tmp_path / "out", "mask",
                ipts=33219,
                nexus_path=fake_nexus,
            )


# ---------------------------------------------------------------------------
# M4: build_swiss_cheese_from_ub_files — happy path
# ---------------------------------------------------------------------------

class TestBuildFromUBFilesHappyPath:
    def test_loads_metadataonly_and_builds_mask(self, tmp_path, fake_nexus, fake_ubs):
        import importlib

        mock_sc = MagicMock()

        def fake_save(dir_str, pfx):
            (Path(dir_str) / f"{pfx}_Wavelength.json").write_text(
                json.dumps({"units": "Wavelength", "isLite": True,
                            "xmins": [], "xmaxs": [], "spectraLsts": []})
            )

        mock_sc.save.side_effect = fake_save
        mock_mantid = MagicMock()

        with patch.dict(sys.modules, {
            "mantid": MagicMock(simpleapi=mock_mantid),
            "mantid.simpleapi": mock_mantid,
            "snapwrap.maskUtils": MagicMock(swissCheese=MagicMock(return_value=mock_sc)),
        }):
            import snapwrap.reduction_artefacts.masking as _masking
            importlib.reload(_masking)
            result = _masking.build_swiss_cheese_from_ub_files(
                fake_ubs, 65891, [0.02], True,
                tmp_path / "out", "mask",
                ipts=33219,
                nexus_path=fake_nexus,
            )

        mock_mantid.LoadEventNexus.assert_called_once()
        _, load_kwargs = mock_mantid.LoadEventNexus.call_args
        assert load_kwargs.get("MetaDataOnly") is True
        mock_mantid.DeleteWorkspace.assert_called_once()
        assert mock_sc.notchFromUB.call_count == 2
        assert len(result) == 1
        assert result[0].name == "mask_Wavelength.json"


# ---------------------------------------------------------------------------
# R1: register_swiss_cheese_artefact — record structure
# ---------------------------------------------------------------------------

class TestRegisterSwissCheeseArtefact:
    def test_record_written_to_artefacts_index(self, campaign_root, fake_ubs):
        shared, ipts, slug = campaign_root
        ub_paths = [str(p) for p in fake_ubs]
        mask_path = "/tmp/dac_mask_Wavelength.json"

        record = register_swiss_cheese_artefact(
            ipts=ipts,
            campaign_identifier=slug,
            artefact_id="dac_mask_brucite_run65891",
            mask_json_path=mask_path,
            source_run=65891,
            ub_mat_paths=ub_paths,
            width_coef=[0.02],
            is_lite=True,
            shared_root=shared,
        )

        # artefact record fields
        assert record["artefact_type"] == "bin_mask"
        assert record["method"] == "swiss_cheese_ub"
        assert record["intended_use"] == "pre_reduction"
        assert record["path"] == mask_path
        assert record["run_context"]["run_number"] == 65891
        assert record["metadata"]["width_coef"] == [0.02]
        assert record["metadata"]["is_lite"] is True
        assert record["metadata"]["n_diamonds"] == 2
        assert len(record["input_asset_ids"]) == 2

    def test_artefact_record_is_on_disk(self, campaign_root, fake_ubs):
        shared, ipts, slug = campaign_root
        register_swiss_cheese_artefact(
            ipts=ipts,
            campaign_identifier=slug,
            artefact_id="mask_disk_check",
            mask_json_path="/tmp/m.json",
            source_run=65891,
            ub_mat_paths=[str(p) for p in fake_ubs],
            width_coef=[0.02],
            is_lite=True,
            shared_root=shared,
        )

        artefacts_index = (
            shared / "snapwrap" / "reduction_artefacts"
            / "campaigns" / slug / "artefacts_index.jsonl"
        )
        records = read_jsonl_records(artefacts_index)
        assert len(records) == 1
        assert records[0]["artefact_type"] == "bin_mask"

    def test_ub_assets_registered(self, campaign_root, fake_ubs):
        shared, ipts, slug = campaign_root
        register_swiss_cheese_artefact(
            ipts=ipts,
            campaign_identifier=slug,
            artefact_id="mask_asset_check",
            mask_json_path="/tmp/m.json",
            source_run=65891,
            ub_mat_paths=[str(p) for p in fake_ubs],
            width_coef=[0.02],
            is_lite=True,
            shared_root=shared,
        )

        ub_assets = list_asset_records(
            ipts=ipts,
            campaign_identifier=slug,
            asset_type="ub_matrix",
            shared_root=shared,
        )
        assert len(ub_assets) == 2
        assert ub_assets[0]["metadata"]["crystal_index"] == 1
        assert ub_assets[1]["metadata"]["crystal_index"] == 2
        # run-scoped
        assert ub_assets[0]["applicability"]["scope"] == "run"
        assert ub_assets[0]["applicability"]["run_number"] == 65891

    def test_input_asset_ids_match_registered_assets(self, campaign_root, fake_ubs):
        shared, ipts, slug = campaign_root
        record = register_swiss_cheese_artefact(
            ipts=ipts,
            campaign_identifier=slug,
            artefact_id="mask_xlink_check",
            mask_json_path="/tmp/m.json",
            source_run=65891,
            ub_mat_paths=[str(p) for p in fake_ubs],
            width_coef=[0.02],
            is_lite=True,
            shared_root=shared,
        )

        ub_assets = list_asset_records(
            ipts=ipts, campaign_identifier=slug,
            asset_type="ub_matrix", shared_root=shared,
        )
        registered_ids = {a["asset_id"] for a in ub_assets}
        for aid in record["input_asset_ids"]:
            assert aid in registered_ids

    def test_notes_in_provenance(self, campaign_root, fake_ubs):
        shared, ipts, slug = campaign_root
        record = register_swiss_cheese_artefact(
            ipts=ipts,
            campaign_identifier=slug,
            artefact_id="mask_notes_check",
            mask_json_path="/tmp/m.json",
            source_run=65891,
            ub_mat_paths=[str(p) for p in fake_ubs],
            width_coef=[0.02],
            is_lite=True,
            shared_root=shared,
            notes="test run only",
        )
        assert record["provenance"]["notes"] == "test run only"


# ---------------------------------------------------------------------------
# R2: register_swiss_cheese_artefact — error conditions
# ---------------------------------------------------------------------------

class TestRegisterSwissCheeseErrors:
    def test_invalid_ipts_raises(self, tmp_path):
        with pytest.raises(ValueError, match="ipts"):
            register_swiss_cheese_artefact(
                ipts=0,
                campaign_identifier="slug",
                artefact_id="x",
                mask_json_path="/tmp/m.json",
                source_run=1,
                ub_mat_paths=[],
                width_coef=[0.02],
                is_lite=True,
                shared_root=tmp_path,
            )

    def test_empty_artefact_id_raises(self, campaign_root, fake_ubs):
        shared, ipts, slug = campaign_root
        with pytest.raises(ValueError, match="artefact_id"):
            register_swiss_cheese_artefact(
                ipts=ipts,
                campaign_identifier=slug,
                artefact_id="   ",
                mask_json_path="/tmp/m.json",
                source_run=65891,
                ub_mat_paths=[str(p) for p in fake_ubs],
                width_coef=[0.02],
                is_lite=True,
                shared_root=shared,
            )

    def test_missing_campaign_raises(self, tmp_path):
        # Use the campaign_root fixture inline — bootstrap state exists but
        # then delete campaign.json to simulate a partial/corrupt state.
        shared = tmp_path / "shared"
        shared.mkdir()
        ipts = 99901
        bootstrap_campaign(
            ipts=ipts,
            campaign_slug="ghost_campaign",
            assembly_type="DAC",
            shared_root=shared,
        )
        # Remove the campaign.json to trigger the FileNotFoundError path.
        camp_json = (
            shared / "snapwrap" / "reduction_artefacts"
            / "campaigns" / "ghost_campaign" / "campaign.json"
        )
        camp_json.unlink()

        with pytest.raises(FileNotFoundError, match="campaign.json"):
            register_swiss_cheese_artefact(
                ipts=ipts,
                campaign_identifier="ghost_campaign",
                artefact_id="x",
                mask_json_path="/tmp/m.json",
                source_run=1,
                ub_mat_paths=[],
                width_coef=[0.02],
                is_lite=True,
                shared_root=shared,
            )
