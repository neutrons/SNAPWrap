from __future__ import annotations
from dataclasses import dataclass, asdict, fields, field, is_dataclass
from typing import Any, ClassVar, Dict, Mapping, Optional, Tuple, Type, get_args, get_origin
import json
import re

import snapwrap.SEEMeta.utils as SEE

# --- helper placed near top-level of module ---

def _validate_chemical_formula(formula: str) -> bool:
    """
    Conservative validator for Mantid-style chemical formulas.

    Accepted forms:
    - Hyphen-separated species, e.g. "(Li7)2-C-H4-N-Cl6"
    - Concatenated element tokens like "H2O" (parsed by element symbols)
    Species may be:
      - an isotope: (ElementSymbolMassNumber) optionally followed by a multiplicity (int or float)
        e.g. (Li7)2
      - an element symbol: ElementSymbol optionally followed by multiplicity (int or float)
        e.g. Cl6 or C or H4.5

    Returns True if the formula matches these conservative rules, False otherwise.
    """
    if not isinstance(formula, str) or not formula:
        return False

    # hyphen-separated full-match regex:
    # species = (isotope_group | element_symbol) [count]
    # isotope_group: \( [A-Z][a-z]? \d+ \)
    # element_symbol: [A-Z][a-z]?
    # count: integer or float (e.g. 2 or 2.0 or 2.5)
    species_re = r"(?:\([A-Z][a-z]?\d+\)|[A-Z][a-z]?)(?:\d+(?:\.\d+)?)?"
    hyphenated_re = re.compile(rf"^{species_re}(?:-{species_re})*$")
    if hyphenated_re.match(formula):
        return True

    # if not hyphenated, try to parse concatenated tokens like H2O, C6H12O6, etc.
    idx = 0
    L = len(formula)
    token_re = re.compile(r"^\(?([A-Z][a-z]?\d+)\)?(?:\d+(?:\.\d+)?)?")
    # simpler parser: iterate consuming either isotope group or element symbol + optional count
    while idx < L:
        # try isotope group at current index
        if formula[idx] == "(":
            m = re.match(r"^\(([A-Z][a-z]?\d+)\)(\d+(?:\.\d+)?)?", formula[idx:])
            if not m:
                return False
            idx += m.end()
            continue
        # try element symbol + optional count
        m = re.match(r"^[A-Z][a-z]?(?:\d+(?:\.\d+)?)?", formula[idx:])
        if not m:
            return False
        idx += m.end()

    # if we consumed all characters it's valid
    return idx == L

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
    def from_dict(cls, d: Mapping[str, Any]) -> "numVal":
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
    Union = getattr(__import__("typing"), "Union", None)
    if origin is Optional or origin is Union:
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

    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serialNumber: Optional[str] = None
    location: Optional[str] = None
    # Optional human-readable description
    comment: Optional[str] = None
    stlFile: Optional[str] = None

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

    def setMantidMaterial(self, material_name: str, required: Optional[list] = None) -> Dict[str, Any]:
        """
        Fetch a subset of material properties from the SEE DB and return a dict
        mapped to keys suitable for creating a Mantid material.

        Validates material exists and required fields are present. Validates
        ChemicalFormula syntax using _validate_chemical_formula.
        """
        if not SEE.materialInDatabase(material_name):
            raise ValueError(f"Material '{material_name}' not found in database.")

        details = SEE.get_material_details(material_name)
        if not isinstance(details, dict):
            raise ValueError(f"Unexpected material details type for '{material_name}'")

        # mantid-friendly keys -> SEE DB keys
        mapping = {
            "ChemicalFormula": "chemical_formula",
            "MassDensity": "mass_density_g_cm3",
        }

        out: Dict[str, Any] = {}
        for out_key, db_key in mapping.items():
            val = details.get(db_key)
            if val is not None:
                out[out_key] = val

        # Validate chemical formula syntax if present
        formula = out.get("ChemicalFormula")
        if formula is not None and not _validate_chemical_formula(formula):
            raise ValueError(f"Material '{material_name}' has invalid ChemicalFormula syntax: '{formula}'")

        # default required fields
        if required is None:
            required = ["ChemicalFormula", "MassDensity"]
        missing_required = [k for k in required if out.get(k) in (None, "", [])]

        if missing_required:
            raise ValueError(f"Material '{material_name}' missing required properties: {missing_required}")

        return out

@register
@dataclass(slots=True, kw_only=True)
class DACAnvil(Component):
    kind: ClassVar[str] = "anvil.dac"
    culetDiameter: numVal  # required, now keyword-only
    material: str = "singleCrystalDiamond"
    stringDescriptor: str = field(init=False)
    UB: Optional[list] = field(default=None)
    Notches: Optional[list] = field(default=None)

    def __post_init__(self):
        # Validate material
        if not SEE.materialInDatabase(self.material):
            raise ValueError(f"Material '{self.material}' not found in database.")
        matprop = SEE.get_material_details(self.material)
        self.UB = [] if matprop.get("isSingleCrystal") else None

        self.stringDescriptor = self.buildStringDescriptor()
        self.stlFile = f"{self.stringDescriptor}.stl"

    def buildStringDescriptor(self):
        d = f"{self.culetDiameter.value:.1f}{self.culetDiameter.units}" if self.culetDiameter else "NA"
        return f"anvil_DAC_culet_{d}".replace(" ","_")

@register
@dataclass(slots=True, kw_only=True)
class toroidAnvil(Component):
    """Toroidal anvil: requires material and numberOfToroids.

    - material: required material name (no default)
    - numberOfToroids: required int (no default)
    - stringDescriptor is built in __post_init__
    """
    kind: ClassVar[str] = "anvil.toroidal"

    material: str
    numberOfToroids: int
    stringDescriptor: str = field(init=False)

    def __post_init__(self):
        # validate material exists and fetch properties
        if not SEE.materialInDatabase(self.material):
            raise ValueError(f"Material '{self.material}' not found in database.")

        # build derived descriptors
        self.stringDescriptor = self.buildStringDescriptor()
        self.stlFile = f"{self.stringDescriptor}.stl"

    def buildStringDescriptor(self) -> str:
        if self.numberOfToroids == 1:
            toroid_str = "1_toroid"
        else:
            toroid_str = f"{self.numberOfToroids}_toroids"
        return (
            f"anvil_{toroid_str}_{self.material}"
        ).replace(" ", "_")