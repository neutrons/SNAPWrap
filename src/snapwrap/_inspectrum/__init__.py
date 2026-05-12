"""Vendored ``inspectrum`` package — internal namespace inside SNAPWrap.

This package was absorbed from the standalone ``inspectrum`` repository
(https://github.com/mguthriem/inspectrum) and renamed to live inside
``snapwrap``.  Independent development of inspectrum has been frozen; the
canonical home for these modules is now SNAPWrap.

The leading underscore in ``_inspectrum`` flags this as an *internal*
namespace.  External code should not import directly from here; instead,
import the snapwrap-side wrappers (``snapwrap.sampleMeta.eos``,
``snapwrap.sampleMeta.refine``, etc.) once they exist.

Migration plan: see ``docs/inspectrum_absorption_plan.md`` and
``docs/crystal_species_refinement_plan.md``.
"""

__version__ = "0.1.0+vendored"

# Narrow re-export of the pieces the SNAPWrap bridge actually needs.  The full
# vendored API stays available via ``snapwrap._inspectrum.<module>``.
from .engine import inspect  # noqa: F401
from .models import (  # noqa: F401
    CrystalPhase,
    DiffractionSpectrum,
    EquationOfState,
    Instrument,
    PhaseDescription,
    SampleConditions,
)

__all__ = [
    "__version__",
    "inspect",
    "CrystalPhase",
    "DiffractionSpectrum",
    "EquationOfState",
    "Instrument",
    "PhaseDescription",
    "SampleConditions",
]
