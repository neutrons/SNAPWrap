"""Enumerations and column definitions for the Calibration Manager UI."""

from enum import Enum, auto


class CalStatus(Enum):
    """Overall calibration status for a state.

    Classification depends on context:

    - **Without a run/cycle filter** the question is: "does this state
      have any calibrations at all?"  Only FULL, PARTIAL, UNCALIBRATED,
      and CORRUPT apply.

    - **With a run or cycle selected** the question becomes: "is there a
      *valid* calibration for that specific run?"  This is where the
      OUT_OF_CYCLE and UNMATCHED statuses become relevant — the state
      *has* calibrations, but none that apply to the selected run.

    The key insight (from operational experience) is that a state with
    five perfectly good 2024-B calibrations is **not** "uncalibrated" —
    it just needs a new calibration for 2025-A.  The UI must communicate
    this difference.
    """

    # ── Context-independent statuses ─────────────────────────────
    FULL = auto()           # valid difcal AND valid normcal
    PARTIAL = auto()        # one of difcal/normcal present, not both
    UNCALIBRATED = auto()   # no difcal and no normcal (no real calibrations exist at all)
    CORRUPT = auto()        # validateIndex reports failure for either type

    # ── Run/cycle-scoped statuses ────────────────────────────────
    OUT_OF_CYCLE = auto()   # calibrations exist and match appliesTo,
                            # but belong to a different cycle than the
                            # selected run.  Operationally: "needs
                            # recalibration for this cycle"

    UNMATCHED = auto()      # calibrations exist but the run number
                            # falls outside every entry's appliesTo
                            # range.  Operationally: "needs a calibration
                            # whose appliesTo covers this run"


class CalTypeStatus(Enum):
    """Per-calType status (difcal or normcal individually).

    This gives the model a finer-grained vocabulary for each calibration
    type before they are combined into the overall :class:`CalStatus`.
    """

    VALID = auto()              # valid calibration found for this run/cycle
    EXISTS_NO_RUN = auto()      # calibrations exist; no run was specified
    OUT_OF_CYCLE = auto()       # appliesTo matches but cycle doesn't
    UNMATCHED = auto()          # appliesTo doesn't cover this run at all
    UNCALIBRATED = auto()       # no real calibrations (difcal: only v0; normcal: no index)
    STATE_MISSING = auto()      # state folder doesn't exist
    CORRUPT_INDEX = auto()      # index JSON is missing or unparseable
    ERROR = auto()              # unexpected error


def caltype_status_from_detail(calStatus: dict) -> CalTypeStatus:
    """Map a ``checkCalibrationStatus`` result dict to a :class:`CalTypeStatus`.

    This is the single place that interprets the ``statusDetail`` string
    and the boolean flags, so the rest of the model and UI never need to
    parse free-text reason strings.
    """
    detail = calStatus.get("statusDetail", "")

    # ── error / corrupt cases ────────────────────────────────────
    if "does not exist" in detail:
        return CalTypeStatus.STATE_MISSING
    if "invalid JSON" in detail or "unexpected error" in detail:
        return CalTypeStatus.CORRUPT_INDEX

    # ── uncalibrated cases ───────────────────────────────────────
    if "no normalization index" in detail:
        return CalTypeStatus.UNCALIBRATED
    if "only has default" in detail:
        return CalTypeStatus.UNCALIBRATED

    # ── no run number provided ───────────────────────────────────
    if "no run number provided" in detail:
        return CalTypeStatus.EXISTS_NO_RUN

    # ── run was provided but didn't match ────────────────────────
    if calStatus.get("runIsCalibrated"):
        return CalTypeStatus.VALID

    if "out of cycle" in detail:
        return CalTypeStatus.OUT_OF_CYCLE

    if "no matching run range" in detail:
        return CalTypeStatus.UNMATCHED

    # fallback
    return CalTypeStatus.ERROR


def caltype_status_for_cycle(calStatus: dict, cycleID: str) -> CalTypeStatus:
    """Classify a calType's status when a *cycle* is selected (no run).

    Unlike :func:`caltype_status_from_detail`, this does not look at
    ``appliesTo`` ranges at all.  It asks only: "does this state have a
    calibration that belongs to *cycleID*?"

    The ``calStatus`` dict must have been obtained with
    ``checkCalibrationStatus(runNumber=None, ...)`` so that
    ``calibIndexList`` is populated and each entry has an annotated
    ``cycleID`` field.

    Parameters
    ----------
    calStatus : dict
        Result of ``checkCalibrationStatus(runNumber=None, ...)``.
    cycleID : str
        The cycle to match against (e.g. ``"2025-A"``).
    """
    detail = calStatus.get("statusDetail", "")

    # ── error / corrupt / missing ────────────────────────────────
    if "does not exist" in detail:
        return CalTypeStatus.STATE_MISSING
    if "invalid JSON" in detail or "unexpected error" in detail:
        return CalTypeStatus.CORRUPT_INDEX

    # ── uncalibrated cases ───────────────────────────────────────
    if "no normalization index" in detail:
        return CalTypeStatus.UNCALIBRATED
    if "only has default" in detail:
        return CalTypeStatus.UNCALIBRATED

    # ── calibrations exist — do any belong to this cycle? ────────
    entries = calStatus.get("calibIndexList", [])
    for entry in entries:
        if entry.get("cycleID") == cycleID:
            return CalTypeStatus.VALID

    # Entries exist but none from this cycle
    if entries:
        return CalTypeStatus.OUT_OF_CYCLE

    # Shouldn't reach here, but be safe
    return CalTypeStatus.UNCALIBRATED


