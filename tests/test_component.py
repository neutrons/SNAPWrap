import pytest
import snapwrap.SEEMeta.component as component


def test_setMantidMaterial_with_valid_formula():
    a = component.DACAnvil(culetDiameter=numVal(0.5, "mm"), material="testCrystal")
    mantid = a.setMantidMaterial("testCrystal")
    assert mantid["ChemicalFormula"] == "(Li7)2-C-H4-N-Cl6"
    assert mantid["MassDensity"] == 5.0

def test_numVal_valid_units():
    v = component.numVal(1.23, "mm")
    assert v.value == 1.23
    assert v.units == "mm"

def test_numVal_invalid_units():
    with pytest.raises(ValueError):
        component.numVal(1.23, "foo")

def test_setMantidMaterial_with_valid_formula():
    a = component.DACAnvil(culetDiameter=component.numVal(0.5, "mm"), material="testCrystal")
    mantid = a.setMantidMaterial("testCrystal")
    assert mantid["ChemicalFormula"] == "(Li7)2-C-H4-N-Cl6"
    assert mantid["MassDensity"] == 5.0

def test_anvil_toroid():
    a = component.toroidAnvil(material="ZTA", numberOfToroids=1)
    assert a.material == "ZTA"
    assert a.numberOfToroids == 1


def test_gasket_valid():

    #test toroidal gasket creation
    a = component.toroidAnvil(material="ZTA", numberOfToroids=1)
    g = component.makeToroidGasket(a)
    assert isinstance(g, component.toroidGasket)
    assert g.numberOfToroids == 1
    assert g.material == "TiZr"

    #test DAC gasket creation
    a = component.DACAnvil(culetDiameter=component.numVal(1.5, "mm"))
    g = component.makeDACGasket(a, indentThickness=component.numVal(0.1, "mm"), holeDiameter=component.numVal(0.3, "mm"))
    assert isinstance(g, component.DACGasket)
    assert g.indentThickness.value == 0.1
    assert g.holeDiameter.value == 0.3


def test_gasket_invalid_model():
    with pytest.raises(ValueError):
        component.toroidGasket(material="foo")

def test_cylinder_valid():

    c = component.cylinder(material="TiZr", 
                           innerDiameter=component.numVal(2.0, "mm"), 
                           outerDiameter=component.numVal(3.0, "mm"), 
                           height=component.numVal(5.0, "mm"))
    assert c.material == "TiZr"
    assert c.innerDiameter.value == 2.0
    assert c.outerDiameter.value == 3.0
    assert c.height.value == 5.0

def test_cylinder_invalid_material():
    with pytest.raises(ValueError):
        c = component.cylinder(material="unKnown", 
                           innerDiameter=component.numVal(2.0, "mm"), 
                           outerDiameter=component.numVal(3.0, "mm"), 
                           height=component.numVal(5.0, "mm"))