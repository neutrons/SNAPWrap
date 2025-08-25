import json
import pytest

# Import the module first
import importlib
import snapwrap.SEEMeta.component as component
importlib.reload(component)


# DON'T import the classes directly - use the module references to ensure consistent class identity
def _roundtrip_assembly(assembly):
    payload = assembly.to_dict()
    cls = type(assembly)
    recovered = cls.from_dict(payload)
    return recovered

def test_dac_assembly_serialisation_roundtrip():
    # Use component.ClassNames directly to avoid identity issues
    anvil = component.DACAnvil(
        culetDiameter=component.numVal(0.5, "mm"), 
        material="singleCrystalDiamond"
    )
    
    # Debug prints
    print(f"component.DACAnvil: {component.DACAnvil} at {id(component.DACAnvil)}")
    print(f"anvil isinstance check: {isinstance(anvil, component.DACAnvil)}")
    
    gasket = component.makeDACGasket(
        anvil, 
        indentThickness=component.numVal(0.05, "mm"), 
        holeDiameter=component.numVal(0.4, "mm"), 
        material="W"
    )
    tc = component.temperatureController()
    
    # Import assembly here to avoid circular imports
    from snapwrap.SEEMeta.assembly import DAC
    assembly = DAC(components=[anvil, gasket, tc], comment="Test DAC assembly", model="TestModel", serialNumber="SN123")

    recovered = _roundtrip_assembly(assembly)

    assert isinstance(recovered, DAC)
    assert len(recovered.components) == 3

    kinds = [getattr(c, "kind", None) for c in recovered.components]
    assert "anvil.dac" in kinds
    assert "gasket.dac" in kinds
    assert "aux.equipment.temperature" in kinds


def test_pe_assembly_with_toroid_and_pressure_controller_roundtrip():
    tor = component.toroidAnvil(material="W", numberOfToroids=2)
    g = component.makeToroidGasket(tor)
    pc = component.pressureController()

    # Import assembly here to avoid circular imports
    from snapwrap.SEEMeta.assembly import PE
    assembly = PE(components=[tor, g, pc], comment="Test PE assembly", model="PEModel", serialNumber="PE123")

    recovered = _roundtrip_assembly(assembly)

    assert isinstance(recovered, PE)
    assert len(recovered.components) == 3

    kinds = [getattr(c, "kind", None) for c in recovered.components]
    assert "anvil.toroidal" in kinds
    assert "aux.equipment.pressure" in kinds


def test_cylinder_cell_assembly_roundtrip():
    cyl1 = component.cylinder(material="TiZr", outerDiameter=component.numVal(10, "mm"), innerDiameter=component.numVal(5, "mm"), height=component.numVal(20, "mm"))
    cyl2 = component.cylinder(material="W", outerDiameter=component.numVal(5, "mm"), innerDiameter=component.numVal(2, "mm"), height=component.numVal(15, "mm"))
    
    # Import assembly here to avoid circular imports
    from snapwrap.SEEMeta.assembly import CylinderCell
    assembly = CylinderCell(components=[cyl1, cyl2], comment="Test CylinderCell assembly", model="CylinderModel", serialNumber="CY123")

    recovered = _roundtrip_assembly(assembly)

    assert isinstance(recovered, CylinderCell)
    assert len(recovered.components) == 2

    kinds = [getattr(c, "kind", None) for c in recovered.components]
    assert "cylinder" in kinds

