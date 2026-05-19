"""Mantid ADS workspace-tree management for reduction-artefact builders.

In the main interactive use-case — a long-lived Mantid Workbench session in
which the operator re-runs a campaign script as new neutron runs arrive —
the reduction-artefact builders deposit a handful of workspaces in the ADS
on each call (UB-indexed peaks, monitor spectra, MD workspaces, swiss-cheese
diagnostics, ...).  Without house-keeping the workspace tree quickly turns
into clutter.

This module provides a thin, idempotent policy layer that keeps the tree
tidy by sorting per-run outputs into two sibling :class:`WorkspaceGroup`
containers:

* ``wrap_artefacts_{run}``    — workspaces the operator usually keeps
  (e.g. the indexed-peaks workspaces produced by the UB-derivation pipeline).
* ``wrap_diagnostics_{run}``  — *intermediate* workspaces useful for
  inspection / debugging (raw event ws, MD ws, monitor spectra, swiss-cheese
  diagnostic ws).  Only present when ``keep_diagnostics=True``.

A third helper :func:`purge_artefacts_for_run` removes both groups (and
their member workspaces) — the "delete everything after reduction" use case.

All functions are no-ops when Mantid is not importable (tests / docs).
"""

from __future__ import annotations

import importlib as _importlib
from collections.abc import Iterable
from typing import Any

try:  # pragma: no cover — covered indirectly in environments with Mantid
    _mantid: Any = _importlib.import_module("mantid.simpleapi")
except Exception:  # pragma: no cover
    _mantid = None


# ── Naming convention ───────────────────────────────────────────────────────

ARTEFACT_GROUP_PREFIX = "wrap_artefacts_"
DIAGNOSTIC_GROUP_PREFIX = "wrap_diagnostics_"


def artefact_group_name(run_number: int) -> str:
    """Return the canonical artefact-group name for *run_number*."""
    return f"{ARTEFACT_GROUP_PREFIX}{run_number}"


def diagnostic_group_name(run_number: int) -> str:
    """Return the canonical diagnostic-group name for *run_number*."""
    return f"{DIAGNOSTIC_GROUP_PREFIX}{run_number}"


# ── Internals ───────────────────────────────────────────────────────────────

def _existing(ws_names: Iterable[str]) -> list[str]:
    """Filter *ws_names* to those actually present in the Mantid ADS."""
    if _mantid is None:
        return []
    present = set(_mantid.mtd.getObjectNames())
    return [n for n in ws_names if n in present]


def _adopt(ws_names: Iterable[str], group_name: str) -> str | None:
    """Group *ws_names* under *group_name*, creating or extending as needed.

    * Workspaces that don't currently exist are silently skipped.
    * Workspaces already belonging to another group are ungrouped first
      (Mantid forbids a workspace being in two groups simultaneously).
    * If *group_name* already exists, new members are added to it;
      otherwise a fresh group is created.
    * If after filtering there are no workspaces to group **and** the group
      doesn't yet exist, no group is created (returns ``None``).
    """
    if _mantid is None:
        return None

    names = _existing(ws_names)
    if not names:
        if group_name in _mantid.mtd.getObjectNames():
            return group_name
        return None

    # Ungroup any incoming ws that's currently in a different group.
    for n in names:
        ws = _mantid.mtd[n]
        parent = getattr(ws, "getGroupNames", lambda: [])()
        # Newer Mantid: ws.isInGroup() or look at all groups for membership.
        for existing_group_name in _mantid.mtd.getObjectNames():
            try:
                g = _mantid.mtd[existing_group_name]
            except Exception:
                continue
            if not _is_group(g):
                continue
            if existing_group_name == group_name:
                continue
            try:
                if n in list(g.getNames()):
                    g.remove(n)
            except Exception:
                pass
        del parent  # unused — defensive lookup only

    if group_name in _mantid.mtd.getObjectNames() and _is_group(
        _mantid.mtd[group_name]
    ):
        grp = _mantid.mtd[group_name]
        existing_members = set(grp.getNames())
        for n in names:
            if n not in existing_members:
                grp.add(n)
    else:
        # If the name exists but isn't a group, refuse to clobber.
        if group_name in _mantid.mtd.getObjectNames():
            raise RuntimeError(
                f"Cannot create group {group_name!r}: a non-group workspace "
                f"with that name already exists."
            )
        _mantid.GroupWorkspaces(InputWorkspaces=names, OutputWorkspace=group_name)
    return group_name


def _is_group(ws: Any) -> bool:
    """Return True iff *ws* is a WorkspaceGroup."""
    return type(ws).__name__ == "WorkspaceGroup" or hasattr(ws, "getNames")


# ── Public API ──────────────────────────────────────────────────────────────

def adopt_into_artefact_group(
    ws_names: Iterable[str],
    *,
    run_number: int,
) -> str | None:
    """Move *ws_names* into the per-run artefact group.

    Returns the group name (or ``None`` if Mantid is unavailable or no
    workspaces were present to group and no pre-existing group exists).
    Idempotent and safe to call multiple times in the same session.
    """
    return _adopt(ws_names, artefact_group_name(run_number))


def adopt_into_diagnostics_group(
    ws_names: Iterable[str],
    *,
    run_number: int,
) -> str | None:
    """Move *ws_names* into the per-run diagnostics group."""
    return _adopt(ws_names, diagnostic_group_name(run_number))


def finalize_builder_workspaces(
    *,
    run_number: int,
    artefact_ws: Iterable[str] = (),
    diagnostic_ws: Iterable[str] = (),
    keep_diagnostics: bool,
) -> None:
    """Standard end-of-builder house-keeping.

    Sends *artefact_ws* into the artefact group.  Then, depending on
    *keep_diagnostics*:

    * ``True``  — send *diagnostic_ws* into the diagnostics group.
    * ``False`` — delete *diagnostic_ws* (workspaces that don't exist are
      skipped silently).
    """
    if _mantid is None:
        return

    adopt_into_artefact_group(artefact_ws, run_number=run_number)

    if keep_diagnostics:
        adopt_into_diagnostics_group(diagnostic_ws, run_number=run_number)
    else:
        for n in _existing(diagnostic_ws):
            try:
                _mantid.DeleteWorkspace(Workspace=n)
            except Exception:
                pass


def purge_artefacts_for_run(
    run_number: int,
    *,
    include_diagnostics: bool = True,
) -> list[str]:
    """Delete the artefact (and optionally diagnostics) group for *run_number*.

    Returns the list of group names that were actually deleted.  Missing
    groups are silently skipped — safe to call eagerly.
    """
    if _mantid is None:
        return []

    deleted: list[str] = []
    targets = [artefact_group_name(run_number)]
    if include_diagnostics:
        targets.append(diagnostic_group_name(run_number))

    present = set(_mantid.mtd.getObjectNames())
    for name in targets:
        if name in present:
            try:
                _mantid.DeleteWorkspace(Workspace=name)
                deleted.append(name)
            except Exception:
                pass
    return deleted


def purge_artefacts_for_runs(
    run_numbers: Iterable[int],
    *,
    include_diagnostics: bool = True,
) -> list[str]:
    """Convenience: :func:`purge_artefacts_for_run` for many runs."""
    deleted: list[str] = []
    for r in run_numbers:
        deleted.extend(
            purge_artefacts_for_run(r, include_diagnostics=include_diagnostics)
        )
    return deleted
