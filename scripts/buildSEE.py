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
# Build Pressure controller and Temperature controller:
###################################################################

teledyne = pressureController(manufacturer="teledyne", 
                              model="", serialNumber="",
                              pvLogs=["BL3:SE:Teledyne1:PressSet",
                                      "BL3:SE:Teledyne1:Pressure"])

pace = pressureController(manufacturer="pace", 
                         model="", serialNumber="",
                         pvLogs=["BL3:SE:PACE1:PressSet",
                                 "BL3:SE:PACE1:Pressure"])

lakeshore = temperatureController(manufacturer="Lakeshore", #TODO: need a nickname property
                                 model="", serialNumber="",
                                 pvLogs=["BL3:SE:Lakeshore:SETP4",
                                          "BL3:SE:Lakeshore:TempSet"])

#save these as separate jsons
for controller in [teledyne, pace, lakeshore]:
    print("Created component:")
    print(controller.stringDescriptor)

    # serialize and save
    payload = controller.to_dict()
    #save json
    json = f"{jsonDir}/components/{controller.manufacturer}.json"
    utils.SEEMetaSaver(payload,json)

###################################################################
# DAC template:
###################################################################

#specify anvil
anvil = DACAnvil(culetDiameter=
                numVal(1.5, "mm"), 
                )
anvil.orientation = [0.0,0.0,1.0] #parallel to beam


# use anvil to build gasket
gasket = makeDACGasket(anvil, 
                       indentThickness=numVal(0.09, "mm"), 
                       holeDiameter=numVal(0.65, "mm"), 
                       material="W")
gasket.orientation = [0.0,0.0,1.0] #parallel to beam

# add current design of collimator
coll = Collimator(material="hBN",
                  apertureShape="circle",
                  apertureDimensions=[numVal(0.5, "mm"),numVal(0.5,'mm')])

coll.orientation = [0.0,0.0,1.0] #parallel to beam
coll.origin = [0.0,0.0,-5.0] #5mm upstream of the sample position

# assemble
cryoDAC = assembly.DAC(components=[anvil, gasket, coll, pace,lakeshore], 
               comment="DAC template", 
               model="markVI", 
               serialNumber="001",
               orientation=[0.0, 0.0, 1.0])
#customise attributes
cryoDAC.primaryCategory = "DAC"
cryoDAC.nickname = "cryoDAC"

DAC = assembly.DAC(components=[anvil, gasket, coll, teledyne], 
               comment="DAC template", 
               model="markVI", 
               serialNumber="001",
               orientation=[0.0, 0.0, 1.0])
#customise attributes
DAC.primaryCategory = "DAC"
DAC.nickname = "DAC"

# serialize and save 
payload = cryoDAC.to_dict()
json = f"{jsonDir}/DAC_cryo.json"
utils.SEEMetaSaver(payload,json)

payload = DAC.to_dict()
json = f"{jsonDir}/DAC.json"
utils.SEEMetaSaver(payload,json)

###################################################################
# PE templates:
###################################################################

#specify single toroid anvil
singleToroid_CBN = toroidAnvil(material='cBN',
                    numberOfToroids=1
                )
# use anvil to build gasket
singleToroid_gasket = makeToroidGasket(singleToroid_CBN)

# TODO: create collimator and add to PE assemblies

# assemble
PE_ST_VX5 = assembly.PE(
            components=[singleToroid_CBN, singleToroid_gasket, teledyne], 
            comment="PE single toroid template", 
            model="VX5", 
            serialNumber="")

PE_ST_VX3 = assembly.PE(
            components=[singleToroid_CBN, singleToroid_gasket, teledyne], 
            comment="PE single toroid template", 
            model="VX3", 
            serialNumber="")


#specify double toroid anvil
doubleToroid_sd = toroidAnvil(material='sinteredDiamond',
                    numberOfToroids=2
                )
# use anvil to build gasket
doubleToroid_gasket = makeToroidGasket(doubleToroid_sd)

# assemble
PE_DT_VX5 = assembly.PE(components=[doubleToroid_sd, doubleToroid_gasket, teledyne], 
               comment="PE double toroid template", 
               model="VX5", 
               serialNumber="")

