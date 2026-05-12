from __future__ import annotations

import pytest

from snapwrap.reduction_artefacts import (
    build_requirement_report,
    build_requirement_report_from_seemeta,
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
