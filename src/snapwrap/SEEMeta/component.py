# import json
# import os

import snapwrap.SEEMeta.utils as SEE


class numVal:
    def __init__(self, value, units):
        self.value = float(value)
        allowed = {'ang','nm','um','mm','cm','m','deg','rad'}
        units_l = units.lower()
        if units_l not in allowed:
            raise ValueError(f"Invalid units specified: {units}. options are {sorted(allowed)}")
        self.units = units_l
        self.source = None

    def to_dict(self):
        return {"value": self.value, "units": self.units, "source": self.source}

    @classmethod
    def from_dict(cls, data):
        obj = cls(data["value"], data["units"])
        obj.source = data.get("source")
        return obj
    
    def __str__(self):
        return f"{self.value} {self.units}"

class anvil:
    def __init__(self, type, material, numberOfToroids=None, culetDiameter=None):
        # validate type
        if type not in ("DAC", "toroidal"):
            raise ValueError(f"Invalid anvil type: {type}. Must be 'DAC' or 'toroidal'.")
        self.type = type

        # material
        if not SEE.materialInDatabase(material):
            raise ValueError(f"Material '{material}' not found in database.")
        self.material = material
        matprop = SEE.get_material_details(material)
        self.UB = [] if matprop.get("isSingleCrystal") else None

        # per-type fields
        if self.type == "DAC":
            if culetDiameter is None:
                raise ValueError("culetDiameter must be provided for DAC anvils")
            self.culetDiameter = numVal(culetDiameter, "mm")
            self.hasBindingRing = False
            self.numberOfToroids = None
            self.innerDiameter = None

        else:  # "toroidal"
            if numberOfToroids is None:
                raise ValueError("numberOfToroids must be provided for toroidal anvils")
            self.numberOfToroids = int(numberOfToroids)
            self.innerDiameter = numVal(6 if self.numberOfToroids == 1 else 3, "mm")
            self.culetDiameter = None
            self.hasBindingRing = True

        # optional
        self.manufacturer = ""
        self.comment = ""

        self.stringDescriptor = self.buildStringDescriptor()
        self.stlFile = f"{self.stringDescriptor}.stl"

    def buildStringDescriptor(self):
        # pick something that always exists
        if self.type == "DAC":
            d = f"{self.culetDiameter.value:.1f}{self.culetDiameter.units}" if self.culetDiameter else "NA"
            return f"anvil_DAC_{self.material}_culet_{d}".replace(" ","_")
        else:
            return f"anvil_toroidal_{self.material}_ntor_{self.numberOfToroids}".replace(" ","_")

    def to_dict(self):
        return {
            "type": self.type,
            "material": self.material,
            "culetDiameter": self.culetDiameter.to_dict() if self.culetDiameter else None,
            "numberOfToroids": self.numberOfToroids,
            "innerDiameter": self.innerDiameter.to_dict() if self.innerDiameter else None,
            "hasBindingRing": self.hasBindingRing,
            "stlFile": self.stlFile,
            "manufacturer": self.manufacturer,
            "stringDescriptor": self.stringDescriptor,
            "comment": self.comment,
            "UB": self.UB,
        }

    @classmethod
    def from_dict(cls, data):
        t = data["type"]
        mat = data["material"]
        cd = data.get("culetDiameter")
        nt = data.get("numberOfToroids")
        obj = cls(
            type=t,
            material=mat,
            culetDiameter=cd["value"] if cd else None,
            numberOfToroids=nt
        )
        obj.innerDiameter = numVal.from_dict(data["innerDiameter"]) if data.get("innerDiameter") else obj.innerDiameter
        obj.hasBindingRing = data.get("hasBindingRing", obj.hasBindingRing)
        obj.manufacturer = data.get("manufacturer", "")
        obj.comment = data.get("comment", "")
        obj.UB = data.get("UB", obj.UB)
        obj.stringDescriptor = data.get("stringDescriptor", obj.stringDescriptor)
        obj.stlFile = data.get("stlFile", obj.stlFile)
        return obj


class gasket:
    def __init__(self, model, material, initialIndentThickness=None, initialHoleDiameter=None):
        self.type = "gasket"
        if not SEE.materialInDatabase(material):
            raise ValueError(f"Material '{material}' not found in database.")
        self.material = material

        self.allowedModels = ["flat", "toroidal"]
        model_l = model.lower()
        if model_l not in self.allowedModels:
            raise ValueError(f"{model} isn't supported, options are: {self.allowedModels}")
        self.model = model_l

        self.initialIndentThickness = numVal(initialIndentThickness, "mm") if initialIndentThickness is not None else None
        if self.initialIndentThickness: self.initialIndentThickness.source = "measured"

        self.initialHoleDiameter = numVal(initialHoleDiameter, "mm") if initialHoleDiameter is not None else None
        if self.initialHoleDiameter: self.initialHoleDiameter.source = "measured"

        self.stringDescriptor = self.buildStringDescriptor()
        self.stlFile = f"{self.stringDescriptor}.stl"
        self.manufacturer = ""
        self.comment = ""

    def to_dict(self):
        return {
            "type": "gasket",
            "model": self.model,
            "material": self.material,
            "initialIndentThickness": self.initialIndentThickness.to_dict() if self.initialIndentThickness else None,
            "initialHoleDiameter": self.initialHoleDiameter.to_dict() if self.initialHoleDiameter else None,
            "stringDescriptor": self.stringDescriptor,
            "stlFile": self.stlFile,
            "manufacturer": self.manufacturer,
            "comment": self.comment
        }

    @classmethod
    def from_dict(cls, data):
        obj = cls(
            model=data["model"],
            material=data["material"],
            initialIndentThickness=(data["initialIndentThickness"]["value"] if data.get("initialIndentThickness") else None),
            initialHoleDiameter=(data["initialHoleDiameter"]["value"] if data.get("initialHoleDiameter") else None),
        )
        obj.manufacturer = data.get("manufacturer", "")
        obj.stlFile = data.get("stlFile", obj.stlFile)
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
                 axis=[0.0,1.0,0.0],
                 center=[0.0,0.0,0.0]):

        # validate material
        materialFound = SEE.materialInDatabase(material)
        if materialFound: 
            self.material = material
        else:
            raise ValueError(f"Material '{material}' not found in database.")
        
        try:
            self.chemicalFormula = SEE.get_material_details(material)["chemical_formula"]
            self.massDensity = SEE.get_material_details(material)["mass_density_g_cm3"]
        except KeyError as e:
            raise ValueError(f"Material '{material}' missing required properties: {e}")
        
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
            "ID": self.ID.value,
            "OD": self.OD.value,
            "height": self.height.value,
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
            axis=data.get("axis", [0.0, 1.0, 0.0]),
            center=data.get("center", [0.0, 0.0, 0.0])
        )
        obj.cadFile = data.get("cadFile", "")
        obj.comment = data.get("comment", "")
        return obj

    def validate(self):

        #boiler plate validation for the cylinder class

        assert self.ID.value<=self.OD.value, "ID must be less than or equal to OD"
        assert type(self.OD.value) is float
        assert self.OD.value > 0, "OD must be greater than zero"

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
            "InnerRadius":self.ID.value/2,
            "OuterRadius":self.OD.value/2,
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