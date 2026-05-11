"""Helpers for locating reduction artefact JSON schemas at runtime."""

from __future__ import annotations

from pathlib import Path

_SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"


def get_schema_path(name: str) -> Path:
    """Return absolute path to a named schema file.

    Args:
        name: File name (e.g. ``campaign.schema.json``).
    """
    return (_SCHEMA_DIR / name).resolve()


def list_schema_paths() -> dict[str, Path]:
    """Return all known schema paths keyed by file name."""
    return {p.name: p for p in sorted(_SCHEMA_DIR.glob("*.json"))}
