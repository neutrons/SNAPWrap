"""Workflow queue data model for the Campaign Manager.

A :class:`WorkflowQueue` is a per-run ordered list of :class:`WorkflowStep`
objects that records which operations to perform and with which artefacts.
The queue is persisted as JSON in the campaign directory
(``workflow_queue_{run}.json``) and loaded by the WorkflowPanel on startup.

Execution is handled by the Campaign Manager model layer and WorkflowPanel,
not here — this module is a pure data model (no Mantid, no Qt).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


#: Valid step type identifiers — order here is the canonical execution order.
STEP_TYPES: tuple[str, ...] = ("reduce", "resample", "crop")

#: Human-readable labels for each step type.
STEP_LABELS: dict[str, str] = {
    "reduce": "Reduce",
    "resample": "Resample",
    "crop": "Crop",
}

#: Default params for each step type (used when creating a new step).
STEP_DEFAULTS: dict[str, dict[str, Any]] = {
    "reduce": {
        "keepUnfocussed": False,
        "verbose": False,
        "continueNoDifcal": False,
        "continueNoVan": False,
    },
    "resample": {
        "sample_factor": 1.0,
    },
    "crop": {
        "edge_bins": 0,
        "min_coverage": 0.002,
        "force_recompute": False,
        "diagnostics": False,
    },
}

#: Artefact types that gate each step (step cannot be added if these are absent).
STEP_REQUIRED_ARTEFACTS: dict[str, list[str]] = {
    "reduce": [],
    "resample": [],
    "crop": ["bin_mask"],
}


@dataclass
class WorkflowStep:
    """One step in a workflow queue.

    Args:
        step_type: One of ``"reduce"``, ``"resample"``, or ``"crop"``.
        params: Step-specific parameters (e.g. ``{"edge_bins": 0}`` for crop).
        artefact_selections: Maps artefact_type → list of artefact_ids selected
            by the user.  For example::

                {
                    "bin_mask": ["binmask-wavelength-monitor-run65893",
                                 "binmask-dspacing-json"],
                    "pixel_mask": ["pixmask-pe-lite"],
                }

            An artefact_id suffixed with ``:MISSING`` means it was copied from
            another run and is not (yet) present in the current campaign.
    """

    step_type: str
    params: dict[str, Any] = field(default_factory=dict)
    artefact_selections: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WorkflowStep:
        return cls(
            step_type=d["step_type"],
            params=dict(d.get("params") or {}),
            artefact_selections={
                k: list(v)
                for k, v in (d.get("artefact_selections") or {}).items()
            },
        )

    @classmethod
    def default(cls, step_type: str) -> WorkflowStep:
        """Return a new step with default params and empty artefact selections."""
        return cls(
            step_type=step_type,
            params=dict(STEP_DEFAULTS.get(step_type, {})),
        )

    def has_missing_artefacts(self) -> bool:
        """Return True if any selected artefact ID is suffixed with ':MISSING'."""
        return any(
            aid.endswith(":MISSING")
            for ids in self.artefact_selections.values()
            for aid in ids
        )


class WorkflowQueue:
    """Per-run ordered list of :class:`WorkflowStep` objects with JSON persistence.

    Design constraints:
    - At most one step of each type (enforced by :meth:`replace`).
    - Steps are stored in execution order (reduce → resample → crop).
    - Persisted as ``workflow_queue_{run}.json`` in the campaign directory.
    """

    FILENAME_TEMPLATE = "workflow_queue_{run}.json"

    def __init__(
        self,
        run_number: int,
        steps: list[WorkflowStep] | None = None,
    ) -> None:
        self.run_number = run_number
        self.steps: list[WorkflowStep] = list(steps or [])

    # ── mutation ──────────────────────────────────────────────────────────────

    def append(self, step: WorkflowStep) -> None:
        """Append *step* to the end of the queue.

        Raises:
            ValueError: A step of the same type already exists.
        """
        if self.has_step(step.step_type):
            raise ValueError(
                f"A '{step.step_type}' step already exists in the queue. "
                "Use replace() to update it."
            )
        self.steps.append(step)

    def replace(self, step: WorkflowStep) -> None:
        """Replace the first step of the same type, or append if absent."""
        for i, s in enumerate(self.steps):
            if s.step_type == step.step_type:
                self.steps[i] = step
                return
        self.steps.append(step)

    def remove(self, step_type: str) -> bool:
        """Remove the step of the given type.  Returns True if a step was removed."""
        before = len(self.steps)
        self.steps = [s for s in self.steps if s.step_type != step_type]
        return len(self.steps) < before

    def clear(self) -> None:
        self.steps.clear()

    # ── queries ───────────────────────────────────────────────────────────────

    def get_step(self, step_type: str) -> WorkflowStep | None:
        for s in self.steps:
            if s.step_type == step_type:
                return s
        return None

    def has_step(self, step_type: str) -> bool:
        return any(s.step_type == step_type for s in self.steps)

    def has_missing_artefacts(self) -> bool:
        return any(s.has_missing_artefacts() for s in self.steps)

    # ── persistence ───────────────────────────────────────────────────────────

    @classmethod
    def _queue_path(cls, campaign_dir: Path, run_number: int) -> Path:
        return campaign_dir / cls.FILENAME_TEMPLATE.format(run=run_number)

    def save(self, campaign_dir: Path) -> Path:
        """Write the queue to ``campaign_dir/workflow_queue_{run}.json``.

        Creates the directory if needed.  Returns the path written.
        """
        path = self._queue_path(campaign_dir, self.run_number)
        payload: dict[str, Any] = {
            "run_number": self.run_number,
            "steps": [s.to_dict() for s in self.steps],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, campaign_dir: Path, run_number: int) -> WorkflowQueue:
        """Load from ``campaign_dir/workflow_queue_{run}.json``.

        Returns an empty queue if the file does not exist.
        """
        path = cls._queue_path(campaign_dir, run_number)
        if not path.exists():
            return cls(run_number=run_number)
        data = json.loads(path.read_text(encoding="utf-8"))
        steps = [WorkflowStep.from_dict(d) for d in data.get("steps", [])]
        return cls(run_number=run_number, steps=steps)

    # ── copy-from-run ─────────────────────────────────────────────────────────

    @classmethod
    def copy_from_run(
        cls,
        source: WorkflowQueue,
        target_run: int,
        available_artefact_ids: set[str],
    ) -> WorkflowQueue:
        """Copy a queue to a new run, flagging artefacts not present in the target.

        Step types and params are copied verbatim.  Each artefact ID that is
        *not* in *available_artefact_ids* is suffixed with ``:MISSING`` so the
        UI can warn the user before execution.
        """
        new_steps: list[WorkflowStep] = []
        for step in source.steps:
            new_sels: dict[str, list[str]] = {}
            for atype, ids in step.artefact_selections.items():
                new_sels[atype] = [
                    aid if aid in available_artefact_ids else f"{aid}:MISSING"
                    for aid in ids
                ]
            new_steps.append(WorkflowStep(
                step_type=step.step_type,
                params=dict(step.params),
                artefact_selections=new_sels,
            ))
        return cls(run_number=target_run, steps=new_steps)
