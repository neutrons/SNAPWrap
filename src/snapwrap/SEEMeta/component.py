# import json
# import os

import snapwrap.SEEMeta.utils as SEE


class numVal:
    #class to define a number value with units

    def __init__(self, value, units):

        self.value = value        

        allowedUnits = ['ang','nm','um','mm','cm','m','deg','rad']
        if units.lower() in allowedUnits:
            self.units = units.lower()
        else: 
            raise ValueError(f"Invalid units specified: {self.type}. options are {allowedUnits}")

        self.source = None # use to track if measured or calculated

    def __str__(self):
        return f"{self.value} {self.units}"

    def to_dict(self):
        return {
            "value": self.value,
            "units": self.units,
            "source":self.source
        }
    
    @classmethod
    def from_dict(cls, data):
        return cls(data["value"], data["units"])

class anvil:
    #class to define a generic anvil

    def __init__(self,
                 type,
                 material,
                 numberOfToroids=None,
                 culetDiameter=None):

        #validate type
        if self.type not in ["DAC", "toroidal"]:
            raise ValueError(f"Invalid anvil type: {self.type}. Must be 'DAC' or 'toroidal'.")

        #validate material
        materialFound = SEE.materialInDatabase(material)
        if materialFound: 
            self.material = material
        else:
            raise ValueError(f"Material '{material}' not found in database.")

        matprop = SEE.get_material_details(material)
        if matprop["isSingleCrystal"]:
            self.UB = [] #only need this attribute for single crystal anvils
        else:
            self.UB = None

        self.material = material
        self.type = type 
        if self.type == "DAC":
            if culetDiameter is None:
                raise ValueError("culetDiameter must be provided for DAC anvils")
            self.culetDiameter = numVal(culetDiameter,"mm")
            self.hasBindingRing = False

        if self.type == "toroid":   
            if numberOfToroids is None:
                raise ValueError("numberOfToroids must be provided for toroidal anvils")
            self.numberOfToroids = numberOfToroids
            if numberOfToroids == 1:
                self.innerDiameter = numVal(6,"mm")
            elif numberOfToroids == 2:
                self.innerDiameter = numVal(3,"mm")
    
            self.hasBindingRing = True #default to true, can be overridden

        self.stringDescriptor = self.buildStringDescriptor()

        #optional extra info        
        self.manufacturer = ""
        self.comment = ""
        self.UB = [] #aspirational, but could be included...
        self.stlFile = f"{self.stringDescriptor}.stl"


    def to_dict(self):
        return {
            "type": self.type,
            "material": self.material,
            "culetDiameter": self.culetDiameter,
            "numberOfToroids": self.numberOfToroids,
            "innerDiameter": getattr(self, 'innerDiameter', None),  # only for toroidal anvils
            "hasBindingRing": self.hasBindingRing,
            "stlFile": self.stlFile,
            "manufacturer": self.manufacturer,
            "stringDescriptor": self.stringDescriptor,
            "comment": self.comment,
            "UB": self.UB
        }
    
    def buildStringDescriptor(self):

        # create a short string to represent instance

        if self.type == "single-crystal":
            stringDescriptor = f"anvil_SXL_{self.material}_culet_{self.culetDiameter}"
        elif self.type == "polycrystalline":
            stringDescriptor = f"anvil_{self.culetGeometry}_{self.model}_{self.material}"

        return stringDescriptor.replace(" ","_")

    @classmethod
    def from_dict(cls, data):
        #instantiate class from data dictionary

        obj = cls(
            type=data["type"],
            material=data["material"],
            culetGeometry=data["culetGeometry"],
            culetDiameter=data["culetDiameter"],
            model=data["model"]
        )
        obj.cadFile = data.get("cadFile", "") 
        obj.manufacturer = data.get("manufacturer", "")
        obj.comment = data.get("comment", "")
        obj.UB = data.get("UB", [])
        return obj

