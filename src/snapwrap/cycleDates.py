"""cycleDates  –  map SNAP run numbers to facility operating cycles.

Workflow
--------
1. Instrument scientists maintain a LibreOffice Calc spreadsheet (.ods) with
   columns: cycleID, startDate, stopDate, firstRun.
   Rows may appear in any order (the module sorts by startDate).
   Future cycles whose firstRun is not yet known should have a blank/NaN
   firstRun; these rows are stored in the JSON but excluded from run-number
   lookups.
2. ``build_cycle_json()`` reads that spreadsheet, validates the data and writes
   a versioned JSON file to a standard location.
3. ``get_cycle_for_run(run_number)`` performs a fast lookup against the cached
   JSON data to return the cycle ID for a given run.

Paths default to ``{Config["instrument.calibration.home"]}/cycleDates.{ods,json}``
but can be overridden.
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional

import pandas as pd

from snapred.meta.Config import Config

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------
_CAL_HOME: str = Config["instrument.calibration.home"]
DEFAULT_ODS: str = os.path.join(_CAL_HOME, "cycleDates.ods")
DEFAULT_JSON: str = os.path.join(_CAL_HOME, "cycleDates.json")

# ---------------------------------------------------------------------------
# Module-level cache (populated once per session unless explicitly rebuilt)
# ---------------------------------------------------------------------------
_CYCLE_CACHE: Optional[List[Dict[str, Any]]] = None
_CACHE_VERSION: Optional[int] = None

# Expected spreadsheet columns
_REQUIRED_COLUMNS = {"cycleID", "startDate", "stopDate", "firstRun"}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _parse_date(val: Any, label: str, row_idx: int) -> datetime.date:
    """Parse a value as YYYY-MM-DD, raising ValueError with context on failure.

    Accepts ``datetime.date``, ``datetime.datetime``, pandas ``Timestamp``,
    or an ISO-format string.
    """
    if isinstance(val, datetime.datetime):
        return val.date()
    if isinstance(val, datetime.date):
        return val
    s = str(val).strip()
    try:
        return datetime.date.fromisoformat(s)
    except (ValueError, TypeError):
        raise ValueError(
            f"Row {row_idx}: '{label}' value '{val}' is not a valid YYYY-MM-DD date"
        )


def _validate_dataframe(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Validate a DataFrame read from the .ods and return a list of cycle dicts.

    The DataFrame is sorted by startDate ascending before validation so the
    spreadsheet rows need not be in any particular order.

    Rows whose ``firstRun`` is blank / NaN are treated as future cycles: they
    are included in the output (with ``firstRun: null``) but skipped during
    overlap and monotonicity checks on firstRun.

    Checks performed:
    - Required columns present.
    - No duplicate cycleIDs.
    - Dates parse as YYYY-MM-DD and stopDate >= startDate.
    - firstRun values (when present) are positive integers.
    - After sorting, no overlapping date ranges.
    - firstRun values are monotonically increasing (consistent with date order).
    """
    # --- column check ---
    missing = _REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Spreadsheet missing required columns: {sorted(missing)}")

    # drop completely empty rows that Calc sometimes appends
    df = df.dropna(how="all").reset_index(drop=True)

    if df.empty:
        raise ValueError("Spreadsheet contains no data rows")

    # --- sort by startDate ascending ---
    # parse dates into a temporary column for sorting, then iterate in order
    df = df.copy()
    df["_start_parsed"] = [
        _parse_date(row["startDate"], "startDate", i) for i, row in df.iterrows()
    ]
    df = df.sort_values("_start_parsed").reset_index(drop=True)

    # --- per-row validation ---
    records: List[Dict[str, Any]] = []
    seen_ids: set = set()
    prev_end: Optional[datetime.date] = None
    prev_first_run: Optional[int] = None
    prev_last_run: Optional[int] = None

    for i, row in df.iterrows():
        cycle_id = str(row["cycleID"]).strip()
        if cycle_id in seen_ids:
            raise ValueError(f"Row {i}: duplicate cycleID '{cycle_id}'")
        seen_ids.add(cycle_id)

        start = _parse_date(row["startDate"], "startDate", i)
        stop = _parse_date(row["stopDate"], "stopDate", i)
        if stop < start:
            raise ValueError(
                f"Row {i} ('{cycle_id}'): stopDate ({stop}) < startDate ({start})"
            )

        # firstRun — may be NaN for future cycles
        raw_first = row["firstRun"]
        first_run: Optional[int] = None
        if pd.notna(raw_first):
            try:
                first_run = int(raw_first)
            except (ValueError, TypeError):
                raise ValueError(
                    f"Row {i} ('{cycle_id}'): firstRun '{raw_first}' is not a valid integer"
                )
            if first_run < 1:
                raise ValueError(
                    f"Row {i} ('{cycle_id}'): firstRun must be a positive integer, got {first_run}"
                )

        # lastRun — optional column, and optional per row.  Its absence means
        # "this cycle has no recorded end", which is treated permissively (see
        # resolve_cycle_for_run); setting it is what closes a cycle so that
        # runs beyond it read as undecided rather than in-cycle.
        last_run: Optional[int] = None
        if "lastRun" in df.columns:
            raw_last = row["lastRun"]
            if pd.notna(raw_last):
                try:
                    last_run = int(raw_last)
                except (ValueError, TypeError):
                    raise ValueError(
                        f"Row {i} ('{cycle_id}'): lastRun '{raw_last}' is not a valid integer"
                    )
                if first_run is None:
                    raise ValueError(
                        f"Row {i} ('{cycle_id}'): lastRun ({last_run}) set but firstRun is blank"
                    )
                if last_run < first_run:
                    raise ValueError(
                        f"Row {i} ('{cycle_id}'): lastRun ({last_run}) < firstRun ({first_run})"
                    )

        # no overlapping date ranges
        if prev_end is not None and start <= prev_end:
            raise ValueError(
                f"Row {i} ('{cycle_id}'): startDate ({start}) overlaps with previous cycle "
                f"stopDate ({prev_end})"
            )

        # a cycle must end before the next one begins
        if prev_last_run is not None and first_run is not None and first_run <= prev_last_run:
            raise ValueError(
                f"Row {i} ('{cycle_id}'): firstRun ({first_run}) is not greater than the "
                f"previous cycle's lastRun ({prev_last_run}) — cycles would overlap"
            )

        # firstRun monotonically increasing (skip when either is None)
        if first_run is not None and prev_first_run is not None and first_run <= prev_first_run:
            raise ValueError(
                f"Row {i} ('{cycle_id}'): firstRun ({first_run}) must be greater than "
                f"previous firstRun ({prev_first_run})"
            )

        records.append({
            "cycleID": cycle_id,
            "startDate": start.isoformat(),
            "stopDate": stop.isoformat(),
            "firstRun": first_run,
            "lastRun": last_run,
        })

        prev_end = stop
        if first_run is not None:
            prev_first_run = first_run
        prev_last_run = last_run

    return records


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_cycle_json(
    ods_path: Optional[str] = None,
    json_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Read the .ods spreadsheet, validate, write versioned JSON, and update cache.

    Parameters
    ----------
    ods_path : str, optional
        Path to the LibreOffice Calc spreadsheet.  Defaults to
        ``{calibration.home}/cycleDates.ods``.
    json_path : str, optional
        Destination for the JSON file.  Defaults to
        ``{calibration.home}/cycleDates.json``.

    Returns
    -------
    list[dict]
        The validated list of cycle records (also cached in-module).
    """
    global _CYCLE_CACHE, _CACHE_VERSION

    ods_path = ods_path or DEFAULT_ODS
    json_path = json_path or DEFAULT_JSON

    have_ods = os.path.isfile(ods_path)
    have_json = os.path.isfile(json_path)

    # If the .ods is missing we can still proceed when a valid JSON exists —
    # there is simply nothing new to compare against.
    if not have_ods:
        if have_json:
            # Fall back to loading from the existing JSON.
            return load_cycle_data(json_path=json_path)
        # Neither source exists — nothing we can do.
        raise FileNotFoundError(f"Cycle-dates spreadsheet not found: {ods_path}")

    try:
        df = pd.read_excel(ods_path, engine="odf")
    except PermissionError:
        if have_json:
            import warnings
            warnings.warn(
                f"cycleDates: no read permission for {ods_path}; "
                "falling back to existing JSON.",
                stacklevel=2,
            )
            return load_cycle_data(json_path=json_path)
        raise
    records = _validate_dataframe(df)

    # Compare against existing JSON — only write if the cycle data changed.
    existing_version = 0
    existing_cycles: Optional[List[Dict[str, Any]]] = None
    if have_json:
        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
            existing_version = int(existing.get("version", 0))
            existing_cycles = existing.get("cycles", [])
        except Exception:
            existing_cycles = None  # force rewrite on corrupt/unreadable JSON

    if existing_cycles == records:
        # Nothing changed — keep current version, skip the write.
        print(
            f"cycleDates: {json_path} is already up-to-date "
            f"({len(records)} cycle(s), version {existing_version})"
        )
        _CYCLE_CACHE = records
        _CACHE_VERSION = existing_version
        return records

    new_version = existing_version + 1 if existing_version else 1

    payload = {
        "version": new_version,
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": str(ods_path),
        "cycles": records,
    }

    try:
        Path(json_path).parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        print(f"cycleDates: wrote {len(records)} cycle(s) to {json_path} (version {new_version})")
    except PermissionError:
        import warnings
        warnings.warn(
            f"cycleDates: no write permission for {json_path}; "
            "using in-memory data parsed from .ods. "
            "An instrument scientist can update the JSON by running snapwrap.",
            stacklevel=2,
        )

    # refresh module cache
    _CYCLE_CACHE = records
    _CACHE_VERSION = new_version

    return records


def load_cycle_data(
    json_path: Optional[str] = None,
    rebuild: bool = False,
    ods_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return the list of cycle records, loading from JSON (or rebuilding from .ods).

    The result is cached for the lifetime of the Python session.  Pass
    ``rebuild=True`` to force a re-read of the .ods spreadsheet, re-validate
    and rewrite the JSON.

    Parameters
    ----------
    json_path : str, optional
        Path to the JSON file.
    rebuild : bool
        If True, re-reads the .ods and regenerates the JSON before loading.
    ods_path : str, optional
        Path to the .ods (only used when *rebuild* is True).

    Returns
    -------
    list[dict]
        Cycle records sorted by firstRun ascending.
    """
    global _CYCLE_CACHE, _CACHE_VERSION

    if rebuild:
        return build_cycle_json(ods_path=ods_path, json_path=json_path)

    if _CYCLE_CACHE is not None:
        return _CYCLE_CACHE

    json_path = json_path or DEFAULT_JSON

    if not os.path.isfile(json_path):
        raise FileNotFoundError(
            f"Cycle JSON not found at {json_path}. "
            "Run build_cycle_json() first to generate it from the .ods spreadsheet."
        )

    with open(json_path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)

    _CYCLE_CACHE = payload.get("cycles", [])
    _CACHE_VERSION = int(payload.get("version", 1))
    return _CYCLE_CACHE


def get_cycle_for_run(
    run_number: int,
    rebuild: bool = False,
    json_path: Optional[str] = None,
) -> Optional[str]:
    """Return the cycleID that contains *run_number*, or None if not found.

    Lookup strategy: the cycle whose ``firstRun <= run_number`` and whose
    successor's ``firstRun > run_number`` (or is the last cycle) is the match.

    .. warning::
       This lookup is **open-ended**: it ignores ``stopDate``, so a run acquired
       after the last registered cycle ended still resolves to that cycle rather
       than reporting that its cycle is undecided.  Do not use it for gating --
       use :func:`resolve_cycle_for_run`, which distinguishes the two and fails
       closed.  This function is retained for display and annotation, where an
       approximate answer is harmless.

    Parameters
    ----------
    run_number : int
        The SNAP run number to look up.
    rebuild : bool
        If True, force a rebuild from the .ods before looking up.
    json_path : str, optional
        Path to the JSON file.

    Returns
    -------
    str or None
        The cycleID, or None if the run predates all recorded cycles.
    """
    run_number = int(run_number)
    cycles = load_cycle_data(json_path=json_path, rebuild=rebuild)

    if not cycles:
        return None

    # cycles are sorted by startDate ascending (guaranteed by validation).
    # Skip cycles with null firstRun (future cycles not yet started).
    match: Optional[str] = None
    for cycle in cycles:
        fr = cycle["firstRun"]
        if fr is None:
            continue  # future cycle – no run-number assignment yet
        if run_number >= fr:
            match = cycle["cycleID"]
        else:
            break  # all subsequent cycles have higher firstRun

    return match


# ---------------------------------------------------------------------------
# Cycle resolution (run-number bounded)
# ---------------------------------------------------------------------------
#
# ``get_cycle_for_run`` above is firstRun-based and open-ended: it has no
# concept of "after the end of a cycle", so a run taken once a cycle had
# finished still resolves to that cycle.  That is a silent wrong answer rather
# than a missing one -- a gate built on it can never notice that the cycle is
# undecided, so it would never refuse.
#
# ``resolve_cycle_for_run`` below distinguishes three states and fails closed.
# It works purely in run-number space, because that is how both SNAPWrap and
# SNAPRed quantify cycles; the dates in the table are descriptive, not the key.
# The upper bound comes from the optional ``lastRun`` column, which -- like
# ``firstRun`` -- is a human QA judgement and cannot be derived from the data:
# the beam goes off mid-cycle and planned cycle dates get extended to
# compensate, so no rule over beam state reproduces it.

IN_CYCLE = "in_cycle"
UNDECIDED = "undecided"
BEFORE_RECORD = "before_record"


class CycleResolution(NamedTuple):
    """Outcome of resolving a run number to an operating cycle.

    Attributes
    ----------
    cycleID : str or None
        The cycle, when one could be established.  ``None`` unless
        ``status == IN_CYCLE``.
    status : str
        One of :data:`IN_CYCLE`, :data:`UNDECIDED`, :data:`BEFORE_RECORD`.
    detail : str
        Human-readable explanation, suitable for a refusal message.
    """

    cycleID: Optional[str]
    status: str
    detail: str

    @property
    def isDecided(self) -> bool:
        """True only when the run sits inside a known, registered cycle."""
        return self.status == IN_CYCLE


def resolve_cycle_for_run(
    run_number: int,
    rebuild: bool = False,
    json_path: Optional[str] = None,
) -> CycleResolution:
    """Resolve *run_number* to a cycle, distinguishing "undecided" from "known".

    Unlike :func:`get_cycle_for_run` this honours ``lastRun`` and so can tell
    "inside cycle X" apart from "in the gap after cycle X ended".  It fails
    closed: a run it cannot place is :data:`UNDECIDED`, never attributed
    optimistically to the preceding cycle.

    A cycle without a ``lastRun`` keeps the historical behaviour -- bounded from
    above by the next cycle's ``firstRun``, or unbounded if it is the last cycle
    registered.  That is deliberately permissive: absent an explicit end we
    cannot prove a run is out of cycle, and refusing everything after the last
    known ``firstRun`` would block routine work.  Setting ``lastRun`` is what
    closes each cycle.

    Parameters
    ----------
    run_number : int
        The SNAP run number.
    rebuild : bool
        Force a rebuild from the .ods before looking up.
    json_path : str, optional
        Path to the JSON file.

    Returns
    -------
    CycleResolution
    """
    run_number = int(run_number)
    cycles = load_cycle_data(json_path=json_path, rebuild=rebuild)

    # Future cycles carry firstRun: null and cannot place a run.
    dated = [c for c in cycles if c.get("firstRun") is not None]

    if not dated:
        return CycleResolution(
            None, UNDECIDED, "no cycles with a firstRun are registered"
        )

    dated = sorted(dated, key=lambda c: c["firstRun"])

    if run_number < dated[0]["firstRun"]:
        return CycleResolution(
            None,
            BEFORE_RECORD,
            f"run {run_number} predates the first registered cycle "
            f"({dated[0]['cycleID']}, firstRun {dated[0]['firstRun']})",
        )

    # Last cycle whose firstRun does not exceed the run.
    idx = 0
    for i, cycle in enumerate(dated):
        if run_number >= cycle["firstRun"]:
            idx = i
        else:
            break

    candidate = dated[idx]
    lastRun = candidate.get("lastRun")

    if lastRun is not None and run_number > lastRun:
        nxt = dated[idx + 1] if idx + 1 < len(dated) else None
        if nxt is not None:
            detail = (
                f"run {run_number} falls between the end of "
                f"{candidate['cycleID']} (lastRun {lastRun}) and the start of "
                f"{nxt['cycleID']} (firstRun {nxt['firstRun']}), so it belongs "
                "to no registered cycle"
            )
        else:
            detail = (
                f"run {run_number} is after the end of {candidate['cycleID']} "
                f"(lastRun {lastRun}) and the next cycle's firstRun has not "
                "been decided yet"
            )
        return CycleResolution(None, UNDECIDED, detail)

    if lastRun is not None:
        detail = (
            f"run {run_number} lies within {candidate['cycleID']} "
            f"(runs {candidate['firstRun']}-{lastRun})"
        )
    elif idx + 1 < len(dated):
        detail = (
            f"run {run_number} lies between firstRun {candidate['firstRun']} "
            f"and {dated[idx + 1]['cycleID']}'s firstRun "
            f"{dated[idx + 1]['firstRun']}"
        )
    else:
        detail = (
            f"run {run_number} is at or after firstRun {candidate['firstRun']} "
            f"and {candidate['cycleID']} has no lastRun set, so it is presumed "
            "to be the current cycle"
        )

    return CycleResolution(candidate["cycleID"], IN_CYCLE, detail)


def cache_version() -> Optional[int]:
    """Return the version number of the currently cached cycle data, or None."""
    return _CACHE_VERSION


def clear_cache() -> None:
    """Clear the in-memory cycle cache so the next lookup re-reads from disk."""
    global _CYCLE_CACHE, _CACHE_VERSION
    _CYCLE_CACHE = None
    _CACHE_VERSION = None
