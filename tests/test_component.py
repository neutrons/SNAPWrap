import pytest
from snapwrap.SEEMeta.component import numVal, anvil, gasket, cylinder

class DummySEE:
    @staticmethod
    def materialInDatabase(name):
        return name in ["diamond", "steel", "TiZr"]

    @staticmethod
    def get_material_details(name):
        # Return all required keys for TiZr
        if name == "TiZr":
            return {
                "isSingleCrystal": False,
                "chemical_formula": "Zr0.32-Ti0.68",
                "mass_density_g_cm3": 5.23,
                "grade": "custom",
                "composition_by_weight_percent": None,
                "data_source": "ISIS internal report"
            }
        elif name == "diamond":
            return {"isSingleCrystal": True, "chemical_formula": "C"}
        elif name == "steel":
            return {"isSingleCrystal": False, "chemical_formula": "Fe"}
        else:
            return {}

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

def test_anvil_DAC():
    a = anvil(type="DAC", material="diamond", culetDiameter=0.5)
    assert a.type == "DAC"
    assert a.culetDiameter.value == 0.5

def test_anvil_toroid():
    a = anvil(type="toroidal", material="steel", numberOfToroids=2)
    assert a.type == "toroidal"
    assert a.innerDiameter.value == 3

def test_gasket_valid():
    g = gasket(model="flat", material="TiZr", initialIndentThickness=1.0, initialHoleDiameter=2.0)
    assert g.model == "flat"
    assert g.material == "TiZr"

def test_gasket_invalid_model():
    with pytest.raises(ValueError):
        gasket(model="foo", material="TiZr")

def test_cylinder_valid():
    c = cylinder(material="TiZr", ID=2.0, OD=3.0, height=5.0)
    assert c.material == "TiZr"
    assert c.ID.value == 2.0
    assert c.OD.value == 3.0
    assert c.height.value == 5.0

def test_cylinder_invalid_material():
    with pytest.raises(ValueError):
        cylinder(material="unknown", ID=2.0, OD=3.0, height=5.0)