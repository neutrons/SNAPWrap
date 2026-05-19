"""Unit tests for snapwrap.reduction_artefacts.workspace_groups.

Cover the per-run ADS workspace-group policy:

* Naming helpers (``wrap_artefacts_{N}``, ``wrap_diagnostics_{N}``).
* ``finalize_builder_workspaces`` correctly groups artefacts and either
  groups or deletes diagnostics depending on the ``keep_diagnostics`` flag.
* Idempotent adoption: re-adopting the same workspaces is a no-op.
* ``purge_artefacts_for_run`` removes existing groups, no-ops on missing ones.
* All public helpers are no-ops when Mantid is unavailable.

Mantid is **never** imported here — every test mocks ``mantid.simpleapi``
via ``sys.modules`` and reloads :mod:`snapwrap.reduction_artefacts.workspace_groups`
to pick up the mock.
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock


def _reload_with_mock_mantid(mock_mantid):
    """Patch sys.modules with *mock_mantid* and return a freshly reloaded
    workspace_groups module."""
    sys.modules["mantid.simpleapi"] = mock_mantid
    import snapwrap.reduction_artefacts.workspace_groups as _wg
    return importlib.reload(_wg)


def test_name_helpers():
    """Naming convention: ``wrap_artefacts_<run>`` and ``wrap_diagnostics_<run>``."""
    # Don't need mantid for the name helpers; just import normally.
    from snapwrap.reduction_artefacts.workspace_groups import (
        artefact_group_name,
        diagnostic_group_name,
    )
    assert artefact_group_name(65891) == "wrap_artefacts_65891"
    assert diagnostic_group_name(65891) == "wrap_diagnostics_65891"


def test_finalize_keeps_diagnostics_via_grouping():
    """keep_diagnostics=True → diag ws grouped, none deleted."""
    mock = MagicMock()
    # Pretend all artefact + diagnostic workspaces exist.
    mock.mtd.getObjectNames.return_value = [
        "snapwrap_PKS_65891_UB1",
        "snapwrap_PKS_65891_UB2",
        "snapwrap_DSP_65891",
        "snapwrap_MD_65891",
        "snapwrap_PKS_65891",
    ]
    wg = _reload_with_mock_mantid(mock)

    wg.finalize_builder_workspaces(
        run_number=65891,
        artefact_ws=["snapwrap_PKS_65891_UB1", "snapwrap_PKS_65891_UB2"],
        diagnostic_ws=["snapwrap_DSP_65891", "snapwrap_MD_65891", "snapwrap_PKS_65891"],
        keep_diagnostics=True,
    )

    # Two groups created — one artefact, one diagnostics.
    group_calls = mock.GroupWorkspaces.call_args_list
    assert len(group_calls) == 2
    group_names = {c.kwargs["OutputWorkspace"] for c in group_calls}
    assert group_names == {"wrap_artefacts_65891", "wrap_diagnostics_65891"}

    # Nothing deleted.
    mock.DeleteWorkspace.assert_not_called()


def test_finalize_deletes_diagnostics_when_keep_false():
    """keep_diagnostics=False → artefact group created, diag ws deleted."""
    mock = MagicMock()
    mock.mtd.getObjectNames.return_value = [
        "snapwrap_PKS_65891_UB1",
        "snapwrap_DSP_65891",
        "snapwrap_MD_65891",
    ]
    wg = _reload_with_mock_mantid(mock)

    wg.finalize_builder_workspaces(
        run_number=65891,
        artefact_ws=["snapwrap_PKS_65891_UB1"],
        diagnostic_ws=["snapwrap_DSP_65891", "snapwrap_MD_65891"],
        keep_diagnostics=False,
    )

    # Single artefact group created.
    mock.GroupWorkspaces.assert_called_once()
    assert mock.GroupWorkspaces.call_args.kwargs["OutputWorkspace"] == (
        "wrap_artefacts_65891"
    )

    # Two diagnostic ws deleted.
    deleted = {c.kwargs.get("Workspace", c.args[0] if c.args else None)
               for c in mock.DeleteWorkspace.call_args_list}
    assert deleted == {"snapwrap_DSP_65891", "snapwrap_MD_65891"}


def test_finalize_skips_missing_workspaces_silently():
    """Workspaces not in the ADS are silently skipped (idempotent re-runs)."""
    mock = MagicMock()
    mock.mtd.getObjectNames.return_value = []  # nothing present
    wg = _reload_with_mock_mantid(mock)

    wg.finalize_builder_workspaces(
        run_number=42,
        artefact_ws=["ghost1", "ghost2"],
        diagnostic_ws=["ghost3"],
        keep_diagnostics=False,
    )

    mock.GroupWorkspaces.assert_not_called()
    mock.DeleteWorkspace.assert_not_called()


def test_adopt_extends_existing_group():
    """Adopting into an existing group adds members rather than recreating it."""
    mock = MagicMock()

    # Pretend the group already exists alongside a new candidate workspace.
    existing_group = MagicMock()
    existing_group.getNames.return_value = ["already_in"]

    def fake_getitem(name):
        if name == "wrap_artefacts_99":
            return existing_group
        return MagicMock()  # any ws lookup

    mock.mtd.__getitem__.side_effect = fake_getitem
    mock.mtd.getObjectNames.return_value = ["new_ws", "wrap_artefacts_99"]

    wg = _reload_with_mock_mantid(mock)
    # Make the existing group register as a WorkspaceGroup.
    type(existing_group).__name__ = "WorkspaceGroup"

    wg.adopt_into_artefact_group(["new_ws"], run_number=99)

    # No fresh GroupWorkspaces call — we extended the existing group.
    mock.GroupWorkspaces.assert_not_called()
    existing_group.add.assert_called_once_with("new_ws")


def test_purge_deletes_present_groups_only():
    """purge_artefacts_for_run deletes existing groups, ignores missing ones."""
    mock = MagicMock()
    # Only the artefact group exists.
    mock.mtd.getObjectNames.return_value = ["wrap_artefacts_77", "unrelated_ws"]
    wg = _reload_with_mock_mantid(mock)

    deleted = wg.purge_artefacts_for_run(77, include_diagnostics=True)

    assert deleted == ["wrap_artefacts_77"]
    mock.DeleteWorkspace.assert_called_once_with(Workspace="wrap_artefacts_77")


def test_purge_for_runs_aggregates():
    """purge_artefacts_for_runs accumulates deletions across many runs."""
    mock = MagicMock()
    mock.mtd.getObjectNames.return_value = [
        "wrap_artefacts_1",
        "wrap_diagnostics_1",
        "wrap_artefacts_2",
    ]
    wg = _reload_with_mock_mantid(mock)

    deleted = wg.purge_artefacts_for_runs([1, 2, 3], include_diagnostics=True)

    assert set(deleted) == {
        "wrap_artefacts_1",
        "wrap_diagnostics_1",
        "wrap_artefacts_2",
    }


def test_helpers_no_op_without_mantid(monkeypatch):
    """When mantid.simpleapi cannot be imported, every helper is a no-op."""
    monkeypatch.setitem(sys.modules, "mantid.simpleapi", None)
    # Reloading should set _mantid = None via the except branch.
    import snapwrap.reduction_artefacts.workspace_groups as wg
    importlib.reload(wg)

    assert wg.adopt_into_artefact_group(["a", "b"], run_number=1) is None
    assert wg.adopt_into_diagnostics_group(["a"], run_number=1) is None
    assert wg.purge_artefacts_for_run(1) == []
    # Should not raise even with no mantid present.
    wg.finalize_builder_workspaces(
        run_number=1,
        artefact_ws=["a"],
        diagnostic_ws=["b"],
        keep_diagnostics=True,
    )
