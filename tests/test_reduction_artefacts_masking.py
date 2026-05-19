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
    register_pixel_mask_artefact,
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
            import snapwrap.reduction_artefacts.workspace_groups as _wg
            importlib.reload(_wg)
            importlib.reload(_masking)
            # Mark the donor ws as present so finalize will delete it.
            mock_mantid.mtd.getObjectNames.return_value = ["_snapwrap_donor_65891"]
            result = _masking.build_swiss_cheese_from_ub_files(
                fake_ubs, 65891, [0.02], True,
                tmp_path / "out", "mask",
                ipts=33219,
                nexus_path=fake_nexus,
                keep_diagnostics=False,
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


# ---------------------------------------------------------------------------
# P1: build_pixel_mask_from_file / build_pixel_mask_letterbox — validation
# ---------------------------------------------------------------------------

class TestBuildPixelMaskValidation:
    """Tests that do not require Mantid — file-not-found guards."""

    def test_missing_nxs_raises(self, tmp_path: Path):
        from snapwrap.reduction_artefacts.masking import build_pixel_mask_from_file

        with pytest.raises(FileNotFoundError, match="Pixel mask file not found"):
            build_pixel_mask_from_file(
                tmp_path / "no_such_mask.nxs",
                ws_name="test_ws",
            )

    def test_letterbox_missing_standard_file_raises(self, monkeypatch):
        """If the standard PE mask is absent, FileNotFoundError is raised."""
        import snapwrap.reduction_artefacts.masking as _m

        monkeypatch.setattr(_m, "STANDARD_PE_MASK_PATH", Path("/nonexistent/PEMask.nxs"))
        from snapwrap.reduction_artefacts.masking import build_pixel_mask_letterbox

        with pytest.raises(FileNotFoundError):
            build_pixel_mask_letterbox("test_ws")


# ---------------------------------------------------------------------------
# P2: build_pixel_mask_from_file — happy path (Mantid mocked)
# ---------------------------------------------------------------------------

class TestBuildPixelMaskHappyPath:
    def test_returns_ws_name(self, tmp_path: Path):
        """LoadNexus is called and the ws_name is returned."""
        fake_nxs = tmp_path / "PEMask.nxs"
        fake_nxs.touch()

        mock_mantid = MagicMock()

        import snapwrap.reduction_artefacts.masking as _masking_mod
        import importlib

        with patch.dict(
            sys.modules,
            {"mantid.simpleapi": mock_mantid},
        ):
            importlib.reload(_masking_mod)
            from snapwrap.reduction_artefacts.masking import build_pixel_mask_from_file

            result = build_pixel_mask_from_file(fake_nxs, "my_mask_ws")

        assert result == "my_mask_ws"
        mock_mantid.LoadNexus.assert_called_once_with(
            Filename=str(fake_nxs), OutputWorkspace="my_mask_ws"
        )

    def test_letterbox_uses_standard_path(self, tmp_path: Path, monkeypatch):
        """build_pixel_mask_letterbox delegates to build_pixel_mask_from_file."""
        fake_nxs = tmp_path / "PEMask.nxs"
        fake_nxs.touch()

        import snapwrap.reduction_artefacts.masking as _m
        monkeypatch.setattr(_m, "STANDARD_PE_MASK_PATH", fake_nxs)

        mock_mantid = MagicMock()
        import importlib

        with patch.dict(sys.modules, {"mantid.simpleapi": mock_mantid}):
            importlib.reload(_m)
            _m.STANDARD_PE_MASK_PATH = fake_nxs  # re-apply after reload
            from snapwrap.reduction_artefacts.masking import build_pixel_mask_letterbox

            result = build_pixel_mask_letterbox("lb_ws")

        assert result == "lb_ws"
        mock_mantid.LoadNexus.assert_called_once_with(
            Filename=str(fake_nxs), OutputWorkspace="lb_ws"
        )


# ---------------------------------------------------------------------------
# P3: register_pixel_mask_artefact — record structure and schema validation
# ---------------------------------------------------------------------------

class TestRegisterPixelMaskArtefact:
    @pytest.fixture()
    def pe_campaign_root(self, tmp_path: Path):
        shared = tmp_path / "shared"
        shared.mkdir()
        ipts = 99902
        bootstrap_campaign(
            ipts=ipts,
            campaign_slug="pe_h2o_01",
            assembly_type="PE",
            shared_root=shared,
            owners=["tester"],
        )
        return shared, ipts, "pe_h2o_01"

    @pytest.fixture()
    def fake_pe_mask(self, tmp_path: Path) -> Path:
        p = tmp_path / "PEMask.nxs"
        p.touch()
        return p

    def test_letterbox_record_structure(self, pe_campaign_root, fake_pe_mask):
        shared, ipts, slug = pe_campaign_root
        record = register_pixel_mask_artefact(
            ipts=ipts,
            campaign_identifier=slug,
            artefact_id="pixmask_pe_h2o_01",
            nxs_path=str(fake_pe_mask),
            method="pixel_mask.letterbox",
            ws_name="snapwrap_pixmask_pe_h2o_01",
            shared_root=shared,
        )
        assert record["artefact_type"] == "pixel_mask"
        assert record["method"] == "pixel_mask.letterbox"
        assert record["intended_use"] == "pre_reduction"
        assert record["metadata"]["ws_name"] == "snapwrap_pixmask_pe_h2o_01"
        assert record["path"] == str(fake_pe_mask)
        assert len(record["input_asset_ids"]) == 1

    def test_custom_method_accepted(self, pe_campaign_root, fake_pe_mask):
        shared, ipts, slug = pe_campaign_root
        record = register_pixel_mask_artefact(
            ipts=ipts,
            campaign_identifier=slug,
            artefact_id="pixmask_custom",
            nxs_path=str(fake_pe_mask),
            method="pixel_mask.custom",
            ws_name="snapwrap_pixmask_custom",
            shared_root=shared,
        )
        assert record["method"] == "pixel_mask.custom"

    def test_invalid_method_raises(self, pe_campaign_root, fake_pe_mask):
        shared, ipts, slug = pe_campaign_root
        with pytest.raises(ValueError, match="method must be one of"):
            register_pixel_mask_artefact(
                ipts=ipts,
                campaign_identifier=slug,
                artefact_id="bad",
                nxs_path=str(fake_pe_mask),
                method="pixel_mask.nonexistent",
                ws_name="ws",
                shared_root=shared,
            )

    def test_nxs_asset_registered(self, pe_campaign_root, fake_pe_mask):
        shared, ipts, slug = pe_campaign_root
        register_pixel_mask_artefact(
            ipts=ipts,
            campaign_identifier=slug,
            artefact_id="pixmask_pe_h2o_01",
            nxs_path=str(fake_pe_mask),
            method="pixel_mask.letterbox",
            ws_name="snapwrap_pixmask_pe_h2o_01",
            shared_root=shared,
        )
        assets = list_asset_records(
            ipts=ipts, campaign_identifier=slug, shared_root=shared
        )
        mask_assets = [a for a in assets if a.get("asset_type") == "manual_pixel_mask"]
        assert len(mask_assets) == 1
        assert mask_assets[0]["path"] == str(fake_pe_mask)

    def test_artefact_record_written_to_index(self, pe_campaign_root, fake_pe_mask):
        shared, ipts, slug = pe_campaign_root
        register_pixel_mask_artefact(
            ipts=ipts,
            campaign_identifier=slug,
            artefact_id="pixmask_pe_h2o_01",
            nxs_path=str(fake_pe_mask),
            method="pixel_mask.letterbox",
            ws_name="snapwrap_pixmask_pe_h2o_01",
            shared_root=shared,
        )
        artefacts_index = (
            shared / "snapwrap" / "reduction_artefacts"
            / "campaigns" / slug / "artefacts_index.jsonl"
        )
        records = read_jsonl_records(artefacts_index)
        assert any(r.get("artefact_type") == "pixel_mask" for r in records)

    def test_run_scoped_mask(self, pe_campaign_root, fake_pe_mask):
        shared, ipts, slug = pe_campaign_root
        record = register_pixel_mask_artefact(
            ipts=ipts,
            campaign_identifier=slug,
            artefact_id="pixmask_run65200",
            nxs_path=str(fake_pe_mask),
            method="pixel_mask.custom",
            ws_name="snapwrap_pixmask_pe_h2o_01_run65200",
            run_number=65200,
            shared_root=shared,
        )
        assert record["run_context"]["run_number"] == 65200

    def test_missing_campaign_raises(self, tmp_path, fake_pe_mask):
        shared = tmp_path / "shared"
        shared.mkdir()
        ipts = 99902
        bootstrap_campaign(
            ipts=ipts,
            campaign_slug="ghost_pe",
            assembly_type="PE",
            shared_root=shared,
        )
        camp_json = (
            shared / "snapwrap" / "reduction_artefacts"
            / "campaigns" / "ghost_pe" / "campaign.json"
        )
        camp_json.unlink()

        with pytest.raises(FileNotFoundError, match="campaign.json"):
            register_pixel_mask_artefact(
                ipts=ipts,
                campaign_identifier="ghost_pe",
                artefact_id="x",
                nxs_path=str(fake_pe_mask),
                method="pixel_mask.letterbox",
                ws_name="ws",
                shared_root=shared,
            )


# ---------------------------------------------------------------------------
# T1: detect_notches_in_spectrum — pure-numpy notch finder
# ---------------------------------------------------------------------------

class TestDetectNotchesInSpectrum:
    def test_flat_spectrum_yields_no_notches(self):
        import numpy as np
        from snapwrap.reduction_artefacts.masking import detect_notches_in_spectrum

        centers = np.linspace(0.5, 5.0, 400)
        y = np.full(400, 1000.0)
        notches, diag = detect_notches_in_spectrum(centers, y)
        assert notches == []
        for k in ("smoothed", "continuum", "ratio", "below_threshold"):
            assert k in diag

    def test_finds_single_deep_notch(self):
        import numpy as np
        from snapwrap.reduction_artefacts.masking import detect_notches_in_spectrum

        centers = np.linspace(0.5, 5.0, 1000)
        y = np.full(1000, 1000.0)
        # Deep dip from index 400..430 (~0.135 Å wide)
        y[400:430] = 100.0
        notches, _ = detect_notches_in_spectrum(
            centers, y, dip_threshold=0.6, continuum_window=151
        )
        assert len(notches) == 1
        lo, hi = notches[0]
        # The notch must contain the dip centre.
        assert lo < centers[415] < hi

    def test_merges_close_notches(self):
        import numpy as np
        from snapwrap.reduction_artefacts.masking import detect_notches_in_spectrum

        centers = np.linspace(0.5, 5.0, 2000)
        # Bin width ~ (4.5/1999) ≈ 0.00225 Å
        y = np.full(2000, 1000.0)
        y[800:815] = 100.0
        y[820:835] = 100.0  # gap of 5 bins ≈ 0.011 Å
        notches, _ = detect_notches_in_spectrum(
            centers, y, dip_threshold=0.6, continuum_window=151,
            merge_gap_aa=0.05, min_width_aa=0.001,
        )
        assert len(notches) == 1  # merged into one

    def test_drops_too_narrow_notches(self):
        import numpy as np
        from snapwrap.reduction_artefacts.masking import detect_notches_in_spectrum

        centers = np.linspace(0.5, 5.0, 200)
        y = np.full(200, 1000.0)
        y[100] = 50.0  # 1-bin dip ≈ 0.022 Å width
        notches, _ = detect_notches_in_spectrum(
            centers, y, dip_threshold=0.6, min_width_aa=0.5
        )
        assert notches == []

    def test_edge_padding_widens_notches(self):
        import numpy as np
        from snapwrap.reduction_artefacts.masking import detect_notches_in_spectrum

        centers = np.linspace(0.5, 5.0, 1000)
        y = np.full(1000, 1000.0)
        y[400:430] = 100.0
        n0, _ = detect_notches_in_spectrum(
            centers, y, dip_threshold=0.6, continuum_window=151, edge_pad_aa=0.0
        )
        n1, _ = detect_notches_in_spectrum(
            centers, y, dip_threshold=0.6, continuum_window=151, edge_pad_aa=0.05
        )
        assert len(n0) == 1 and len(n1) == 1
        assert n1[0][0] == pytest.approx(n0[0][0] - 0.05)
        assert n1[0][1] == pytest.approx(n0[0][1] + 0.05)

    def test_length_mismatch_raises(self):
        from snapwrap.reduction_artefacts.masking import detect_notches_in_spectrum
        with pytest.raises(ValueError, match="same length"):
            detect_notches_in_spectrum([1, 2, 3], [1, 2])

    def test_unknown_continuum_method_raises(self):
        import numpy as np
        from snapwrap.reduction_artefacts.masking import detect_notches_in_spectrum
        with pytest.raises(ValueError, match="continuum_method"):
            detect_notches_in_spectrum(
                np.linspace(0.5, 5.0, 100),
                np.full(100, 1000.0),
                continuum_method="bogus",
            )

    def test_clip_peaks_finds_deep_notch_and_renormalises(self):
        """clip_peaks: SNIP-based continuum, ratio median == 1, notch found."""
        import numpy as np
        from snapwrap.reduction_artefacts.masking import detect_notches_in_spectrum

        centers = np.linspace(0.5, 5.0, 1000)
        # Slightly noisy continuum (perfectly flat data inverts to identical
        # zeros, which is a SNIP-pathological edge case unrelated to the
        # algorithm's intended use).
        rng = np.random.default_rng(0)
        y = 1000.0 + rng.normal(0, 5.0, size=1000)
        # One narrow deep notch
        y[450:480] *= 0.2
        notches, diag = detect_notches_in_spectrum(
            centers, y,
            continuum_method="clip_peaks",
            clip_win_size=80,
            dip_threshold=0.7,
            min_width_aa=0.005,
            merge_gap_aa=0.02,
        )
        # At least one notch must be found, and one of them must cover the
        # dip centre (we don't assert exactly one — SNIP can produce small
        # end-artefacts depending on continuum shape).
        assert len(notches) >= 1
        dip_x = centers[465]
        assert any(lo < dip_x < hi for lo, hi in notches)
        # Renormalisation guarantee: median of ratio is ≈ 1 (it's the
        # reciprocal of an inv_ratio whose median is exactly 1, so a small
        # numerical offset is expected).
        assert np.median(diag["ratio"]) == pytest.approx(1.0, abs=0.01)
        # Diagnostic ratio is bounded — no inf / huge values.
        assert np.isfinite(diag["ratio"]).all()
        assert diag["ratio"].max() <= 1000.0


# ---------------------------------------------------------------------------
# T2: build_swiss_cheese_from_transmission_monitor — validation + happy-path
# ---------------------------------------------------------------------------

class TestTransmissionMonitorBuilder:
    def test_missing_nexus_raises(self, tmp_path: Path):
        from snapwrap.reduction_artefacts.masking import build_swiss_cheese_from_transmission_monitor

        with pytest.raises(FileNotFoundError):
            build_swiss_cheese_from_transmission_monitor(
                run_number=12345,
                is_lite=True,
                output_dir=tmp_path / "out",
                file_prefix="tm_test",
                ipts=99999,
                nexus_path=tmp_path / "nope.nxs.h5",
                lam_min=0.5, lam_max=5.0,
            )

    @staticmethod
    def _make_mock_sc(out_dir: Path, prefix: str):
        """Mock swissCheese instance whose .save() writes a stub JSON file."""
        mock_sc = MagicMock()
        mock_sc.notchFromList = MagicMock()

        def _save(odir, pfx):
            (Path(odir) / f"{pfx}_Wavelength.json").write_text("{}")
        mock_sc.save.side_effect = _save
        return mock_sc

    def test_happy_path_with_mantid_mocked(self, tmp_path: Path, fake_nexus: Path):
        import numpy as np
        import importlib

        # Build a synthetic spectrum with two clear absorption notches.
        # x has the same length as y (point data after ConvertToPointData).
        n_bins = 1000
        x = np.linspace(0.5, 5.0, n_bins)
        y = np.full(n_bins, 1000.0)
        y[200:230] = 100.0   # notch ~ x[215]
        y[600:640] = 80.0    # notch ~ x[620]

        mock_ws = MagicMock()
        mock_ws.readX.return_value = x.tolist()
        mock_ws.readY.return_value = y.tolist()

        mock_mantid = MagicMock()
        # mtd[spec_ws] must support __getitem__
        mock_mantid.mtd.__getitem__.return_value = mock_ws

        out_dir = tmp_path / "out"
        mock_sc = self._make_mock_sc(out_dir, "tm_test")
        mock_sc_class = MagicMock(return_value=mock_sc)

        with patch.dict(sys.modules, {
            "mantid.simpleapi": mock_mantid,
            "snapwrap.maskUtils": MagicMock(swissCheese=mock_sc_class),
        }):
            import snapwrap.reduction_artefacts.masking as _m
            import snapwrap.reduction_artefacts.workspace_groups as _wg
            importlib.reload(_wg)
            importlib.reload(_m)
            # Make `n in present` work for the three intermediate ws.
            mock_mantid.mtd.getObjectNames.return_value = [
                "snapwrap_trans_12345_monitors",
                "snapwrap_trans_12345_rebinned",
                "snapwrap_trans_12345_spectrum",
            ]
            mask_paths, notches = _m.build_swiss_cheese_from_transmission_monitor(
                run_number=12345,
                is_lite=True,
                output_dir=out_dir,
                file_prefix="tm_test",
                ipts=99999,
                nexus_path=fake_nexus,
                lam_min=0.5,
                lam_max=5.0,
                rebin_step=0.0045,
                dip_threshold=0.6,
                continuum_window=151,
                min_width_aa=0.001,
                keep_diagnostics=False,
            )

        # Mantid pipeline calls
        mock_mantid.LoadNexusMonitors.assert_called_once()
        mock_mantid.ConvertUnits.assert_called_once()
        mock_mantid.Rebin.assert_called_once()
        mock_mantid.ConvertToPointData.assert_called_once()
        mock_mantid.ExtractSingleSpectrum.assert_called_once()
        # Two notches found, passed to swissCheese, and saved.
        assert len(notches) == 2
        mock_sc.notchFromList.assert_called_once_with("Wavelength", notches, True)
        mock_sc.save.assert_called_once()
        # Mask file written.
        assert len(mask_paths) == 1
        assert mask_paths[0].name == "tm_test_Wavelength.json"
        # keep_diagnostics=False → cleanup deletes the three intermediates.
        assert mock_mantid.DeleteWorkspace.call_count == 3
        # No diagnostic workspace produced when keep_diagnostics=False.
        mock_mantid.CreateWorkspace.assert_not_called()
        # And no group should have been created.
        mock_mantid.GroupWorkspaces.assert_not_called()

    def test_keep_workspaces_creates_diag_and_skips_cleanup(
        self, tmp_path: Path, fake_nexus: Path
    ):
        import numpy as np
        import importlib

        n_bins = 500
        x = np.linspace(0.5, 5.0, n_bins)  # point data: same length as y
        y = np.full(n_bins, 1000.0)
        y[200:220] = 100.0

        mock_ws = MagicMock()
        mock_ws.readX.return_value = x.tolist()
        mock_ws.readY.return_value = y.tolist()

        mock_mantid = MagicMock()
        mock_mantid.mtd.__getitem__.return_value = mock_ws

        out_dir = tmp_path / "out"
        mock_sc = self._make_mock_sc(out_dir, "tm_keep")
        mock_sc_class = MagicMock(return_value=mock_sc)

        with patch.dict(sys.modules, {
            "mantid.simpleapi": mock_mantid,
            "snapwrap.maskUtils": MagicMock(swissCheese=mock_sc_class),
        }):
            import snapwrap.reduction_artefacts.masking as _m
            import snapwrap.reduction_artefacts.workspace_groups as _wg
            importlib.reload(_wg)
            importlib.reload(_m)
            # All four diagnostic workspaces should be considered "present"
            # so the adoption helper will pass them to GroupWorkspaces.
            mock_mantid.mtd.getObjectNames.return_value = [
                "myprefix_monitors",
                "myprefix_rebinned",
                "myprefix_spectrum",
                "myprefix_diag",
                "myprefix_notches",
                "myprefix_kept",
            ]
            # Stub the TableWorkspace produced for _notches so addColumn/addRow
            # calls are absorbed by the mock.
            mock_mantid.CreateEmptyTableWorkspace.return_value = MagicMock()
            # mtd.doesExist must return False so the publishing path proceeds.
            mock_mantid.mtd.doesExist.return_value = False
            _m.build_swiss_cheese_from_transmission_monitor(
                run_number=12345,
                is_lite=False,
                output_dir=out_dir,
                file_prefix="tm_keep",
                ipts=99999,
                nexus_path=fake_nexus,
                lam_min=0.5,
                lam_max=5.0,
                rebin_step=0.009,
                dip_threshold=0.6,
                continuum_window=101,
                continuum_method="median",
                min_width_aa=0.001,
                keep_diagnostics=True,
                workspace_prefix="myprefix",
            )

        # Two CreateWorkspace calls: _diag (4-row stack) and _kept (2-row overlay).
        assert mock_mantid.CreateWorkspace.call_count == 2
        create_calls = {
            c.kwargs["OutputWorkspace"]: c.kwargs
            for c in mock_mantid.CreateWorkspace.call_args_list
        }
        assert set(create_calls) == {"myprefix_diag", "myprefix_kept"}
        diag_kw = create_calls["myprefix_diag"]
        assert diag_kw["NSpec"] == 4
        assert diag_kw["VerticalAxisValues"] == ["raw", "smoothed", "continuum", "ratio"]
        kept_kw = create_calls["myprefix_kept"]
        assert kept_kw["NSpec"] == 2
        assert kept_kw["VerticalAxisValues"] == ["ratio", "kept"]
        # The notch list is published as a TableWorkspace.
        mock_mantid.CreateEmptyTableWorkspace.assert_called_once_with(
            OutputWorkspace="myprefix_notches"
        )
        # No DeleteWorkspace when keep_diagnostics=True — intermediates are
        # adopted into the per-run diagnostics group instead.
        mock_mantid.DeleteWorkspace.assert_not_called()
        # The diagnostics group should have been created and contain all six ws.
        mock_mantid.GroupWorkspaces.assert_called_once()
        gw_kwargs = mock_mantid.GroupWorkspaces.call_args.kwargs
        assert gw_kwargs["OutputWorkspace"] == "wrap_diagnostics_12345"
        assert set(gw_kwargs["InputWorkspaces"]) == {
            "myprefix_monitors",
            "myprefix_rebinned",
            "myprefix_spectrum",
            "myprefix_diag",
            "myprefix_notches",
            "myprefix_kept",
        }
        # is_lite=False propagated to notchFromList.
        mock_sc.notchFromList.assert_called_once()
        assert mock_sc.notchFromList.call_args.args[2] is False
