"""Reduction artefacts runtime support.

This package hosts executable contracts and helpers for reduction artefact
persistence/validation. Schema files are intentionally colocated here (not in
`docs/`) because they are consumed by runtime tooling.
"""

from .persistence import (
	SlugConflictError,
	append_jsonl_record,
	bootstrap_campaign,
	list_asset_records,
	register_asset_record,
	rename_campaign_slug,
	read_jsonl_records,
	resolve_campaign_slug,
	validate_jsonl_file,
	validate_record,
)
from .assets import (
	ApplicabilityScope,
	AssetApplicability,
	AssetRecord,
	AssetStatus,
	AssetType,
	LoadedAsset,
)
from .asset_artefact_examples import (
	ArtefactDefinition,
	AssetArtefactExample,
	AssetDefinition,
	EOSObject,
	PixelMaskWorkspaceObject,
	SwissCheeseObject,
	build_crystal_species_from_cif,
	build_example_artefact,
	list_asset_artefact_examples,
)
from .requirements import (
	build_requirement_report,
	build_requirement_report_from_seemeta,
	generate_requirement_reports_from_campaign_specs,
	generate_requirement_report_for_run,
	get_requirement_specs,
	infer_assembly_type_from_seemeta,
	normalize_assembly_type,
	preflight_campaign_specs_seemeta,
)
from .schema_paths import get_schema_path, list_schema_paths

__all__ = [
	"SlugConflictError",
	"append_jsonl_record",
	"ApplicabilityScope",
	"ArtefactDefinition",
	"AssetArtefactExample",
	"AssetApplicability",
	"AssetDefinition",
	"AssetRecord",
	"AssetStatus",
	"AssetType",
	"bootstrap_campaign",
	"build_example_artefact",
	"build_crystal_species_from_cif",
	"build_requirement_report",
	"build_requirement_report_from_seemeta",
	"EOSObject",
	"generate_requirement_reports_from_campaign_specs",
	"generate_requirement_report_for_run",
	"get_schema_path",
	"get_requirement_specs",
	"infer_assembly_type_from_seemeta",
	"list_asset_records",
	"list_asset_artefact_examples",
	"list_schema_paths",
	"LoadedAsset",
	"normalize_assembly_type",
	"PixelMaskWorkspaceObject",
	"preflight_campaign_specs_seemeta",
	"register_asset_record",
	"rename_campaign_slug",
	"read_jsonl_records",
	"resolve_campaign_slug",
	"SwissCheeseObject",
	"validate_jsonl_file",
	"validate_record",
]
