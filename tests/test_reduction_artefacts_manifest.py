"""Tests for Phase C+ campaign manifest schema v0.2.0 + persistence functions.

Schema validation:
  M1.1 Valid manifest passes.
  M1.2 Missing slug rejected.
  M1.3 Missing ipts rejected.
  M1.4 Unknown assembly_asset type rejected.
  M1.5 candidate_species missing cif rejected.
  M1.6 candidate_species with null eos accepted.
  M1.7 Null ruby_pressure_gpa accepted.
  M1.8 Object ruby_pressure_gpa accepted.

bootstrap_campaign_from_manifest:
  M2.1 Explicit assembly_type → campaign created, CIF assets registered.
  M2.2 SEEMeta inference via source_run.
  M2.3 SEEMeta file missing → FileNotFoundError.
  M2.4 No assembly_type and no source_run → ValueError.
  M2.5 Duplicate slug → SlugConflictError.
  M2.6 Living manifest copied into campaign dir.
  M2.7 assembly_assets registered in assets_index.

annotate_run:
  M3.1 ruby_before_gpa written on first call.
  M3.2 ruby_after_gpa merged without clobbering before.
  M3.3 observed_species written.
  M3.4 Unset kwargs do not overwrite existing values.
  M3.5 Unknown run_number raises KeyError.
  M3.6 Missing living manifest raises FileNotFoundError.

add_candidate_species:
  M4.1 New species appended to manifest + CIF asset registered.
  M4.2 Duplicate species_id raises ValueError.
  M4.3 Missing required field raises KeyError.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import ValidationError

from snapwrap.reduction_artefacts import (
    SlugConflictError,
    add_candidate_species,
    annotate_run,
    bootstrap_campaign,
    bootstrap_campaign_from_manifest,
    list_asset_records,
    validate_record,
)


# ── helpers ───────────────────────────────────────────────────────────────────

_W_EOS = {
    "type": "vinet", "order": 3,
    "V_0": 15.862, "V_0_unit": "A3/atom", "Z": 2,
    "K_0": 295.2, "K_prime": 4.32,
    "source": "Dewaele 2004",
}


def _species(species_id: str = "tungsten", role: str = "calibrant",
             cif: str = "/data/W.cif", eos=None) -> dict:
    entry: dict = {"species_id": species_id, "role": role, "cif": cif}
    entry["eos"] = eos
    return entry


def _minimal_manifest(
    slug: str = "test-campaign",
    ipts: int = 1,
    *,
    assembly_type: str | None = "DAC",
    source_run: int | None = None,
    candidate_species: list | None = None,
    assembly_assets: list | None = None,
    runs: list | None = None,
) -> dict:
    camp: dict = {"slug": slug, "ipts": ipts}
    if assembly_type is not None:
        camp["assembly_type"] = assembly_type
    if source_run is not None:
        camp["source_run"] = source_run
    manifest: dict = {
        "schema_version": "0.2.0",
        "campaign": camp,
        "candidate_species": candidate_species if candidate_species is not None else [],
        "runs": runs if runs is not None else [],
    }
    if assembly_assets:
        manifest["assembly_assets"] = assembly_assets
    return manifest


def _write_manifest(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _write_see_file(see_dir: Path, run_number: int,
                    assembly: str = "assembly.dac") -> Path:
    see_dir.mkdir(parents=True, exist_ok=True)
    see_file = see_dir / f"SEE{run_number:06d}.json"
    see_file.write_text(json.dumps({"type": assembly, "components": []}))
    return see_file


# ── M1 Schema validation ──────────────────────────────────────────────────────

def test_valid_manifest_passes_schema():
    manifest = _minimal_manifest(
        candidate_species=[_species(eos=_W_EOS)],
        runs=[{"run_number": 1, "ruby_pressure_gpa": None, "observed_species": None}],
    )
    validate_record(manifest, "campaign_manifest.schema.json")


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


def test_manifest_unknown_assembly_asset_type_rejected():
    manifest = _minimal_manifest(
        assembly_assets=[{
            "asset_id": "bad",
            "asset_type": "unknown_type",
            "path": "/data/bad.txt",
            "provenance": {"source": "manual", "created_by": "tester"},
        }]
    )
    with pytest.raises(ValidationError):
        validate_record(manifest, "campaign_manifest.schema.json")


def test_manifest_candidate_species_missing_cif_rejected():
    species = {"species_id": "w", "role": "calibrant"}  # no cif
    manifest = _minimal_manifest(candidate_species=[species])
    with pytest.raises(ValidationError):
        validate_record(manifest, "campaign_manifest.schema.json")


def test_manifest_candidate_species_null_eos_accepted():
    manifest = _minimal_manifest(candidate_species=[_species(eos=None)])
    validate_record(manifest, "campaign_manifest.schema.json")


def test_manifest_run_null_ruby_accepted():
    manifest = _minimal_manifest(
        runs=[{"run_number": 1, "ruby_pressure_gpa": None}]
    )
    validate_record(manifest, "campaign_manifest.schema.json")


def test_manifest_run_object_ruby_accepted():
    manifest = _minimal_manifest(
        runs=[{
            "run_number": 1,
            "ruby_pressure_gpa": {"before": 3.1, "after": 3.15, "nominal": 3.1}
        }]
    )
    validate_record(manifest, "campaign_manifest.schema.json")


# ── M2 bootstrap_campaign_from_manifest ──────────────────────────────────────

def test_bootstrap_explicit_assembly_type(tmp_path):
    manifest = _minimal_manifest(
        slug="explicit-dac", ipts=99, assembly_type="DAC",
        candidate_species=[
            _species("w", cif="/data/W.cif"),
            _species("brucite", role="sample", cif="/data/B.cif"),
        ],
    )
    mf = _write_manifest(tmp_path / "mf.json", manifest)
    result = bootstrap_campaign_from_manifest(mf, shared_root=tmp_path)

    assert result["campaign"]["assembly_type"] == "DAC"
    assert result["campaign"]["campaign_slug"] == "explicit-dac"
    assert len(result["candidate_species"]) == 2
    assert {s["species_id"] for s in result["candidate_species"]} == {"w", "brucite"}

    assets = list_asset_records(ipts=99, campaign_identifier="explicit-dac",
                                shared_root=tmp_path)
    assert len(assets) == 2
    assert all(a["asset_type"] == "cif" for a in assets)


def test_bootstrap_seemeta_inference(tmp_path):
    see_dir = tmp_path / "SEE"
    _write_see_file(see_dir, run_number=65891, assembly="assembly.dac")

    manifest = _minimal_manifest(
        slug="seemeta-infer", ipts=99,
        assembly_type=None, source_run=65891,
    )
    mf = _write_manifest(tmp_path / "mf.json", manifest)
    result = bootstrap_campaign_from_manifest(
        mf, shared_root=tmp_path, seemeta_dir=see_dir
    )
    assert result["campaign"]["assembly_type"] == "DAC"


def test_bootstrap_seemeta_missing_file(tmp_path):
    manifest = _minimal_manifest(
        slug="seemeta-missing", ipts=99,
        assembly_type=None, source_run=99999,
    )
    mf = _write_manifest(tmp_path / "mf.json", manifest)
    see_dir = tmp_path / "SEE"
    see_dir.mkdir()

    with pytest.raises(FileNotFoundError, match="SEEMeta file not found"):
        bootstrap_campaign_from_manifest(mf, shared_root=tmp_path,
                                         seemeta_dir=see_dir)


def test_bootstrap_no_assembly_raises(tmp_path):
    manifest = _minimal_manifest(
        slug="no-assembly", ipts=99, assembly_type=None, source_run=None
    )
    mf = _write_manifest(tmp_path / "mf.json", manifest)
    with pytest.raises(ValueError, match="assembly_type.*source_run"):
        bootstrap_campaign_from_manifest(mf, shared_root=tmp_path)


def test_bootstrap_duplicate_slug_raises(tmp_path):
    manifest = _minimal_manifest(slug="dup-slug", ipts=99, assembly_type="DAC")
    mf = _write_manifest(tmp_path / "mf.json", manifest)
    bootstrap_campaign_from_manifest(mf, shared_root=tmp_path)
    with pytest.raises(SlugConflictError):
        bootstrap_campaign_from_manifest(mf, shared_root=tmp_path)


def test_bootstrap_living_manifest_copied(tmp_path):
    manifest = _minimal_manifest(slug="living-test", ipts=99, assembly_type="DAC")
    mf = _write_manifest(tmp_path / "mf.json", manifest)
    bootstrap_campaign_from_manifest(mf, shared_root=tmp_path)

    living = (
        tmp_path / "snapwrap" / "reduction_artefacts"
        / "campaigns" / "living-test" / "manifest.json"
    )
    assert living.exists()
    data = json.loads(living.read_text())
    assert data["campaign"]["slug"] == "living-test"


def test_bootstrap_assembly_assets_registered(tmp_path):
    manifest = _minimal_manifest(
        slug="asm-assets", ipts=99, assembly_type="DAC",
        assembly_assets=[{
            "asset_id": "ub-01",
            "asset_type": "ub_matrix",
            "path": "/data/ub.mat",
            "provenance": {"source": "manual", "created_by": "tester"},
        }],
    )
    mf = _write_manifest(tmp_path / "mf.json", manifest)
    result = bootstrap_campaign_from_manifest(mf, shared_root=tmp_path)

    assert len(result["assembly_assets"]) == 1
    assert result["assembly_assets"][0]["asset_id"] == "ub-01"

    assets = list_asset_records(ipts=99, campaign_identifier="asm-assets",
                                shared_root=tmp_path)
    assert any(a["asset_id"] == "ub-01" for a in assets)


# ── M3 annotate_run ──────────────────────────────────────────────────────────

def _bootstrap_with_runs(tmp_path: Path, slug: str,
                          runs: list | None = None) -> dict:
    manifest = _minimal_manifest(
        slug=slug, ipts=99, assembly_type="DAC",
        runs=runs or [{"run_number": 42}],
    )
    mf = _write_manifest(tmp_path / f"{slug}.json", manifest)
    return bootstrap_campaign_from_manifest(mf, shared_root=tmp_path)


def _read_living(tmp_path: Path, slug: str) -> dict:
    path = (
        tmp_path / "snapwrap" / "reduction_artefacts"
        / "campaigns" / slug / "manifest.json"
    )
    return json.loads(path.read_text())


def test_annotate_run_ruby_before(tmp_path):
    _bootstrap_with_runs(tmp_path, "ar-ruby")
    annotate_run(ipts=99, campaign_identifier="ar-ruby", run_number=42,
                 shared_root=tmp_path, ruby_before_gpa=3.1)

    ruby = _read_living(tmp_path, "ar-ruby")["runs"][0]["ruby_pressure_gpa"]
    assert ruby["before"] == 3.1
    assert "after" not in ruby


def test_annotate_run_ruby_merge(tmp_path):
    _bootstrap_with_runs(tmp_path, "ar-merge")
    annotate_run(ipts=99, campaign_identifier="ar-merge", run_number=42,
                 shared_root=tmp_path, ruby_before_gpa=3.1)
    annotate_run(ipts=99, campaign_identifier="ar-merge", run_number=42,
                 shared_root=tmp_path, ruby_after_gpa=3.15, ruby_nominal_gpa=3.1)

    ruby = _read_living(tmp_path, "ar-merge")["runs"][0]["ruby_pressure_gpa"]
    assert ruby["before"] == 3.1
    assert ruby["after"] == 3.15
    assert ruby["nominal"] == 3.1


def test_annotate_run_observed_species(tmp_path):
    _bootstrap_with_runs(tmp_path, "ar-obs",
                         runs=[{"run_number": 42, "observed_species": None}])
    obs = [{"species_id": "w", "lattice_params": {"a": 3.138}, "pressure_gpa": 3.24}]
    annotate_run(ipts=99, campaign_identifier="ar-obs", run_number=42,
                 shared_root=tmp_path, observed_species=obs)

    run = _read_living(tmp_path, "ar-obs")["runs"][0]
    assert run["observed_species"][0]["pressure_gpa"] == 3.24
    assert run["observed_species"][0]["lattice_params"]["a"] == 3.138


def test_annotate_run_unset_does_not_overwrite(tmp_path):
    _bootstrap_with_runs(tmp_path, "ar-unset", runs=[{"run_number": 1}])
    annotate_run(ipts=99, campaign_identifier="ar-unset", run_number=1,
                 shared_root=tmp_path, ruby_before_gpa=5.0)
    annotate_run(ipts=99, campaign_identifier="ar-unset", run_number=1,
                 shared_root=tmp_path, ruby_after_gpa=5.1)

    ruby = _read_living(tmp_path, "ar-unset")["runs"][0]["ruby_pressure_gpa"]
    assert ruby["before"] == 5.0
    assert ruby["after"] == 5.1


def test_annotate_run_unknown_run_raises(tmp_path):
    _bootstrap_with_runs(tmp_path, "ar-badrun", runs=[{"run_number": 1}])
    with pytest.raises(KeyError, match="9999"):
        annotate_run(ipts=99, campaign_identifier="ar-badrun", run_number=9999,
                     shared_root=tmp_path, ruby_before_gpa=1.0)


def test_annotate_run_missing_manifest_raises(tmp_path):
    bootstrap_campaign(ipts=99, campaign_slug="no-mf-camp",
                       assembly_type="DAC", shared_root=tmp_path)
    with pytest.raises(FileNotFoundError, match="Living manifest"):
        annotate_run(ipts=99, campaign_identifier="no-mf-camp",
                     run_number=1, shared_root=tmp_path, ruby_before_gpa=1.0)


# ── M4 add_candidate_species ─────────────────────────────────────────────────

def test_add_candidate_species(tmp_path):
    manifest = _minimal_manifest(
        slug="add-sp", ipts=99, assembly_type="DAC",
        candidate_species=[_species("w", cif="/data/W.cif")],
        runs=[{"run_number": 1}],
    )
    mf = _write_manifest(tmp_path / "mf.json", manifest)
    bootstrap_campaign_from_manifest(mf, shared_root=tmp_path)

    cif_record = add_candidate_species(
        ipts=99, campaign_identifier="add-sp",
        species_def={
            "species_id": "brucite-ii",
            "role": "sample",
            "cif": "/data/brucite-II.cif",
            "stability_pressure": [15.0, None],
        },
        shared_root=tmp_path,
    )

    assert cif_record["asset_type"] == "cif"
    assert cif_record["asset_id"] == "cif-brucite-ii"

    species_ids = [
        s["species_id"]
        for s in _read_living(tmp_path, "add-sp")["candidate_species"]
    ]
    assert "brucite-ii" in species_ids

    assets = list_asset_records(ipts=99, campaign_identifier="add-sp",
                                shared_root=tmp_path)
    assert any(a["asset_id"] == "cif-brucite-ii" for a in assets)


def test_add_candidate_species_duplicate_raises(tmp_path):
    manifest = _minimal_manifest(
        slug="dup-sp", ipts=99, assembly_type="DAC",
        candidate_species=[_species("w", cif="/data/W.cif")],
    )
    mf = _write_manifest(tmp_path / "mf.json", manifest)
    bootstrap_campaign_from_manifest(mf, shared_root=tmp_path)

    with pytest.raises(ValueError, match="already exists"):
        add_candidate_species(
            ipts=99, campaign_identifier="dup-sp",
            species_def={"species_id": "w", "role": "calibrant", "cif": "/data/W.cif"},
            shared_root=tmp_path,
        )


def test_add_candidate_species_missing_field_raises(tmp_path):
    manifest = _minimal_manifest(slug="miss-sp", ipts=99, assembly_type="DAC")
    mf = _write_manifest(tmp_path / "mf.json", manifest)
    bootstrap_campaign_from_manifest(mf, shared_root=tmp_path)

    with pytest.raises(KeyError, match="cif"):
        add_candidate_species(
            ipts=99, campaign_identifier="miss-sp",
            species_def={"species_id": "new", "role": "sample"},
            shared_root=tmp_path,
        )
