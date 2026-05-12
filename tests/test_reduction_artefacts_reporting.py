from __future__ import annotations

import json
from pathlib import Path
import types

from snapwrap.reduction_artefacts import (
    append_jsonl_record,
    bootstrap_campaign,
    generate_requirement_reports_from_campaign_specs,
    generate_requirement_report_for_run,
    preflight_campaign_specs_seemeta,
)


def _campaign_root(tmp_path: Path) -> Path:
    return tmp_path / "SNS" / "SNAP" / "IPTS-35214" / "shared"


def test_generate_requirement_report_for_run_persists_manifest(tmp_path: Path) -> None:
    shared_root = _campaign_root(tmp_path)
    campaign = bootstrap_campaign(
        ipts=35214,
        campaign_slug="dac_fe_01",
        assembly_type="DAC",
        shared_root=shared_root,
    )

    campaign_dir = (
        shared_root
        / "snapwrap"
        / "reduction_artefacts"
        / "campaigns"
        / campaign["campaign_slug"]
    )
    artefacts_index = campaign_dir / "artefacts_index.jsonl"

    common = {
        "timestamp": campaign["created_at"],
        "campaign_id": campaign["campaign_id"],
        "campaign_slug": campaign["campaign_slug"],
        "ipts": campaign["ipts"],
        "intended_use": "pre_reduction",
        "version": 1,
        "status": "active",
        "path": "artefacts/placeholder.nxs",
        "provenance": {"created_by": "pytest"},
    }
    append_jsonl_record(
        artefacts_index,
        {
            **common,
            "record_id": "rec-bin-1",
            "artefact_id": "bin-1",
            "artefact_type": "bin_mask",
            "method": "bin_mask.from_ub_pair",
            "run_context": {"run_number": 1234, "state_id": None},
        },
        schema_name="artefact_record.schema.json",
    )
    append_jsonl_record(
        artefacts_index,
        {
            **common,
            "record_id": "rec-box-1",
            "artefact_id": "box-1",
            "artefact_type": "crystal_box",
            "method": "crystal_box.from_cif",
            "run_context": {"run_number": None, "state_id": None},
        },
        schema_name="artefact_record.schema.json",
    )

    report = generate_requirement_report_for_run(
        ipts=35214,
        campaign_identifier="dac_fe_01",
        run_number=1234,
        shared_root=shared_root,
        persist=True,
    )

    assert report["summary"]["ready"] is True
    assert report["summary"]["missing_required"] == 0
    assert report["report_path"]

    report_path = Path(report["report_path"])
    assert report_path.exists()
    with report_path.open("r", encoding="utf-8") as handle:
        persisted = json.load(handle)
    assert persisted["run_number"] == 1234
    assert persisted["campaign_slug"] == "dac_fe_01"


def test_generate_requirement_report_for_run_dry_run_no_manifest(tmp_path: Path) -> None:
    shared_root = _campaign_root(tmp_path)
    bootstrap_campaign(
        ipts=35214,
        campaign_slug="pe_h2o_01",
        assembly_type="PE",
        shared_root=shared_root,
    )

    report = generate_requirement_report_for_run(
        ipts=35214,
        campaign_identifier="pe_h2o_01",
        run_number=4321,
        shared_root=shared_root,
        persist=False,
    )

    assert report["report_path"] is None
    assert report["assembly_type"] == "PE"
    assert report["summary"]["missing_required"] == 2


def test_generate_requirement_report_for_run_ad_hoc_dry_run_without_state(tmp_path: Path) -> None:
    shared_root = _campaign_root(tmp_path)
    shared_root.mkdir(parents=True, exist_ok=True)

    report = generate_requirement_report_for_run(
        ipts=35214,
        campaign_identifier="dac_fe_01",
        run_number=5001,
        shared_root=shared_root,
        assembly_type="DAC",
        persist=False,
    )

    assert report["campaign_slug"] == "dac_fe_01"
    assert report["campaign_id"] is None
    assert report["assembly_type"] == "DAC"
    assert report["summary"]["required_total"] == 2
    assert report["report_path"] is None


