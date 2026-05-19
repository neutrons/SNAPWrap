from __future__ import annotations

import json
from pathlib import Path

import pytest

from snapwrap.reduction_artefacts import (
    bootstrap_campaign,
    build_requirement_report,
    build_requirement_report_from_seemeta,
    generate_requirement_report_for_run,
    infer_assembly_type_from_seemeta,
    normalize_assembly_type,
)


def test_normalize_assembly_type_aliases() -> None:
    assert normalize_assembly_type("dac") == "DAC"
    assert normalize_assembly_type("DIAMOND_ANVIL_CELL") == "DAC"
    assert normalize_assembly_type("assembly.dac") == "DAC"
    assert normalize_assembly_type("pe cell") == "PE"
    assert normalize_assembly_type("assembly.pe") == "PE"
    assert normalize_assembly_type("OTHER") == "OTHER"


def test_build_requirement_report_dac_defaults_and_missing() -> None:
    report = build_requirement_report(assembly_type="DAC")

    assert report["assembly_type"] == "DAC"
    assert report["summary"]["required_total"] == 2
    assert report["summary"]["missing_required"] == 2
    assert report["summary"]["ready"] is False

    # Deterministic ordering by artefact_type.
    artefact_types = [row["artefact_type"] for row in report["requirements"]]
    assert artefact_types == ["bin_mask", "crystal_box"]

    bin_mask = report["requirements"][0]
    assert bin_mask["preferred_method"] == "bin_mask.from_ub_pair"


def test_build_requirement_report_dac_method_preference_and_availability() -> None:
    artefact_records = [
        {
            "artefact_id": "bm-001",
            "artefact_type": "bin_mask",
            "status": "active",
            "run_context": {"run_number": 1234},
        }
    ]

    report = build_requirement_report(
        assembly_type="DAC",
        run_number=1234,
        method_preferences={"bin_mask": ["bin_mask.from_transmission", "bin_mask.from_ub_pair"]},
        artefact_records=artefact_records,
    )

    by_type = {row["artefact_type"]: row for row in report["requirements"]}
    assert by_type["bin_mask"]["available"] is True
    assert by_type["bin_mask"]["active_ids"] == ["bm-001"]
    assert by_type["bin_mask"]["preferred_method"] == "bin_mask.from_transmission"
    assert by_type["crystal_box"]["missing"] is True
    assert report["summary"]["missing_required"] == 1


def test_build_requirement_report_from_seemeta_pe() -> None:
    seemeta = {"assembly_type": "PE"}
    report = build_requirement_report_from_seemeta(seemeta=seemeta)

    assert infer_assembly_type_from_seemeta(seemeta) == "PE"
    assert report["assembly_type"] == "PE"
    assert [r["artefact_type"] for r in report["requirements"]] == [
        "attenuation_workspace",
        "pixel_mask",
    ]


def test_build_requirement_report_invalid_assembly() -> None:
    with pytest.raises(ValueError):
        build_requirement_report(assembly_type="XYZ")


def test_infer_assembly_type_from_seemeta_missing_field() -> None:
    with pytest.raises(KeyError):
        infer_assembly_type_from_seemeta({"instrument": "SNAP"})


def test_infer_assembly_type_from_real_see_record() -> None:
    """Regression: real SEE records use top-level 'type' field (C+.0 fix)."""
    # Mimics the structure of /SNS/SNAP/IPTS-33219/shared/SEE/SEE065891.json
    seemeta = {"type": "assembly.dac", "components": []}
    assert infer_assembly_type_from_seemeta(seemeta) == "DAC"


def test_infer_assembly_type_from_seemeta_type_key_not_assembly() -> None:
    """A 'type' value that isn't an assembly type should fall through to KeyError."""
    with pytest.raises(KeyError):
        infer_assembly_type_from_seemeta({"type": "some_other_thing"})


def test_build_requirement_report_other_assembly_is_unsupported() -> None:
    report = build_requirement_report(assembly_type="OTHER")
    assert report["assembly_type"] == "OTHER"
    assert report["unsupported"] is True
    assert report["requirements"] == []
    assert report["summary"]["required_total"] == 0
    assert report["summary"]["ready"] is True


def test_build_requirement_report_non_other_assembly_not_unsupported() -> None:
    report = build_requirement_report(assembly_type="DAC")
    assert report.get("unsupported") is False


def _shared_root(tmp_path: Path) -> Path:
    return tmp_path / "SNS" / "SNAP" / "IPTS-35214" / "shared"


def test_generate_requirement_report_for_run_persist_round_trip(tmp_path: Path) -> None:
    """Report is written to manifests/requirements_run_<run>.json and round-trips."""
    shared_root = _shared_root(tmp_path)
    bootstrap_campaign(
        ipts=35214,
        campaign_slug="dac_fe_01",
        assembly_type="DAC",
        shared_root=shared_root,
    )

    report = generate_requirement_report_for_run(
        ipts=35214,
        campaign_identifier="dac_fe_01",
        run_number=1001,
        shared_root=shared_root,
        assembly_type="DAC",
        persist=True,
    )

    assert report["ipts"] == 35214
    assert report["run_number"] == 1001
    assert report["campaign_slug"] == "dac_fe_01"
    assert report["summary"]["required_total"] == 2

    manifest_path = Path(report["report_path"])
    assert manifest_path.exists()

    with manifest_path.open("r", encoding="utf-8") as fh:
        reloaded = json.load(fh)

    assert reloaded["run_number"] == 1001
    assert reloaded["summary"]["ready"] is False


def test_generate_requirement_report_for_run_no_persist(tmp_path: Path) -> None:
    shared_root = _shared_root(tmp_path)
    bootstrap_campaign(
        ipts=35214,
        campaign_slug="dac_fe_01",
        assembly_type="DAC",
        shared_root=shared_root,
    )
    report = generate_requirement_report_for_run(
        ipts=35214,
        campaign_identifier="dac_fe_01",
        run_number=1001,
        shared_root=shared_root,
        assembly_type="DAC",
        persist=False,
    )
    assert report["report_path"] is None
    manifest_path = (
        tmp_path / "SNS" / "SNAP" / "IPTS-35214" / "shared"
        / "snapwrap" / "reduction_artefacts" / "campaigns" / "dac_fe_01"
        / "manifests" / "requirements_run_1001.json"
    )
    assert not manifest_path.exists()
