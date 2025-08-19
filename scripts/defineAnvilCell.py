import sys,os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
from snapwrap.SEEMeta.component import numVal, DACAnvil, toroidAnvil
from snapwrap.SEEMeta import utils

dac = DACAnvil(culetDiameter=numVal(0.5, "mm"))
PE = toroidAnvil(material="ZTA", numberOfToroids=1)

print("DAC Anvil:")
print(dac.to_dict())

print("Toroidal Anvil:")
print(PE.to_dict())