def combine_caltype_statuses(
    dif: CalTypeStatus,
    nrm: CalTypeStatus,
    difCorrupt: bool = False,
    nrmCorrupt: bool = False,
) -> CalStatus:
    """Combine per-calType statuses into a single overall :class:`CalStatus`.

    Parameters
    ----------
    dif, nrm
        Individual caltype statuses.
    difCorrupt, nrmCorrupt
        Whether ``validateIndex`` flagged corruption for each type.

    Returns
    -------
    CalStatus
    """
    # Corruption takes priority
    if difCorrupt or nrmCorrupt:
        return CalStatus.CORRUPT
    if dif is CalTypeStatus.CORRUPT_INDEX or nrm is CalTypeStatus.CORRUPT_INDEX:
        return CalStatus.CORRUPT

    # Out-of-cycle: calibrations exist for both, but at least one
    # doesn't cover the selected cycle
    if dif is CalTypeStatus.OUT_OF_CYCLE or nrm is CalTypeStatus.OUT_OF_CYCLE:
        return CalStatus.OUT_OF_CYCLE

    # Unmatched: appliesTo doesn't cover the run
    if dif is CalTypeStatus.UNMATCHED or nrm is CalTypeStatus.UNMATCHED:
        return CalStatus.UNMATCHED

    # Both valid (or both exist when no run was specified)
    dif_ok = dif in (CalTypeStatus.VALID, CalTypeStatus.EXISTS_NO_RUN)
    nrm_ok = nrm in (CalTypeStatus.VALID, CalTypeStatus.EXISTS_NO_RUN)
    if dif_ok and nrm_ok:
        return CalStatus.FULL
    if dif_ok or nrm_ok:
        return CalStatus.PARTIAL

    return CalStatus.UNCALIBRATED


# Display helpers
STATUS_LABEL = {
    CalStatus.FULL: "Calibrated",
    CalStatus.PARTIAL: "Partial",
    CalStatus.UNCALIBRATED: "Uncalibrated",
    CalStatus.CORRUPT: "Corrupt",
    CalStatus.OUT_OF_CYCLE: "Out of Cycle",
    CalStatus.UNMATCHED: "Unmatched",
}

STATUS_COLOUR = {
    CalStatus.FULL: "green",
    CalStatus.PARTIAL: "amber",
    CalStatus.UNCALIBRATED: "red",
    CalStatus.CORRUPT: "orange",
    CalStatus.OUT_OF_CYCLE: "blue",
    CalStatus.UNMATCHED: "grey",
}

STATUS_TOOLTIP = {
    CalStatus.FULL: "Both difcal and normcal are valid for the selected run/cycle.",
    CalStatus.PARTIAL: "Only one of difcal or normcal is available.",
    CalStatus.UNCALIBRATED: "No calibrations exist for this state.",
    CalStatus.CORRUPT: "Index validation failed — repair may be needed.",
    CalStatus.OUT_OF_CYCLE: (
        "Calibrations exist and match the run range, but belong to a "
        "different operating cycle.  A new calibration is needed for "
        "the selected cycle."
    ),
    CalStatus.UNMATCHED: (
        "Calibrations exist but none have an appliesTo range that "
        "covers the selected run number."
    ),
}

# Tooltip shown in Mode A (no context selected) for the status LED
MODE_A_TOOLTIP = "Select a cycle or enter a run number to evaluate validity."


# ── State overview table column definitions ──────────────────────────────
# Each tuple: (header_text, dict_key, alignment)
#   alignment: "L" = left, "C" = centre, "R" = right

STATE_COLUMNS = [
    ("Status",     "status",           "C"),
    ("State ID",   "stateID",          "L"),
    ("arc1",       "arc1",             "R"),
    ("arc2",       "arc2",             "R"),
    ("wav",        "wav",              "R"),
    ("freq",       "freq",             "R"),
    ("pos",        "pos",              "R"),
    ("slit",       "slit",             "R"),
    ("#difcal",    "nDifcal",          "C"),
    ("difcal cycle", "latestDifcalCycle", "C"),
    ("#normcal",   "nNormcal",         "C"),
    ("normcal cycle", "latestNormcalCycle", "C"),
    ("Corrupt?",   "isCorrupt",        "C"),
]


# ── Calibration detail table column definitions ─────────────────────────

DETAIL_COLUMNS = [
    ("Version",    "version",          "C"),
    ("Run",        "effectiveRun",     "R"),
    ("Cycle",      "cycleID",          "C"),
    ("appliesTo",  "appliesTo",        "L"),
    ("Author",     "author",           "L"),
    ("Timestamp",  "timestamp",        "L"),
    ("Comments",   "comments",         "L"),
]
