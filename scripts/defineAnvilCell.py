import sys,os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
from snapwrap.SEEMeta.component import numVal, DACAnvil, toroidAnvil, cylinder,makeDACGasket
from snapwrap.SEEMeta import utils


PE = toroidAnvil(material="ZTA", numberOfToroids=1)
cyl = cylinder(material="TiZr", outerDiameter=numVal(10, "mm"), 
               innerDiameter=numVal(5, "mm"), 
               height=numVal(20, "mm"))

#confirm round trip serialization
# Test DAC anvil. 
print("Diamond Anvil:")

print("Round trip serialization:")      

print("\ninitial anvil:")
dac = DACAnvil(culetDiameter=numVal(1.5, "mm"))
for key, val in dac.to_dict().items():
    print(f"{key}: {val}")

print("\nunserialized anvil:")

rev_dac = DACAnvil.from_dict(dac.to_dict())
for key, val in rev_dac.to_dict().items():
    print(f"{key}: {val}")

#Now instatiate a gasket from the DAC anvil
print("\nGasket from DAC anvil:")
gasket = makeDACGasket(rev_dac, indentThickness=numVal(0.1, "mm"),
                                    holeDiameter=numVal(0.3, "mm"))

print("Round trip serialization:")

print("\ninitial gasket:")
for key, val in gasket.to_dict().items():
    print(f"{key}: {val}")

print("\nunserialized gasket:")

rev_gasket = gasket.from_dict(gasket.to_dict())
for key, val in rev_gasket.to_dict().items():
    print(f"{key}: {val}")