# import json
# import os
# from sqlalchemy import create_engine, text
# import re

class opposedAnvilCell:
    #class to define a generic opposed anvil cell

    def __init__(self,type,model,material,anvils,gasketMaterial,gasketType,loadAxis):

        self.type = type
        self.model = model
        self.material = material
        self.anvils = anvils
        self.gasketMaterial = gasketMaterial
        self.gasketType = gasketType
        self.loadAxis = loadAxis

        self.stringDescriptor = self.buildStringDescriptor()
        self.cadFile = f"{self.stringDescriptor}.cad"

        # optional info
        self.temperatureControl = None
        self.manufacturer = ""
        self.comment = ""

        self.validate()

    def validate(self):

        assert self.type in ["paris-edinburgh","DAC"]
        if self.type == ["paris-edinburgh"]:
            assert self.model in ["VX1","VX3","VX5"]
        elif self.type == ["DAC"]:
            assert self.model in ["LEGACY","MARK-VI","MARK-VII"]

        # assert self.material in [""] # not sure what these are
        if self.temperatureControl is not None:
            assert self.temperatureControl in ["CCR-14",
                                               "CCR-21",
                                               "CCR-25",
                                               "CRYO-04",
                                               "PE-CRYO",
                                               "None"] 
        assert len(self.anvils) == 2 #make sure there are two anvils!
        assert self.gasketMaterial in ["TiZr","Re","W", "Zr", 
                                       "SS301", 
                                       "pyrophyllite","Al",
                                       "CuBe"]
        # print(f"gasket type is {self.gasketType}")
        assert self.gasketType in ["encapsulating","non_encapsulating","flat","other"]

    def to_dict(self):
        return {
            "type": self.type,
            "model": self.model,
            "material": self.material,
            "anvils": [anvil.to_dict() for anvil in self.anvils],
            "gasketMaterial": self.gasketMaterial,
            "gasketType": self.gasketType,
            "loadAxis": self.loadAxis,
            "temperatureControl": self.temperatureControl,
            "cadFile": self.cadFile,
            "stringDescriptor": self.stringDescriptor,
            "manufacturer": self.manufacturer,
            "comment": self.comment
        }
    
    @classmethod
    def from_dict(cls, data):
        anvils = [anvil.from_dict(a) for a in data["anvils"]]
        obj = cls(
            type=data["type"],
            model=data["model"],
            material=data["material"],
            anvils=anvils,
            gasketMaterial=data["gasketMaterial"],
            gasketType=data["gasketType"],
            loadAxis=data["loadAxis"]
        )
        obj.temperatureControl = data.get("temperatureControl", "")
        obj.cadFile = data.get("cadFile", "")
        obj.manufacturer = data.get("manufacturer", "")
        obj.comment = data.get("comment", "")
        return obj
    
    def buildStringDescriptor(self):

        # create a short string to represent instance
        anvil = self.anvils[0] # this assumes anvils are the same

        if self.type == "paris-edinburgh":

            stringDescriptor = f"PE_{self.model}_{anvil.material}_{anvil.culetGeometry}"
        elif self.type == "DAC":
            stringDescriptor = f"DAC_{self.model}_{anvil.culetDiameter}mm_culet_{self.gasketMaterial}_gasket"
        else:
            raise ValueError(f"Unsupported type: {self.type}")

        return stringDescriptor.replace(" ","_")

    
    def makeFileName(self):
        # a standardised way to create a file name for the output json. The filename should
        # intelligibly describe the SEE, so should be build from it's core attributes. For
        # the save of brevity, these will be abbreviated.

        if self.type == "paris-edinburgh":
            abbrvType = "PE"
        else:
            abbrvType = self.type

        self.anvils[0].type
        
        self.filename = f"{abbrvType}_{self.anvils[0].culetGeometry}_{self.anvils[0].material}.json".replace(' ','_')
        
        print(self.filename)