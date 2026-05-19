"""Tests for reduceSEE — smart wrapper around wrap.reduce."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from snapwrap.reduction_artefacts import reduceSEE, setup_campaign_from_spec
from snapwrap.reduction_artefacts.reduce import (
    _find_campaign_for_run,
    build_reduce_kwargs,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def shared_root(tmp_path: Path) -> Path:
    sr = tmp_path / "shared"
    sr.mkdir()
    return sr


def _write_seemeta(see_dir: Path, run_number: int) -> Path:
    p = see_dir / f"SEE{run_number:06d}.json"
    p.write_text(json.dumps({
        "run_number": run_number,
        "assembly_type": "DAC",
        "components": [],
    }))
    return p


@pytest.fixture()
def see_dir(shared_root: Path) -> Path:
    see = shared_root / "SEE"
    see.mkdir()
    return see


def _bootstrap_campaign(
    shared_root: Path,
    *,
    slug: str,
    run_number: int,
    see_dir: Path,
) -> str:
    """Helper: stand up a real campaign with one ingested SEEMeta record."""
    _write_seemeta(see_dir, run_number)
    spec = {
        "ipts": 1,
        "campaign_slug": slug,
        "assembly_type": "DAC",
        "runs": [run_number],
        "assets": [],
        "seemeta_dir": "SEE",
        "bin_masks": [],
    }
    setup_campaign_from_spec(spec, shared_root=shared_root)
    return slug


@pytest.fixture()
def populated_campaign(shared_root: Path, see_dir: Path) -> str:
    return _bootstrap_campaign(
        shared_root, slug="test_camp_a", run_number=1001, see_dir=see_dir,
    )


# ── _find_campaign_for_run ────────────────────────────────────────────────────

class TestFindCampaignForRun:
    def test_finds_unique_match_via_seemeta_asset(
        self, shared_root, populated_campaign
    ):
        slug = _find_campaign_for_run(
            ipts=1, run_number=1001, shared_root=shared_root,
        )
        assert slug == populated_campaign

    def test_raises_when_run_unknown(self, shared_root, populated_campaign):
        with pytest.raises(KeyError, match="not declared in any campaign"):
            _find_campaign_for_run(
                ipts=1, run_number=9999, shared_root=shared_root,
            )

    def test_raises_when_state_missing(self, shared_root):
        with pytest.raises(KeyError, match="No reduction-artefacts state"):
            _find_campaign_for_run(
                ipts=1, run_number=1001, shared_root=shared_root,
            )

    def test_raises_on_multiple_matches(self, shared_root, see_dir):
        for slug in ("test_camp_a", "test_camp_b"):
            _bootstrap_campaign(
                shared_root, slug=slug, run_number=2002, see_dir=see_dir,
            )
        with pytest.raises(KeyError, match="multiple campaigns"):
            _find_campaign_for_run(
                ipts=1, run_number=2002, shared_root=shared_root,
            )


# ── reduceSEE: kwargs translation + delegation ────────────────────────────────

class _FakeWrap:
    """Stand-in for the snapwrap.utils module — records reduce() calls."""

    def __init__(self):
        self.calls: list[tuple[int, dict]] = []

    def reduce(self, run_number, **kwargs):
        self.calls.append((run_number, kwargs))
        return f"reduced-{run_number}"


class TestReduceSEEDelegation:
    def test_calls_wrap_reduce_with_caller_kwargs(
        self, shared_root, populated_campaign
    ):
        wrap = _FakeWrap()
        result = reduceSEE(
            1001,
            wrap=wrap,
            ipts=1,
            shared_root=shared_root,
            campaign=populated_campaign,
            keepUnfocussed=True,
            verbose=True,
        )
        assert result == "reduced-1001"
        assert len(wrap.calls) == 1
        run, kwargs = wrap.calls[0]
        assert run == 1001
        assert kwargs["keepUnfocussed"] is True
        assert kwargs["verbose"] is True

    def test_auto_discovers_campaign_when_omitted(
        self, shared_root, populated_campaign
    ):
        wrap = _FakeWrap()
        reduceSEE(
            1001,
            wrap=wrap,
            ipts=1,
            shared_root=shared_root,
        )
        assert len(wrap.calls) == 1
        assert wrap.calls[0][0] == 1001

    def test_passes_through_unknown_kwarg_via_extra(
        self, shared_root, populated_campaign
    ):
        wrap = _FakeWrap()
        reduceSEE(
            1001,
            wrap=wrap,
            ipts=1,
            shared_root=shared_root,
            campaign=populated_campaign,
            lambdaCrop=False,
        )
        _, kwargs = wrap.calls[0]
        assert kwargs.get("lambdaCrop") is False


# ── build_reduce_kwargs sanity check ──────────────────────────────────────────

class TestBuildReduceKwargs:
    def test_no_artefacts_yields_only_passthroughs(self):
        manifest = {"run_number": 1, "selected_artefacts": []}
        k = build_reduce_kwargs(manifest, verbose=True, keepUnfocussed=True)
        assert k == {
            "verbose": True,
            "keepUnfocussed": True,
            "continueNoDifcal": False,
            "continueNoVan": False,
        }
