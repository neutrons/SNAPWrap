"""Unit tests for the campaignManager.dialogs helpers (Qt-free)."""

from snapwrap.campaignManager.dialogs import _suggest_new_id


def test_suggest_new_id_rewrites_trailing_run():
    # Standard case: id ends with the source run, swap in the new one.
    assert (
        _suggest_new_id("dspacing-mask-diamond-65891", 65891, 65892)
        == "dspacing-mask-diamond-65892"
    )


def test_suggest_new_id_handles_string_runs():
    # Run numbers may arrive as strings from the QLineEdit.
    assert (
        _suggest_new_id("binmask-wavelength-10001", "10001", "10002")
        == "binmask-wavelength-10002"
    )


def test_suggest_new_id_appends_when_no_trailing_run():
    # Id has no trailing number at all — append the new run.
    assert _suggest_new_id("pixmask-letterbox", "", 65892) == "pixmask-letterbox-65892"


def test_suggest_new_id_falls_back_to_copy_on_mismatch():
    # Id has *some* trailing number but it doesn't match the source run —
    # don't silently rewrite something the operator didn't expect.
    assert (
        _suggest_new_id("dspacing-mask-diamond-65891", 65999, 65892)
        == "dspacing-mask-diamond-65891-copy"
    )


def test_suggest_new_id_falls_back_to_copy_on_nonnumeric_run():
    # Garbage in run field — keep a safe -copy suggestion.
    assert (
        _suggest_new_id("dspacing-mask-diamond-65891", 65891, "not-a-run")
        == "dspacing-mask-diamond-65891-copy"
    )


def test_suggest_new_id_empty_source():
    assert _suggest_new_id("", 65891, 65892) == ""
