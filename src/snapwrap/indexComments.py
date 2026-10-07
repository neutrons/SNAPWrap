"""Vocabulary for calibration-index ``comments`` and ``appliesTo`` strings.

Deliberately dependency-free — only the standard library — so that both the
core reduction path (:mod:`snapwrap.utils`) and the mock-free GUI constants
module (:mod:`snapwrap.calibrationManager.constants`) can import it without
dragging in mantid, snapred or Qt.

**Invalidation.** A calibration version is retired by making its index entry
unselectable rather than by deleting it. Deletion forced the remaining
versions to be re-numbered, which silently broke provenance: a run reduced
against "version N" could no longer be tied to the calibration that actually
produced it, because some other calibration had since become version N.

Invalidation instead sets ``appliesTo`` to :data:`NEVER_APPLIES` — a condition
no run can satisfy, since run numbers are positive — and prefixes the comment
with :data:`INVALIDATED_PREFIX`. The version keeps its number, its folder and
its record, so history stays readable, while
``Indexer._isApplicableEntry`` filters it out of every lookup.

Because the prefix sits at the *front* of the comment, anything that matches
an anchored pattern against a comment must strip it first — hence
:func:`strip_invalidated`.
"""

import re

__all__ = [
    "INVALIDATED_PREFIX",
    "NEVER_APPLIES",
    "is_invalidated",
    "strip_invalidated",
    "mark_invalidated",
]


#: Marker prefixed to the ``comments`` field of an invalidated index entry.
INVALIDATED_PREFIX = "(INVALIDATED)"

#: ``appliesTo`` value that no run number can satisfy. Run numbers are
#: positive, and ``Indexer._isApplicableEntry`` compares numerically, so an
#: entry carrying this is never selected. It still passes snapred's
#: ``IndexEntry.appliesToFormatChecker``, which requires only
#: ``{symbol}{integer}``.
NEVER_APPLIES = "<0"


_INVALIDATED_RE = re.compile(r"^\s*\(INVALIDATED\)\s*")


def is_invalidated(comment) -> bool:
    """Return True if *comment* carries the invalidation marker."""

    if not isinstance(comment, str):
        return False
    return bool(_INVALIDATED_RE.match(comment))


def strip_invalidated(comment):
    """Return *comment* with a leading invalidation marker removed.

    Non-strings and unmarked comments are returned unchanged, so this is safe
    to call unconditionally before matching any anchored pattern.
    """

    if not isinstance(comment, str):
        return comment
    return _INVALIDATED_RE.sub("", comment, count=1)


def mark_invalidated(comment) -> str:
    """Return *comment* with the invalidation marker prefixed.

    Idempotent — a comment that is already marked is returned unchanged, so
    invalidating twice does not stack prefixes.
    """

    if not isinstance(comment, str):
        comment = "" if comment is None else str(comment)
    if is_invalidated(comment):
        return comment
    comment = comment.strip()
    return f"{INVALIDATED_PREFIX} {comment}" if comment else INVALIDATED_PREFIX
