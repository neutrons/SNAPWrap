#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

# import constructors
from snapwrap.SEEMeta.component import *
import snapwrap.SEEMeta.assembly as assembly
import snapwrap.SEEMeta.utils as utils

from snapwrap.wrapConfig import WrapConfig

jsonDir = WrapConfig.get("SEE/json/home")


###################################################################
# Pressure controller and Temperature controller:
###################################################################

teledyne = pressureController(manufacturer="Teledyne", 
                              model="", serialNumber="",
                              pvLogs=["BL3:SE:Teledyne1:PressSet",
                                      "BL3:SE:Teledyne1:Pressure"])

pace = pressureController(manufacturer="PACE", 
                         model="", serialNumber="",
                         pvLogs=["BL3:SE:PACE1:PressSet",
                                 "BL3:SE:PACE1:Pressure"])

cryo_12 = temperatureController(manufacturer="", 
                                 model="", serialNumber="",
                                 pvLogs=["BL3:SE:Lakeshore:SETP4",
                                          "BL3:SE:Teledyne1:TempSet"])

###################################################################
# DAC template:
###################################################################

#specify anvil
anvil = DACAnvil(culetDiameter=
                numVal(1.5, "mm"), 
                )


# use anvil to build gasket
gasket = makeDACGasket(anvil, 
                       indentThickness=numVal(0.09, "mm"), 
                       holeDiameter=numVal(0.65, "mm"), 
                       material="W")

# assemble
DAC = assembly.DAC(components=[anvil, gasket, teledyne], 
               comment="DAC template", 
               model="markVI", 
               serialNumber="",
               orientation=[0.0, 0.0, 1.0])

print("Created assembly:")
print(DAC.stringDescriptor)

# serialize and save 
payload = DAC.to_dict()
#save json
json = f"{jsonDir}/DAC.json"
utils.SEEMetaSaver(payload,json)

###################################################################
# PE templates:
###################################################################

#specify single toroid anvil
anvil = toroidAnvil(material='cBN',
                    numberOfToroids=1
                )

# use anvil to build gasket
gasket = makeToroidGasket(anvil)

# assemble
PE_ST_VX5 = assembly.PE(components=[anvil, gasket, teledyne], 
               comment="PE single toroid template", 
               model="VX5", 
               serialNumber="")

PE_ST_VX3 = assembly.PE(components=[anvil, gasket, teledyne], 
               comment="PE single toroid template", 
               model="VX3", 
               serialNumber="")


#specify double toroidanvil
anvil = toroidAnvil(material='sinteredDiamond',
                    numberOfToroids=2
                )
# use anvil to build gasket
gasket = makeToroidGasket(anvil)

# assemble
PE_DT_VX5 = assembly.PE(components=[anvil, gasket, teledyne], 
               comment="PE double toroid template", 
               model="VX5", 
               serialNumber="")

PE_DT_VX3 = assembly.PE(components=[anvil, gasket, teledyne], 
               comment="PE double toroid template", 
               model="VX3", 
               serialNumber="")

# serialize and save
for cell in [PE_ST_VX5, PE_ST_VX3, PE_DT_VX5, PE_DT_VX3]:
    print("Created assembly:")
    print(cell.stringDescriptor)

    # serialize and save
    payload = cell.to_dict()
    #save json
    model = cell.model.replace(" ","_")
    if cell.comment.startswith("PE single"):
        json = f"{jsonDir}/PE_singleToroid_{model}.json"
    else:
        json = f"{jsonDir}/PE_doubleToroid_{model}.json"
    utils.SEEMetaSaver(payload,json)

###################################################################
# To do cylinder templates:
###################################################################

###################################################################
# van can:
###################################################################

cyl = cylinder(material="V",innerDiameter=numVal(2.9, "mm"), 
                  outerDiameter=numVal(3.0, "mm"), 
                  height=numVal(30, "mm"))

vanCan = assembly.CylinderCell(components=[cyl],
                               comment="Vanadium can template",
                               )

# serialize and round-trip
payload = vanCan.to_dict()
#save json
json = f"{jsonDir}/vanCan_3mm.json"
utils.SEEMetaSaver(payload,json)


###################################################################
# empty assembly:
###################################################################

empty = assembly.empty()
empty.comment = "Empty assembly"

# serialize and round-trip
payload = empty.to_dict()
#save json
json = f"{jsonDir}/empty.json"
utils.SEEMetaSaver(payload,json)