class gasket:
    #class to define a generic gasket component

    def __init__(self,
                 model,
                 material,
                 initialIndentThickness=None,
                 initialHoleDiameter=None,
                 ):

        self.type = "gasket"

        #validate material
        materialFound = SEE.materialInDatabase(material)
        if materialFound: 
            self.material = material
        else:
            raise ValueError(f"Material '{material}' not found in database.")

        
        self.allowedModels = ["flat","toroidal"]
        if model.lower() in self.allowedModels:
            self.model = model.lower()
        else:
            raise ValueError(f"{model} isn\'t supported, options are:{allowedModels}")

        if initialIndentThickness is not None:
            self.initialThickness = numVal(initialIndentThickness,"mm")
            self.initialThicknessDiameter.source = "measured"

        if initialHoleDiameter is not None:
            self.initialHoleDiameter = numVal(initialHoleDiameter,"mm")
            self.initialHoleDiameter.source = "measured"

        self.stringDescriptor = self.buildStringDescriptor()

        #optional extra info
        self.stlFile = f"{self.stringDescriptor}.stl"
        self.manufacturer=""
        self.comment=""

        self.validate()

    def to_dict(self):
        return {
            "type": "gasket",
            "model": self.model,
            "material": self.material,
            "initialIndentThickness": self.initialIndentThickness,
            "initialHoleDiameter": self.initialHoleDiameter,
            "stringDescriptor": self.stringDescriptor,
            "stlFile": self.stlFile,
            "manufacturer": self.manufacturer,
            "comment": self.comment
        }
    
    @classmethod
    def from_dict(cls, data):
        #instantiate class from data dictionary
        obj = cls(
            model=data["model"],
            material=data["material"],
        )
        obj.data.get("manufacturer","")
        obj.stlFile = data.get("stlFile", "")
        obj.comment = data.get("comment", "")
        return obj


    def buildStringDescriptor(self):
        return f"gasket_{self.material}_{self.model}".replace(" ","_")

class cylinder:
    #class to define a generic cylinder component

    def __init__(self,
                 material,
                 ID,
                 OD,
                 height,
                 axis=[0,1,0],
                 center=[0,0,0]):

        # validate material
        materialFound = SEE.materialInDatabase(material)
        if materialFound: 
            self.material = material
        else:
            raise ValueError(f"Material '{material}' not found in database.")
        
        self.ID = numVal(ID,"mm")
        self.OD = numVal(OD,"mm")
        self.height = numVal(height,"mm")
        self.center = center
        self.axis=axis

        self.stringDescriptor = self.buildStringDescriptor()
        self.stlFile = f"{self.stringDescriptor}.stl"
        self.manufacturer=""
        self.comment=""

        self.validate()
        self.buildMantidDictionaries() 

    def to_dict(self):
        return {
            "type": "cylinder",
            "material": self.material,
            "ID": self.ID,
            "OD": self.OD,
            "height": self.height,
            "axis": self.axis,
            "center": self.center,
            "stringDescriptor": self.stringDescriptor,
            "cadFile": self.stlFile,
            "comment": self.comment
        }
    
    @classmethod
    def from_dict(cls, data):
        #instantiate class from data dictionary
        obj = cls(
            material=data["material"],
            ID=data["ID"],
            OD=data["OD"],
            height=data["height"],
            axis=data.get("axis", [0, 1, 0]),
            center=data.get("center", [0, 0, 0])
        )
        obj.cadFile = data.get("cadFile", "")
        obj.comment = data.get("comment", "")
        return obj

    def validate(self):

        #boiler plate validation for the cylinder class
        assert type(self.material) is str, "material must be a string"
        assert len(self.material) > 0, "material must not be an empty string"
        assert type(self.ID) is float
        assert type(self.height) is float
        assert self.ID<=self.OD, "ID must be less than or equal to OD"
        assert type(self.OD) is float
        assert self.OD > 0, "OD must be greater than zero"

        for vector in [self.axis, self.center]:
            assert type(vector) is list, f"{vector} must be a list"
            assert len(vector) == 3, f"{vector} must be a 3-element list"
            for element in vector:
                assert type(element) is float, f"All elements of {vector} must be floats"

    def buildMantidDictionaries(self):

        #create the mantid dictionaries that are needed for absorption corrections
        self.mantidContainerGeometry = {
            "shape":"HollowCylinder",
            "height":self.height,
            "InnerRadius":self.ID/2,
            "OuterRadius":self.OD/2,
            "Center":self.center,
            "Axis":self.axis
        }

        self.mantidContainerMaterial={
            "ChemicalFormula":self.chemicalFormula,
            "NumberDensity":1.0,
            "MassDensity":self.massDensity       
        }


    def buildStringDescriptor(self):
        return f"cyl_{self.material}_{self.ID.value:.1}{self.ID.units}_{self.height.value:.1}{self.ID.units}".replace(" ","_")