def test_generate_requirement_reports_from_campaign_specs_mixed_run_entries(tmp_path: Path) -> None:
    shared_root = _campaign_root(tmp_path)
    shared_root.mkdir(parents=True, exist_ok=True)

    seemeta_path = tmp_path / "seemeta_2002.json"
    seemeta_path.write_text('{"assembly_type": "PE"}\n', encoding="utf-8")

    campaign_specs = [
        {
            "campaign": "dac_fe_01",
            "assembly_type": "DAC",
            "runs": [
                2001,
                {"run": 2002, "seemeta_json": str(seemeta_path)},
                {"run_number": 2003, "assembly_type": "DAC"},
            ],
        }
    ]

    reports = generate_requirement_reports_from_campaign_specs(
        ipts=35214,
        campaign_specs=campaign_specs,
        shared_root=shared_root,
        persist=False,
    )

    assert len(reports) == 3
    by_run = {r["run_number"]: r for r in reports}
    assert by_run[2001]["assembly_type"] == "DAC"
    assert by_run[2002]["assembly_type"] == "PE"
    assert by_run[2003]["assembly_type"] == "DAC"
    assert all(r["report_path"] is None for r in reports)


def test_generate_requirement_report_auto_acquire_meta_type(monkeypatch, tmp_path: Path) -> None:
    shared_root = _campaign_root(tmp_path)
    shared_root.mkdir(parents=True, exist_ok=True)

    def _fake_import_module(name: str):
        assert name == "snapwrap.SEEMeta.utils"
        return types.SimpleNamespace(acquireMeta=lambda run: {"type": "PE"})

    monkeypatch.setattr(
        "snapwrap.reduction_artefacts.requirements.importlib.import_module",
        _fake_import_module,
    )

    report = generate_requirement_report_for_run(
        ipts=35214,
        campaign_identifier="pe_auto_01",
        run_number=6001,
        shared_root=shared_root,
        require_seemeta=True,
        persist=False,
    )

    assert report["assembly_type"] == "PE"
    assert report["summary"]["required_total"] == 2
    assert report["seemeta_present"] is True
    assert report["report_path"] is None


def test_generate_requirement_report_strict_seemeta_raises_when_missing(monkeypatch, tmp_path: Path) -> None:
    shared_root = _campaign_root(tmp_path)
    shared_root.mkdir(parents=True, exist_ok=True)

    def _fake_import_module(name: str):
        assert name == "snapwrap.SEEMeta.utils"
        return types.SimpleNamespace(acquireMeta=lambda run: None)

    monkeypatch.setattr(
        "snapwrap.reduction_artefacts.requirements.importlib.import_module",
        _fake_import_module,
    )

    try:
        generate_requirement_report_for_run(
            ipts=35214,
            campaign_identifier="dac_missing_01",
            run_number=7001,
            shared_root=shared_root,
            require_seemeta=True,
            persist=False,
        )
    except ValueError as exc:
        assert "SEEMeta is required" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected ValueError for missing strict SEEMeta")


def test_preflight_campaign_specs_seemeta_reports_sources(monkeypatch, tmp_path: Path) -> None:
    seemeta_path = tmp_path / "seemeta_8102.json"
    seemeta_path.write_text('{"type": "DAC"}\n', encoding="utf-8")

    def _fake_import_module(name: str):
        assert name == "snapwrap.SEEMeta.utils"

        def _acquire(run: int):
            if run == 8101:
                return {"type": "PE"}
            if run == 8103:
                return None
            return None

        return types.SimpleNamespace(acquireMeta=_acquire)

    monkeypatch.setattr(
        "snapwrap.reduction_artefacts.requirements.importlib.import_module",
        _fake_import_module,
    )

    rows = preflight_campaign_specs_seemeta(
        campaign_specs=[
            {
                "campaign": "camp_01",
                "runs": [
                    8101,
                    {"run": 8102, "seemeta_json": str(seemeta_path)},
                    8103,
                ],
            }
        ]
    )

    by_run = {row["run_number"]: row for row in rows}
    assert by_run[8101]["seemeta_present"] is True
    assert by_run[8101]["source"] == "acquireMeta"
    assert by_run[8101]["assembly_type"] == "PE"

    assert by_run[8102]["seemeta_present"] is True
    assert by_run[8102]["source"] == "seemeta_json"
    assert by_run[8102]["assembly_type"] == "DAC"

    assert by_run[8103]["seemeta_present"] is False
    assert by_run[8103]["source"] == "none"

