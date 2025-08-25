from __future__ import annotations
from dataclasses import dataclass, fields, field, asdict
from typing import Any, ClassVar, Dict, List, Mapping, Optional, Type

from snapwrap.SEEMeta.component import (
    Component,
    DACAnvil,
    DACGasket,
    toroidAnvil,
    toroidGasket,
    cylinder,
)  # concrete Component classes live here


_ASM_REGISTRY: Dict[str, Type["Assembly"]] = {}


def register_assembly(cls: Type["Assembly"]) -> Type["Assembly"]:
    key = getattr(cls, "kind", None)
    if not key:
        raise ValueError(f"{cls.__name__} must define a ClassVar[str] 'kind'.")
    if key in _ASM_REGISTRY and _ASM_REGISTRY[key] is not cls:
        raise ValueError(f"Duplicate assembly kind: {key}")
    _ASM_REGISTRY[key] = cls
    return cls


def _coerce_asm_init_kwargs(kls: Type["Assembly"], payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build init kwargs for an Assembly subclass.
    Special-case: convert component dicts -> Component instances via Component.from_dict.
    """
    allowed = {f.name: f for f in fields(kls) if f.init}
    kwargs: Dict[str, Any] = {}

    for name, f in allowed.items():
        if name not in payload:
            continue
        val = payload[name]
        if name == "components" and isinstance(val, list):
            comps = []
            for item in val:
                if isinstance(item, Mapping):
                    comps.append(Component.from_dict(item))
                else:
                    comps.append(item)
            kwargs[name] = comps
        else:
            kwargs[name] = val
    return kwargs


@dataclass(slots=True, kw_only=True)
class Assembly:
    """
    Generic assembly container. Subclasses should set a concrete `kind`.
    Instances contain a list of Component instances and simple metadata fields.
    """
    kind: ClassVar[str] = "assembly"
    version: ClassVar[int] = 1

    components: List[Component] = field(default_factory=list)
    comment: Optional[str] = None
    model: Optional[str] = None
    serialNumber: Optional[str] = None
    orientation: List[float] = field(default_factory=lambda: [0.0, 1.0, 0.0])
    stringDescriptor: str = field(init=False)

    def __post_init__(self) -> None:
        # normalize/validate orientation as a 3-element list of floats
        if self.orientation is None:
            self.orientation = [0.0, 1.0, 0.0]
        else:
            # accept tuples, lists, numpy arrays etc.
            try:
                seq = list(self.orientation)
            except Exception:
                raise ValueError("orientation must be an iterable of three numeric values")
            if len(seq) != 3:
                raise ValueError("orientation must have exactly three elements")
            self.orientation = [float(x) for x in seq]

        # build stringDescriptor from assembly kind and included component kinds
        comp_kinds = [getattr(c, "kind", "component") for c in self.components]
        parts = [self.kind] + comp_kinds
        # join with underscores and replace spaces just in case
        self.stringDescriptor = "_".join(part.replace(" ", "_") for part in parts if part)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # replace component objects with their dict representations
        d["components"] = [c.to_dict() for c in self.components]
        d["type"] = self.kind
        d["version"] = self.version
        return d

    @classmethod
    def upgrade(cls, payload: Dict[str, Any], from_version: int) -> Dict[str, Any]:
        # override in concrete classes if migration needed
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Assembly":
        t = payload.get("type")
        if not t:
            raise ValueError("Missing 'type' in assembly payload")
        kls = _ASM_REGISTRY.get(t)
        if not kls:
            raise ValueError(f"Unknown assembly type: {t}")

        data = dict(payload)
        data.pop("type", None)
        from_version = int(data.pop("version", 1))

        while from_version < kls.version:
            data = kls.upgrade(data, from_version)
            from_version += 1

        init_kwargs = _coerce_asm_init_kwargs(kls, data)
        obj = kls(**init_kwargs)  # type: ignore[misc]

        # Set any remaining (non-init) fields present in payload
        for k, v in data.items():
            if hasattr(obj, k) and k not in init_kwargs:
                setattr(obj, k, v)
        return obj

# Concrete assemblies --------------------------------------------------------

@register_assembly
@dataclass(slots=True, kw_only=True)
class DAC(Assembly):
    kind: ClassVar[str] = "assembly.dac"
    # components default empty list; caller typically supplies [anvil, gasket, ...]


    def __post_init__(self) -> None:
        # run generic assembly post-init (orientation normalization etc.)
        Assembly.__post_init__(self)

        # Count DACAnvil and DACGasket instances
        anvil_count = sum(1 for c in self.components if isinstance(c, DACAnvil))
        gasket_count = sum(1 for c in self.components if isinstance(c, DACGasket))

        if anvil_count != 1:
            raise ValueError(f"DAC assembly requires exactly one DACAnvil; found {anvil_count}")
        if gasket_count != 1:
            raise ValueError(f"DAC assembly requires exactly one DACGasket; found {gasket_count}")

        # Ensure there are no other anvil or gasket types present
        for c in self.components:
            kind = getattr(c, "kind", "")
            if kind.startswith("anvil.") and not isinstance(c, DACAnvil):
                raise ValueError(f"DAC assembly cannot contain anvil of type '{kind}'")
            if kind.startswith("gasket.") and not isinstance(c, DACGasket):
                raise ValueError(f"DAC assembly cannot contain gasket of type '{kind}'")


@register_assembly
@dataclass(slots=True, kw_only=True)
class PE(Assembly):
    kind: ClassVar[str] = "assembly.pe"

    def __post_init__(self) -> None:
        # run generic assembly post-init (orientation normalization etc.)
        Assembly.__post_init__(self)

        # Count toroidAnvil and toroidGasket instances
        anvil_count = sum(1 for c in self.components if isinstance(c, toroidAnvil))
        gasket_count = sum(1 for c in self.components if isinstance(c, toroidGasket))

        if anvil_count != 1:
            raise ValueError(f"PE assembly requires exactly one toroidAnvil; found {anvil_count}")
        if gasket_count != 1:
            raise ValueError(f"PE assembly requires exactly one toroidGasket; found {gasket_count}")

        # Ensure there are no other anvil or gasket types present
        for c in self.components:
            kind = getattr(c, "kind", "")
            if kind.startswith("anvil.") and not isinstance(c, toroidAnvil):
                raise ValueError(f"PE assembly cannot contain anvil of type '{kind}'")
            if kind.startswith("gasket.") and not isinstance(c, toroidGasket):
                raise ValueError(f"PE assembly cannot contain gasket of type '{kind}'")

# ---------- CylinderCell assembly with concentric-cylinder validation ----------
@register_assembly
@dataclass(slots=True, kw_only=True)
class CylinderCell(Assembly):
    kind: ClassVar[str] = "assembly.cylinder"

    def __post_init__(self) -> None:
        # run generic assembly post-init (orientation normalization etc.)
        Assembly.__post_init__(self)

        # gather cylinder components in the order they appear in components list
        cyls = [c for c in self.components if isinstance(c, cylinder)]

        if not cyls:
            raise ValueError("CylinderCell assembly requires at least one cylinder component")

        # Ensure all cylinder units match for inner/outer comparisons
        base_units = cyls[0].innerDiameter.units
        for c in cyls:
            if c.innerDiameter.units != base_units or c.outerDiameter.units != base_units:
                raise ValueError("CylinderCell: all cylinder numVal units must match")

        # Sort cylinders by innerDiameter.value ascending
        sorted_cyls = sorted(cyls, key=lambda c: c.innerDiameter.value)

        # Replace cylinders in self.components preserving positions of non-cylinder components:
        it = iter(sorted_cyls)
        new_components = []
        for comp in self.components:
            if isinstance(comp, cylinder):
                new_components.append(next(it))
            else:
                new_components.append(comp)
        self.components = new_components

        # adjacency check (concentric / adjoining)
        for i in range(1, len(sorted_cyls)):
            prev = sorted_cyls[i - 1]
            cur = sorted_cyls[i]
            if cur.innerDiameter.value != prev.outerDiameter.value:
                raise ValueError(
                    "CylinderCell: cylinders must be adjoining and concentric; "
                    f"{i}: innerDiameter ({cur.innerDiameter.value}{cur.innerDiameter.units}) "
                    f"!= previous outerDiameter ({prev.outerDiameter.value}{prev.outerDiameter.units})"
                )