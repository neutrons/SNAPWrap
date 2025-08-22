#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

# patch SEE before importing classes that call it in __post_init__
from snapwrap.SEEMeta import component as component_mod

class DummySEE:
    @staticmethod
    def materialInDatabase(name: str) -> bool:
        return name in {"singleCrystalDiamond", "W", "TiZr", "testCrystal"}

    @staticmethod
    def get_material_details(name: str) -> dict:
        if name == "singleCrystalDiamond":
            return {"chemical_formula": "C", "mass_density_g_cm3": 3.51, "isSingleCrystal": True}
        if name == "W":
            return {"chemical_formula": "W", "mass_density_g_cm3": 19.25, "isSingleCrystal": False}
        if name == "TiZr":
            return {"chemical_formula": "Zr0.32-Ti0.68", "mass_density_g_cm3": 5.23, "isSingleCrystal": False}
        if name == "testCrystal":
            return {"chemical_formula": "(Li7)2-C-H4-N-Cl6", "mass_density_g_cm3": 5.0, "isSingleCrystal": False}
        return {}

component_mod.SEE = DummySEE

# now import constructors
from snapwrap.SEEMeta.component import numVal, DACAnvil, makeDACGasket,temperatureController, toroidAnvil
from snapwrap.SEEMeta.assembly import DAC
import json

# create a test assembly with anvil, gasket, and temperature controller

anvil = DACAnvil(culetDiameter=numVal(0.5, "mm"), material="singleCrystalDiamond")
gasket = makeDACGasket(anvil, indentThickness=numVal(0.05, "mm"), holeDiameter=numVal(0.4, "mm"), material="W")
toroid = toroidAnvil(material="TiZr", numberOfToroids=1)
TC = temperatureController()

# assemble
assembly = DAC(components=[anvil, gasket, TC], 
               comment="Test DAC assembly", model="TestModel", serialNumber="SN123")

print("Created assembly:")
print(assembly.stringDescriptor)

# serialize and round-trip
payload = assembly.to_dict()
print("Serialized assembly:")

print(json.dumps(payload, indent=2))

recovered = DAC.from_dict(payload)
print("\nRecovered assembly components:")
for c in recovered.components:
    print(type(c).__name__, getattr(c, "kind", None), getattr(c, "stringDescriptor", None))