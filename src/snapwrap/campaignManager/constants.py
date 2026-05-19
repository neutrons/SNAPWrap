"""Enumerations and column definitions for the Campaign Manager UI."""

from __future__ import annotations

from enum import Enum, auto


class ArtefactStatus(Enum):
    """Status pill for an artefact row."""

    ACTIVE = auto()
    RETIRED = auto()
    UNKNOWN = auto()


# String stored in the JSONL ``status`` field → enum.
STATUS_FROM_STRING = {
    "active": ArtefactStatus.ACTIVE,
    "retired": ArtefactStatus.RETIRED,
}

# Enum → display label (short, fits a status pill).
STATUS_LABEL = {
    ArtefactStatus.ACTIVE: "active",
    ArtefactStatus.RETIRED: "retired",
    ArtefactStatus.UNKNOWN: "?",
}

# Enum → colour name (resolved to QColor in the delegate).
STATUS_COLOUR = {
    ArtefactStatus.ACTIVE: "green",
    ArtefactStatus.RETIRED: "grey",
    ArtefactStatus.UNKNOWN: "amber",
}


# ── Artefact table columns ───────────────────────────────────────────────
#
# Each entry: (header, record_key, tooltip).  ``record_key`` is the dotted
# path inside an artefact-record dict; the model resolves it via
# :func:`_lookup`.

ARTEFACT_COLUMNS: list[tuple[str, str, str]] = [
    ("Status",       "status",                       "Active or retired"),
    ("Type",         "artefact_type",                "e.g. bin_mask, pixel_mask, crystal_species"),
    ("ID",           "artefact_id",                  "Artefact identifier (unique per campaign)"),
    ("Run",          "run_context.run_number",       "Run number this artefact applies to (if scoped)"),
    ("Method",       "method",                       "How the artefact was produced"),
    ("Created",      "created_at",                   "ISO timestamp"),
    ("By",           "created_by",                   "Provenance author"),
    ("Notes",        "notes",                        "Free-text notes"),
]


def lookup(record: dict, dotted_key: str):
    """Resolve a possibly dotted key inside an artefact record.

    Returns the empty string when any segment is missing — the table
    cells render falsy values as blanks.
    """
    cur = record
    for part in dotted_key.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return ""
    return cur if cur is not None else ""
