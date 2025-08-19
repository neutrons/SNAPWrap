from __future__ import annotations
from dataclasses import dataclass, asdict, fields, field, is_dataclass
from typing import Any, ClassVar, Dict, Mapping, Optional, Tuple, Type, get_args, get_origin
import json

import snapwrap.SEEMeta.utils as SEE

# ---------- Value-with-units ----------
@dataclass(frozen=True, slots=True)
class numVal:
    value: float
    units: str
    source: Optional[str] = None

    _ALLOWED: ClassVar[set[str]] = {"ang", "nm", "um", "mm", "cm", "m", "deg", "rad"}

    def __post_init__(self):
        u = self.units.lower()
        if u not in self._ALLOWED:
            raise ValueError(f"Invalid units: {self.units}. Allowed: {sorted(self._ALLOWED)}")
        object.__setattr__(self, "units", u)

    def to_dict(self) -> Dict[str, Any]:
        return {"value": self.value, "units": self.units, "source": self.source}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "NumVal":
        return cls(value=d["value"], units=d["units"], source=d.get("source"))
    
    def __str__(self):
        return f"{self.value} {self.units}"

# ---------- Component base + registry ----------

_REGISTRY: Dict[str, Type["Component"]] = {}

def register(cls: Type["Component"]) -> Type["Component"]:
    """Decorator to register a component class by its .kind tag."""
    key = getattr(cls, "kind", None)
    if not key:
        raise ValueError(f"{cls.__name__} must define a ClassVar[str] 'kind'.")
    if key in _REGISTRY and _REGISTRY[key] is not cls:
        raise ValueError(f"Duplicate component kind: {key}")
    _REGISTRY[key] = cls
    return cls

def _is_dataclass_type(tp: Any) -> Optional[Type]:
    """Return the dataclass type if tp is a dataclass or Optional[dataclass], else None."""
    if isinstance(tp, type) and is_dataclass(tp):
        return tp
    origin = get_origin(tp)
    if origin is Optional or origin is Union := getattr(__import__("typing"), "Union", None):
        for arg in get_args(tp):
            if arg is type(None):
                continue
            if isinstance(arg, type) and is_dataclass(arg):
                return arg
    return None

def _coerce_init_kwargs(kls: Type, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Filter unknown keys and coerce nested dataclass fields using .from_dict if present."""
    allowed = {f.name: f for f in fields(kls)}
    kwargs: Dict[str, Any] = {}
    # get_type_hints handles Optional/Union
    try:
        from typing import get_type_hints
        hints = get_type_hints(kls)
    except Exception:
        hints = {f.name: f.type for f in fields(kls)}

    for name, f in allowed.items():
        if name not in payload:
            continue
        val = payload[name]
        hinted = hints.get(name, f.type)
        dcls = _is_dataclass_type(hinted)
        if dcls and isinstance(val, Mapping):
            # Prefer custom from_dict if available
            if hasattr(dcls, "from_dict"):
                kwargs[name] = dcls.from_dict(val)  # type: ignore
            else:
                kwargs[name] = dcls(**val)  # naive
        else:
            kwargs[name] = val
    return kwargs

@dataclass(slots=True)
class Component:
    """Base class with shared (de)serialization and schema migration."""
    # Stable wire identifier for this concrete class, e.g. "anvil.dac"
    kind: ClassVar[str] = "component"
    # Schema version for this specific kind
    version: ClassVar[int] = 1

    # ---- Serialization ----
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["type"] = self.kind
        d["version"] = self.version
        return d

    @classmethod
    def upgrade(cls, payload: Dict[str, Any], from_version: int) -> Dict[str, Any]:
        """Override in subclasses to migrate payloads forward. Default: no-op."""
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Component":
        """Dispatch via 'type' tag, apply migrations, and hydrate nested dataclasses."""
        t = payload.get("type")
        if not t:
            raise ValueError("Missing 'type' in payload")
        kls = _REGISTRY.get(t)
        if not kls:
            raise ValueError(f"Unknown component type: {t}")

        # Work on a copy; strip meta
        data = dict(payload)
        data.pop("type", None)
        from_version = int(data.pop("version", 1))

        # Migrate to current class version
        while from_version < kls.version:
            data = kls.upgrade(data, from_version)
            from_version += 1

        # Filter/convert init kwargs
        init_kwargs = _coerce_init_kwargs(kls, data)
        obj = kls(**init_kwargs)  # type: ignore[misc]

        # Apply any extra non-init fields from payload that survived (forward-compat)
        for k, v in data.items():
            if hasattr(obj, k) and k not in init_kwargs:
                setattr(obj, k, v)
        return obj

@register
@dataclass(slots=True)
class Anvil(Component):
    kind: ClassVar[str] = "anvil"
    type: str
    material: str
    numberOfToroids: Optional[int] = None
    culetDiameter: Optional[numVal] = None
    innerDiameter: Optional[numVal] = None
    hasBindingRing: Optional[bool] = None
    manufacturer: str = ""
    comment: str = ""
    stringDescriptor: str = field(init=False)
    stlFile: str = field(init=False)
    UB: Optional[list] = field(default=None)

    def __post_init__(self):
        # Validate type
        if self.type not in ("DAC", "toroidal"):
            raise ValueError(f"Invalid anvil type: {self.type}. Must be 'DAC' or 'toroidal'.")
        # Validate material
        if not SEE.materialInDatabase(self.material):
            raise ValueError(f"Material '{self.material}' not found in database.")
        matprop = SEE.get_material_details(self.material)
        self.UB = [] if matprop.get("isSingleCrystal") else None

        # Per-type fields
        if self.type == "DAC":
            if self.culetDiameter is None:
                raise ValueError("culetDiameter must be provided for DAC anvils")
            self.hasBindingRing = False
            self.numberOfToroids = None
            self.innerDiameter = None
        else:  # "toroidal"
            if self.numberOfToroids is None:
                raise ValueError("numberOfToroids must be provided for toroidal anvils")
            self.innerDiameter = numVal(6 if self.numberOfToroids == 1 else 3, "mm")
            self.culetDiameter = None
            self.hasBindingRing = True

        self.stringDescriptor = self.buildStringDescriptor()
        self.stlFile = f"{self.stringDescriptor}.stl"

    def buildStringDescriptor(self):
        if self.type == "DAC":
            d = f"{self.culetDiameter.value:.1f}{self.culetDiameter.units}" if self.culetDiameter else "NA"
            return f"anvil_DAC_{self.material}_culet_{d}".replace(" ","_")
        else:
            return f"anvil_toroidal_{self.material}_ntor_{self.numberOfToroids}".replace(" ","_")

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