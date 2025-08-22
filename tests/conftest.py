import importlib
import pytest
from snapwrap import SEEMeta as SEEMeta_pkg
import snapwrap.SEEMeta.component as component_mod

# Add near the top, after imports

@pytest.fixture(scope="session", autouse=True)
def clear_module_cache():
    """Force reload key modules to avoid cached state from previous runs."""
    import sys
    import importlib
    
    # List modules that need fresh reloading
    modules_to_reload = [
        'snapwrap.SEEMeta.component',
        'snapwrap.SEEMeta',
    ]
    
    # Reload each module and ensure SEE is patched
    for module_name in modules_to_reload:
        if module_name in sys.modules:
            mod = importlib.reload(sys.modules[module_name])
            if hasattr(mod, 'SEE'):
                mod.SEE = DummySEE
    
    # Direct patch for component_mod
    if 'snapwrap.SEEMeta.component' in sys.modules:
        sys.modules['snapwrap.SEEMeta.component'].SEE = DummySEE

class DummySEE:
    @staticmethod
    def materialInDatabase(name: str) -> bool:
        return name in {"singleCrystalDiamond", "W", "TiZr", "testCrystal","ZTA"}

    @staticmethod
    def get_material_details(name: str) -> dict:
        if name == "singleCrystalDiamond":
            return {"chemical_formula": "C", "mass_density_g_cm3": 3.51, "isSingleCrystal": True}
        if name == "W":
            return {"chemical_formula": "W", "mass_density_g_cm3": 19.25, "isSingleCrystal": False}
        if name == "TiZr":
            return {"chemical_formula": "Zr0.32-Ti0.68", "mass_density_g_cm3": 5.23, "isSingleCrystal": False}
        if name == "testCrystal":
            return {"chemical_formula": "(Li7)2-C-H4-N-Cl6", "mass_density_g_cm3": 5.0, "isSingleCrystal": False}
        if name == "ZTA":
            return {"chemical_formula": "Al0.33-O0.61-Zr0.05", "mass_density_g_cm3": 4.37, "isSingleCrystal": False}
        return {}

# initial assignment and reload to ensure component module picks it up
SEEMeta_pkg.SEE = DummySEE
component_mod.SEE = DummySEE
importlib.reload(component_mod)
component_mod.SEE = DummySEE
SEEMeta_pkg.SEE = DummySEE

@pytest.fixture(autouse=True)
def enforce_dummy_see():
    """Ensure DummySEE is applied before each test to avoid other tests clobbering it."""
    component_mod.SEE = DummySEE
    SEEMeta_pkg.SEE = DummySEE
    yield
    # re-assert after test in case it was changed
    component_mod.SEE = DummySEE
    SEEMeta_pkg.SEE = DummySEE