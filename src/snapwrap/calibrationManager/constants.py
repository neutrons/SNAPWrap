"""Enumerations and column definitions for the Calibration Manager UI."""

from enum import Enum, auto


class CalStatus(Enum):
    """Overall calibration status for a state (relative to a given cycle/run)."""

    FULL = auto()        # valid difcal AND valid normcal
    PARTIAL = auto()     # one of difcal/normcal present, not both
    UNCALIBRATED = auto()  # neither difcal nor normcal
    CORRUPT = auto()     # validateIndex reports failure for either type


# Display helpers
STATUS_LABEL = {
    CalStatus.FULL: "Calibrated",
    CalStatus.PARTIAL: "Partial",
    CalStatus.UNCALIBRATED: "Uncalibrated",
    CalStatus.CORRUPT: "Corrupt",
}

STATUS_COLOUR = {
    CalStatus.FULL: "green",
    CalStatus.PARTIAL: "amber",
    CalStatus.UNCALIBRATED: "red",
    CalStatus.CORRUPT: "orange",
}


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
    ("Run",        "runNumber",        "R"),
    ("Cycle",      "cycleID",          "C"),
    ("appliesTo",  "appliesTo",        "L"),
    ("Timestamp",  "timestamp",        "L"),
    ("Comments",   "comments",         "L"),
]
