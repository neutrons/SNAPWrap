"""Reduction artefacts runtime support.

This package hosts executable contracts and helpers for reduction artefact
persistence/validation. Schema files are intentionally colocated here (not in
`docs/`) because they are consumed by runtime tooling.
"""

from .persistence import (
	SlugConflictError,
	append_jsonl_record,
	bootstrap_campaign,
	rename_campaign_slug,
	read_jsonl_records,
	resolve_campaign_slug,
	validate_jsonl_file,
	validate_record,
)
from .schema_paths import get_schema_path, list_schema_paths

__all__ = [
	"SlugConflictError",
	"append_jsonl_record",
	"bootstrap_campaign",
	"get_schema_path",
	"list_schema_paths",
	"rename_campaign_slug",
	"read_jsonl_records",
	"resolve_campaign_slug",
	"validate_jsonl_file",
	"validate_record",
]