PE_DT_VX3 = assembly.PE(components=[doubleToroid_sd, doubleToroid_gasket, teledyne], 
               comment="PE double toroid template", 
               model="VX3", 
               serialNumber="")

# serialize and save
for cell in [PE_ST_VX5, PE_ST_VX3, PE_DT_VX5, PE_DT_VX3]:
    print("Created assembly:")
    print(cell.stringDescriptor)

    cell.origin = [0.0, 0.0, 0.0] #set origin to sample position
    cell.orientation = [0.0,1.0,0.0] #set orientation to vertically up
    cell.nickname = "PE"

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
# cylinder templates:
###################################################################

#BeCu H2 gas cell
cyl = cylinder(material="BeCu",innerDiameter=numVal(7.0, "mm"), 
                  outerDiameter=numVal(23.0, "mm"), 
                  height=numVal(30, "mm")
                  )

cell1 = assembly.CylinderCell(components=[cyl],
                             comment="CuBe H2 gas cell",
                             )
cell1.primaryCategory = "gasCell"
cell1.nickname = "BeCu gas"
#Auto frettaged Al cell
cyl = cylinder(material="Al",innerDiameter=numVal(6.0, "mm"), 
                  outerDiameter=numVal(18.0, "mm"), 
                  height=numVal(30, "mm"))

cell2 = assembly.CylinderCell(components=[cyl],
                             comment="Small auto frettaged Al cell",
                             )
cell2.primaryCategory = "gasCell"
cell2.nickname = "autoFrettaged gas"
# 2.5mm BeCu clamp
cyl = cylinder(material="BeCu",innerDiameter=numVal(2.5, "mm"), 
                  outerDiameter=numVal(8.8, "mm"), 
                  height=numVal(30, "mm"))

cell3 = assembly.CylinderCell(components=[cyl],
                             comment="2.5mm BeCu clamp",
                             )
cell3.primaryCategory = "clamp"
cell3.nickname = "BeCu clamp"

#pre-stressed clamp
cly1 = cylinder(material="BeCu",innerDiameter=numVal(4.7, "mm"), 
                  outerDiameter=numVal(15.3, "mm"), 
                  height=numVal(30, "mm"))
cly2 = cylinder(material="Al",innerDiameter=numVal(15.3, "mm"), 
                  outerDiameter=numVal(32.1, "mm"), 
                  height=numVal(30, "mm"))                               

cell4 = assembly.CylinderCell(components=[cly1,cly2],
                             comment="Pre-stressed clamp",
                             )
cell4.primaryCategory = "clamp"
cell4.nickname = "pre-stressed clamp"

fnames = ["gasCell_CuBe_H2.json","gasCell_Small_autoFrettaged_Al.json",
          "clamp_CuBe_2.5mm.json","clamp_pre-stressed.json"] 

for i,cell in enumerate([cell1,cell2,cell3,cell4]):

    cell.origin = [0.0, 0.0, 0.0] #set origin to sample position
    cell.orientation = [0.0,1.0,0.0] #set orientation to vertically up
    payload = cell.to_dict()
    #save json
    json = f"{jsonDir}/{fnames[i]}"

    utils.SEEMetaSaver(payload,json)    
###################################################################
# van can:
###################################################################

cyl = cylinder(material="V",innerDiameter=numVal(2.9, "mm"), 
                  outerDiameter=numVal(3.0, "mm"), 
                  height=numVal(30, "mm"))

vanCan = assembly.CylinderCell(components=[cyl],
                               comment="Vanadium can template",
                               )
vanCan.primaryCategory = "vanadiumCan"
vanCan.nickname = "van can"
vanCan.origin = [0.0, 0.0, 0.0]
vanCan.orientation = [0.0,1.0,0.0]

# serialize and round-trip
payload = vanCan.to_dict()
#save json
json = f"{jsonDir}/vanCan_3mm.json"
utils.SEEMetaSaver(payload,json)


###################################################################
# empty assembly:
###################################################################

empty = assembly.Empty()
empty.comment = "Empty assembly"
empty.nickname = "empty"

# serialize and round-trip
payload = empty.to_dict()
#save json
json = f"{jsonDir}/empty.json"
utils.SEEMetaSaver(payload,json)