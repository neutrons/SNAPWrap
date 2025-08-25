#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

# import constructors
from snapwrap.SEEMeta.component import *
import snapwrap.SEEMeta.assembly as assembly


# DAC template:

#specify anvil
anvil = DACAnvil(culetDiameter=
                numVal(1.5, "mm"), 
                )


# use anvil to build gasket
gasket = makeDACGasket(anvil, 
                       indentThickness=numVal(90, "um"), 
                       holeDiameter=numVal(0.65, "um"), 
                       material="W")

# assemble
DAC = assembly.DAC(components=[anvil, gasket], 
               comment="DAC template", 
               model="markVI", 
               serialNumber="SN123")

print("Created assembly:")
print(DAC.stringDescriptor)

# serialize and round-trip
payload = DAC.to_dict()
print("Serialized assembly:")

print(json.dumps(payload, indent=2))

# recovered = DAC.from_dict(payload)
# print("\nRecovered assembly components:")
# for c in recovered.components:
#     print(type(c).__name__, getattr(c, "kind", None), getattr(c, "stringDescriptor", None))