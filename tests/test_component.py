import pytest
from snapwrap.SEEMeta.component import numVal, DACAnvil, toroidAnvil

import pytest
from snapwrap.SEEMeta import component as component_mod

# Minimal test double for SEE
class DummySEE:
    @staticmethod
    def materialInDatabase(name):
        return name in ["testCrystal", "singleCrystalDiamond","ZTA"]

    @staticmethod
    def get_material_details(name):
        if name == "testCrystal":
            return {
                "chemical_formula": "(Li7)2-C-H4-N-Cl6",
                "mass_density_g_cm3": 5.0,
                "isSingleCrystal": False,
            }
        if name == "singleCrystalDiamond":
            return {
                "chemical_formula": "C",
                "mass_density_g_cm3": 3.51,
                "isSingleCrystal": True,
            }
        if name == "ZTA":
            return {
                "chemical_formula": "Al0.33-O0.61-Zr0.05",
                "mass_density_g_cm3": 4.37,
                "isSingleCrystal": False,
            }
        return {}

# Patch SEE on the module before importing classes (ensures __post_init__ sees DummySEE)
component_mod.SEE = DummySEE

from snapwrap.SEEMeta.component import numVal, DACAnvil

def test_setMantidMaterial_with_valid_formula():
    a = DACAnvil(culetDiameter=numVal(0.5, "mm"), material="testCrystal")
    mantid = a.setMantidMaterial("testCrystal")
    assert mantid["ChemicalFormula"] == "(Li7)2-C-H4-N-Cl6"
    assert mantid["MassDensity"] == 5.0

# Patch SEE for testing
import snapwrap.SEEMeta.component as component
component.SEE = DummySEE

def test_numVal_valid_units():
    v = numVal(1.23, "mm")
    assert v.value == 1.23
    assert v.units == "mm"

def test_numVal_invalid_units():
    with pytest.raises(ValueError):
        numVal(1.23, "foo")

def test_setMantidMaterial_with_valid_formula():
    a = DACAnvil(culetDiameter=numVal(0.5, "mm"), material="testCrystal")
    mantid = a.setMantidMaterial("testCrystal")
    assert mantid["ChemicalFormula"] == "(Li7)2-C-H4-N-Cl6"
    assert mantid["MassDensity"] == 5.0

def test_anvil_toroid():
    a = toroidAnvil(material="ZTA", numberOfToroids=1)
    


# def test_gasket_valid():
#     g = gasket(model="flat", material="TiZr", initialIndentThickness=1.0, initialHoleDiameter=2.0)
#     assert g.model == "flat"
#     assert g.material == "TiZr"

# def test_gasket_invalid_model():
#     with pytest.raises(ValueError):
#         gasket(model="foo", material="TiZr")

# def test_cylinder_valid():
#     c = cylinder(material="TiZr", ID=2.0, OD=3.0, height=5.0)
#     assert c.material == "TiZr"
#     assert c.ID.value == 2.0
#     assert c.OD.value == 3.0
#     assert c.height.value == 5.0

# def test_cylinder_invalid_material():
#     with pytest.raises(ValueError):
#         cylinder(material="unknown", ID=2.0, OD=3.0, height=5.0)