"""Tests for Phase C+ campaign manifest schema + bootstrap_campaign_from_manifest.

C+.2.1 Schema validation — valid manifest passes; bad manifests rejected.
C+.2.2 bootstrap_campaign_from_manifest with explicit assembly_type.
C+.2.3 bootstrap_campaign_from_manifest with SEEMeta-driven assembly_type inference.
C+.2.4 Missing both assembly_type and source_run raises ValueError.
C+.2.5 Duplicate slug raises SlugConflictError.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from jsonschema import ValidationError

from snapwrap.reduction_artefacts import (
    SlugConflictError,
    bootstrap_campaign_from_manifest,
    list_asset_records,
    validate_record,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _minimal_manifest(
    slug: str = "test-campaign",
    ipts: int = 1,
    *,
    assembly_type: str | None = "DAC",
    source_run: int | None = None,
    assets: list | None = None,
) -> dict:
    camp: dict = {"slug": slug, "ipts": ipts}
    if assembly_type is not None:
        camp["assembly_type"] = assembly_type
    if source_run is not None:
        camp["source_run"] = source_run
    return {
        "schema_version": "0.1.0",
        "campaign": camp,
        "assets": assets if assets is not None else [],
    }


def _write_manifest(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _write_see_file(see_dir: Path, run_number: int, assembly: str = "assembly.dac") -> Path:
    see_dir.mkdir(parents=True, exist_ok=True)
    see_file = see_dir / f"SEE{run_number:06d}.json"
    see_file.write_text(json.dumps({"type": assembly, "components": []}), encoding="utf-8")
    return see_file


# ── C+.2.1 Schema validation ─────────────────────────────────────────────────

def test_valid_manifest_passes_schema():
    manifest = _minimal_manifest()
    validate_record(manifest, "campaign_manifest.schema.json")  # must not raise


def test_manifest_missing_slug_rejected():
    manifest = _minimal_manifest()
    del manifest["campaign"]["slug"]
    with pytest.raises(ValidationError):
        validate_record(manifest, "campaign_manifest.schema.json")


def test_manifest_missing_ipts_rejected():
    manifest = _minimal_manifest()
    del manifest["campaign"]["ipts"]
    with pytest.raises(ValidationError):
        validate_record(manifest, "campaign_manifest.schema.json")


def test_manifest_unknown_asset_type_rejected():
    assets = [
        {
            "asset_id": "bad-asset",
            "asset_type": "unknown_type",
            "path": "/data/bad.txt",
        }
    ]
    manifest = _minimal_manifest(assets=assets)
    with pytest.raises(ValidationError):
        validate_record(manifest, "campaign_manifest.schema.json")


def test_manifest_missing_assets_key_rejected():
    manifest = _minimal_manifest()
    del manifest["assets"]
    with pytest.raises(ValidationError):
        validate_record(manifest, "campaign_manifest.schema.json")


def test_manifest_all_asset_types_accepted():
    """All enum values in the schema are accepted."""
    for at in ("cif", "eos_description", "phase_description",
               "ub_matrix", "seemeta_json", "manual_pixel_mask", "other"):
        assets = [{"asset_id": f"a-{at}", "asset_type": at, "path": f"/data/x.{at}"}]
        manifest = _minimal_manifest(assets=assets)
        validate_record(manifest, "campaign_manifest.schema.json")  # must not raise


# ── C+.2.2 Explicit assembly_type ────────────────────────────────────────────

def test_bootstrap_campaign_from_manifest_explicit_assembly_type(tmp_path):
    assets = [
        {
            "asset_id": "cif-w-01",
            "asset_type": "cif",
            "path": "/data/W.cif",
            "provenance": {"source": "imported", "created_by": "tester"},
        },
        {
            "asset_id": "eos-w-01",
            "asset_type": "eos_description",
            "path": "/data/W.eos.json",
            "applicability": {"scope": "campaign"},
            "provenance": {"source": "manual", "created_by": "tester", "notes": "test eos"},
        },
    ]
    manifest = _minimal_manifest(
        slug="explicit-dac",
        ipts=99,
        assembly_type="DAC",
        assets=assets,
    )
    mf = _write_manifest(tmp_path / "manifest.json", manifest)

    result = bootstrap_campaign_from_manifest(mf, shared_root=tmp_path)

    assert result["campaign"]["assembly_type"] == "DAC"
    assert result["campaign"]["campaign_slug"] == "explicit-dac"
    assert len(result["assets"]) == 2

    registered = list_asset_records(
        ipts=99,
        campaign_identifier="explicit-dac",
        shared_root=tmp_path,
    )
    assert len(registered) == 2
    asset_ids = {r["asset_id"] for r in registered}
    assert asset_ids == {"cif-w-01", "eos-w-01"}


def test_bootstrap_campaign_from_manifest_creates_assets_index(tmp_path):
    manifest = _minimal_manifest(
        slug="index-check",
        ipts=99,
        assembly_type="PE",
        assets=[{"asset_id": "pk-01", "asset_type": "other", "path": "/data/pk.dat"}],
    )
    mf = _write_manifest(tmp_path / "mf.json", manifest)
    bootstrap_campaign_from_manifest(mf, shared_root=tmp_path)

    index_path = (
        tmp_path / "snapwrap" / "reduction_artefacts" / "campaigns"
        / "index-check" / "assets_index.jsonl"
    )
    assert index_path.exists()
    lines = [l for l in index_path.read_text().splitlines() if l.strip()]
    assert len(lines) == 1


# ── C+.2.3 SEEMeta-driven assembly_type inference ────────────────────────────

def test_bootstrap_campaign_from_manifest_seemeta_inference(tmp_path):
    see_dir = tmp_path / "SEE"
    _write_see_file(see_dir, run_number=65891, assembly="assembly.dac")

    manifest = _minimal_manifest(
        slug="seemeta-infer",
        ipts=99,
        assembly_type=None,
        source_run=65891,
    )
    mf = _write_manifest(tmp_path / "mf.json", manifest)

    result = bootstrap_campaign_from_manifest(
        mf,
        shared_root=tmp_path,
        seemeta_dir=see_dir,
    )
    assert result["campaign"]["assembly_type"] == "DAC"


def test_bootstrap_campaign_from_manifest_seemeta_missing_file(tmp_path):
    manifest = _minimal_manifest(
        slug="seemeta-missing",
        ipts=99,
        assembly_type=None,
        source_run=99999,
    )
    mf = _write_manifest(tmp_path / "mf.json", manifest)
    see_dir = tmp_path / "SEE"  # empty — no SEE file present

    with pytest.raises(FileNotFoundError, match="SEEMeta file not found"):
        bootstrap_campaign_from_manifest(mf, shared_root=tmp_path, seemeta_dir=see_dir)


# ── C+.2.4 No assembly_type and no source_run → ValueError ───────────────────

def test_bootstrap_campaign_from_manifest_no_assembly_raises(tmp_path):
    manifest = _minimal_manifest(
        slug="no-assembly",
        ipts=99,
        assembly_type=None,
        source_run=None,
    )
    mf = _write_manifest(tmp_path / "mf.json", manifest)

    with pytest.raises(ValueError, match="assembly_type.*source_run"):
        bootstrap_campaign_from_manifest(mf, shared_root=tmp_path)


# ── C+.2.5 Duplicate slug raises SlugConflictError ───────────────────────────

def test_bootstrap_campaign_from_manifest_duplicate_slug_raises(tmp_path):
    manifest = _minimal_manifest(slug="dup-slug", ipts=99, assembly_type="DAC")
    mf = _write_manifest(tmp_path / "mf.json", manifest)

    bootstrap_campaign_from_manifest(mf, shared_root=tmp_path)

    with pytest.raises(SlugConflictError):
        bootstrap_campaign_from_manifest(mf, shared_root=tmp_path)
