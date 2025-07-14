# Integrated Panel UI: Anvil + OpposedAnvilCell
import panel as pn
pn.extension()

import os
import json
import traceback

from snapwrap.SEEMeta.material import material
from snapwrap.SEEMeta.assembly import opposedAnvilCell
from snapwrap.SEEMeta.component import anvil,cylinder
from snapwrap.wrapConfig import WrapConfig
# from sqlalchemy import create_engine

# ===================== LOAD MATERIALS DATABASE ================
# # Connect to your DB
# engine = create_engine("sqlite:///materials/materials.db")
# # Load all materials into a list

# n.b. materials already imports database.

materials = material.load_all()
jsonComponentDir = WrapConfig.get("SEE/json/components") 
jsonAnvilDir = f"{jsonComponentDir}/anvils"
jsonCylinderDir = f"{jsonComponentDir}/cylinders"
jsonOACDir = WrapConfig.get("SEE/json/opposedAnvilCells")
jsonCCDir = WrapConfig.get("SEE/json/cylinderCells")



# ===================== ANVIL BUILDER ==========================

# assign materials this hardwires that materials must be present
# in database.

save_directory = pn.widgets.TextInput(name="Save Directory", 
                                      value=jsonAnvilDir)

zta = material(name="zta")
wc = material(name="wc")
sinteredDiamond = material(name="sintereddiamond")
sxldiamond = material(name="singlecrystaldiamond")
cbn = material(name="cbn")


type_options = ["polycrystalline", "single-crystal"]
material_map = {
    "polycrystalline": [zta.name, wc.name, sinteredDiamond.name, cbn.name],
    "single-crystal": [sxldiamond.name]
}
geometry_map = {
    "polycrystalline": ["single toroid", "double toroid", "bridgman"],
    "single-crystal": ["flat", "bevelled"]
}
model_map = {
    "polycrystalline": ["standard", "3mm dimple", "other"],
    "single-crystal": ["conical", "flat", "other"]
}
culetDiameter_map = {
    "polycrystalline": 15.55,
    "single-crystal": 1.0
}

anvil_type = pn.widgets.Select(name="Type", options=type_options, value="polycrystalline")
anvil_material = pn.widgets.Select(name="Material")
anvil_culetGeometry = pn.widgets.Select(name="Culet Geometry")
anvil_model = pn.widgets.Select(name="Model")
anvil_culetDiameter = pn.widgets.FloatInput(name="Culet Diameter (mm)")
anvil_cadFile = pn.widgets.TextInput(name="CAD File (path)", placeholder="optional")
anvil_manufacturer = pn.widgets.TextInput(name="Manufacturer", placeholder="optional")
anvil_comment = pn.widgets.TextAreaInput(name="Comment", placeholder="optional")
anvil_file_selector = pn.widgets.Select(name="Load Existing Anvil")

@pn.depends(anvil_type.param.value, watch=True)
def update_dependent_fields(tval):
    anvil_material.options = material_map.get(tval, [])
    anvil_material.value = anvil_material.options[0] if anvil_material.options else ""

    anvil_culetGeometry.options = geometry_map.get(tval, [])
    anvil_culetGeometry.value = anvil_culetGeometry.options[0] if anvil_culetGeometry.options else ""

    anvil_model.options = model_map.get(tval, [])
    anvil_model.value = anvil_model.options[0] if anvil_model.options else ""

    anvil_culetDiameter.value = culetDiameter_map.get(tval, 10.0)

update_dependent_fields(anvil_type.value)

output = pn.pane.JSON(name="Anvil JSON", depth=2, theme="light")

save_status = pn.pane.Markdown("")

def update_anvil_file_selector():
    directory = jsonAnvilDir
    if os.path.isdir(directory):
        files = [f for f in os.listdir(directory) if f.startswith("anvil") and f.endswith(".json")]
        anvil_file_selector.options = ["Select a file..."] + files
        anvil_file_selector.value = "Select a file..."
    else:
        anvil_file_selector.options = ["Select a file..."]
        anvil_file_selector.value = "Select a file..."

# Call once at startup
update_anvil_file_selector()

@pn.depends(save_directory.param.value, watch=True)
def _update_anvil_selector_on_dir_change(_):
    update_anvil_file_selector()

@pn.depends(
    anvil_type.param.value,
    anvil_material.param.value,
    anvil_culetGeometry.param.value,
    anvil_model.param.value,
    anvil_culetDiameter.param.value,
    anvil_cadFile.param.value,
    anvil_manufacturer.param.value,
    anvil_comment.param.value,
    watch=True
)
def update_anvil_output(*_):
    try:
        anv = anvil(
            type=anvil_type.value,
            material=anvil_material.value,
            culetGeometry=anvil_culetGeometry.value,
            culetDiameter=float(anvil_culetDiameter.value),
            model=anvil_model.value,
        )
        if anvil_cadFile.value.strip():
            anv.cadFile = anvil_cadFile.value
        anv.manufacturer = anvil_manufacturer.value
        anv.comment = anvil_comment.value
        output.object = anv.to_dict()

        print("TO_DICT:", anv.to_dict())

    except Exception as e:
        output.object = {
        "error": str(e),
        "traceback": traceback.format_exc()
    }

@pn.depends(anvil_file_selector.param.value, watch=True)
def load_anvil_from_file(selected_file):
    if not selected_file or selected_file == "Select a file...":
        return
    directory = jsonAnvilDir
    file_path = os.path.join(directory, selected_file)
    try:
        with open(file_path, "r") as f:
            anv_dict = json.load(f)
        anv_obj = anvil.from_dict(anv_dict)
        # Populate widgets
        anvil_type.value = anv_obj.type
        anvil_material.value = anv_obj.material
        anvil_culetGeometry.value = anv_obj.culetGeometry
        anvil_model.value = anv_obj.model
        anvil_culetDiameter.value = anv_obj.culetDiameter
        anvil_cadFile.value = getattr(anv_obj, "cadFile", "")
        anvil_manufacturer.value = getattr(anv_obj, "manufacturer", "")
        anvil_comment.value = getattr(anv_obj, "comment", "")
        output.object = anv_obj.to_dict()
        save_status.object = f"✅ Loaded anvil from `{selected_file}`"
    except Exception as e:
        save_status.object = f"❌ Failed to load: {e}"

save_button = pn.widgets.Button(name="Save Anvil to Disk", button_type="success")

def save_json(event):
    try:
        if isinstance(output.object, dict) and "error" not in output.object:
            json_str = json.dumps(output.object, indent=2)
            filename = output.object.get("stringDescriptor", "anvil") + ".json"
            directory = jsonAnvilDir
            if not directory:
                raise ValueError("Please specify a save directory.")
            full_path = os.path.join(directory, filename)
            os.makedirs(directory, exist_ok=True)
            with open(full_path, "w") as f:
                f.write(json_str)
            save_status.object = f"✅ Anvil saved to `{full_path}`"
    except Exception as e:
        save_status.object = f"❌ Save failed: {e}"

save_button.on_click(save_json)
update_anvil_output()

anvil_tab = pn.Column(
    pn.pane.Markdown("## Create an Anvil"),
    anvil_type,
    anvil_material,
    anvil_culetGeometry,
    anvil_model,
    anvil_culetDiameter,
    anvil_cadFile,
    anvil_manufacturer,
    anvil_comment,
    save_directory,
    anvil_file_selector,
    save_button,
    save_status,
    output
)

# ===================== OPPOSED ANVIL CELL BUILDER ==========================
oac_type = pn.widgets.Select(name="Type", options=["paris-edinburgh", "DAC"], value="paris-edinburgh")
save_directory = pn.widgets.TextInput(name="Save Directory", 
                                      value=jsonOACDir)
# assign materials
tizr = material(name="tizr")
zr = material(name="zr")
pyrophyllite = material(name="pyrophillite")
re = material(name="re")
ss301 = material(name="ss301")
w = material(name="w")

# The maps below restrict options to compatible attributes, keyed to the
# "Type" attribute. Also sets order of list of those compatible attributes

model_map_oac = {
    "paris-edinburgh": ["VX1", "VX3", "VX5"],
    "DAC": ["LEGACY", "MARK-VI", "MARK-VII"]
}
gasket_map = {
    "paris-edinburgh": [tizr.name, pyrophyllite.name, zr.name],
    "DAC": [re.name, ss301.name, w.name]
}
gtype_map = {
    "paris-edinburgh": ["encapsulating", "non-encapsulating", "other"],
    "DAC": ["flat"]
}
loadaxis_map = {
    "paris-edinburgh": [[0,1,0], [0,0,1]],
    "DAC": [[0,0,1], [0,1,0]]
}
temp_map = {
    "paris-edinburgh": ["CCR-14", "CCR-21", "CCR-25", "CRYO-04", "PE-CRYO", "None"],
    "DAC": ["CCR-14", "CCR-21", "CCR-25", "CRYO-04", "None"]
}

# choose options according to cell type, using "toroid" and "SXL" in name as a way to separate these
# TODO: weird set ups could create issues?

anvil_dir = jsonAnvilDir
PEAnvilOptions = [f for f in os.listdir(anvil_dir) 
                  if f.startswith("anvil") and "toroid" in f and f.endswith(".json")
                  ]
if not PEAnvilOptions:
    PEAnvilOptions = None
    
DACAnvilOptions = [f for f in os.listdir(anvil_dir) 
                  if f.startswith("anvil") and "SXL" in f and f.endswith(".json")
                  ]
if not DACAnvilOptions:
    DACAnvilOptions = None

anvil_map = {
    "paris-edinburgh": PEAnvilOptions,
    "DAC": DACAnvilOptions
}

model_oac = pn.widgets.Select(name="Model")
gasket_oac = pn.widgets.Select(name="Gasket Material")
gtype_oac = pn.widgets.Select(name="Gasket Type")
loadaxis_oac = pn.widgets.Select(name="Load Axis (Mantid Convention)")
temp_oac = pn.widgets.Select(name="Temperature Control")
oac_comment = pn.widgets.TextAreaInput(name="Comment", placeholder="optional")
oac_manufacturer = pn.widgets.TextInput(name="Manufacturer", placeholder="optional")
anvil_file_oac = pn.widgets.Select(name="Anvil JSON")
oac_file_selector = pn.widgets.Select(name="Load Existing OpposedAnvilCell")
oac_output = pn.pane.JSON(name="OAC JSON", depth=2, theme="light")
save_oac_status = pn.pane.Markdown("")
save_oac_button = pn.widgets.Button(name="Save to Disk", button_type="success")
oac_stringDescriptor = pn.widgets.StaticText(name="String Descriptor",value="")

@pn.depends(oac_type.param.value, watch=True)
def update_oac_fields(tval):
    model_oac.options = model_map_oac[tval]
    model_oac.value = model_oac.options[-1]
    gasket_oac.options = gasket_map[tval]
    gasket_oac.value = gasket_oac.options[0]
    gtype_oac.options = gtype_map[tval]
    gtype_oac.value = gtype_oac.options[0]
    loadaxis_oac.options = loadaxis_map[tval]
    loadaxis_oac.value = loadaxis_oac.options[0]
    temp_oac.options = temp_map[tval]
    temp_oac.value = "None"
    anvil_file_oac.options = anvil_map[tval]
    anvil_file_oac.value = anvil_file_oac.options[-1]

    
    # anvil_dir = jsonAnvilDir
    # if os.path.isdir(anvil_dir):
    #     files = [f for f in os.listdir(anvil_dir) if f.startswith("anvil") and f.endswith(".json")]
    #     anvil_file_oac.options = files
    #     default_file = def_anvil_map.get(tval)
    #     anvil_file_oac.value = default_file if default_file in files else (files[0] if files else None)
    # else:
    #     anvil_file_oac.options = []
    #     anvil_file_oac.value = None

    oac_files = [f for f in jsonOACDir if f.endswith(".json")]
    oac_file_selector.options = ["Select a file..."] + oac_files
    oac_file_selector.value = "Select a file..."

@pn.depends(
    oac_type.param.value,
    model_oac.param.value,
    gasket_oac.param.value,
    gtype_oac.param.value,
    loadaxis_oac.param.value,
    temp_oac.param.value,
    oac_comment.param.value,
    oac_manufacturer.param.value,
    anvil_file_oac.param.value,
    watch=True
)
def update_oac_output(*_):
    try:
        # Ensure a valid anvil file is selected
        if not anvil_file_oac.value or anvil_file_oac.value == "Select a file...":
            oac_output.object = None
            oac_preview.object = {"error": "No anvil JSON selected."}
            return

        # Load the anvil object from JSON
        anvil_dir = jsonAnvilDir
        file_path = os.path.join(anvil_dir, anvil_file_oac.value)
        with open(file_path, "r") as f:
            anv_dict = json.load(f)
        anv_instance = anvil.from_dict(anv_dict)

        # Construct OAC object
        oac = opposedAnvilCell(
            type=oac_type.value,
            model=model_oac.value,
            material="N/A",  # or replace with actual material if needed
            anvils=[anv_instance, anv_instance],
            gasketMaterial=gasket_oac.value,
            gasketType=gtype_oac.value,
            loadAxis=loadaxis_oac.value
        )
        oac.temperatureControl = temp_oac.value
        oac.comment = oac_comment.value
        oac.manufacturer = oac_manufacturer.value

        # Assign the full object for saving
        oac_output.object = oac
        oac_preview.object = oac.to_dict()

    except Exception as e:
        print("OAC preview error:", e)
        traceback.print_exc()
        oac_output.object = None
        oac_preview.object = {"error": str(e)}

#preview of json
oac_preview = pn.pane.JSON(name="OAC JSON Preview", depth=2, theme="light")

update_oac_fields(oac_type.value)
update_oac_output()


#load json
def populate_oac_fields_from_obj(oac_obj):
    # Set widget values from an opposedAnvilCell instance
    oac_type.value = oac_obj.type
    model_oac.value = oac_obj.model
    gasket_oac.value = oac_obj.gasketMaterial
    gtype_oac.value = oac_obj.gasketType
    loadaxis_oac.value = oac_obj.loadAxis
    temp_oac.value = oac_obj.temperatureControl if oac_obj.temperatureControl else "None"
    oac_comment.value = oac_obj.comment
    oac_manufacturer.value = oac_obj.manufacturer

    # Set the anvil file selector to match the loaded anvil if possible
    # (Assumes the anvil JSON file exists and matches stringDescriptor)
    anvil_dir = jsonAnvilDir
    anvil_json_name = f"{oac_obj.anvils[0].stringDescriptor}.json"
    if anvil_json_name in anvil_file_oac.options:
        anvil_file_oac.value = anvil_json_name

@pn.depends(oac_file_selector.param.value, watch=True)
def load_oac_from_file(selected_file):
    if not selected_file or selected_file == "Select a file...":
        return
    directory = jsonOACDir
    file_path = os.path.join(directory, selected_file)
    try:
        with open(file_path, "r") as f:
            oac_dict = json.load(f)
        oac_obj = opposedAnvilCell.from_dict(oac_dict)
        # Populate widgets
        populate_oac_fields_from_obj(oac_obj)
        # Update preview/output
        oac_output.object = oac_obj
        oac_preview.object = oac_obj.to_dict()
        save_oac_status.object = f"✅ Loaded OAC from `{selected_file}`"
    except Exception as e:
        save_oac_status.object = f"❌ Failed to load: {e}"


# Save OAC to disk using the object's .to_dict() and stringDescriptor
def save_oac(event):
    try:
        oac_obj = oac_output.object  # Should be an opposedAnvilCell instance
        if not hasattr(oac_obj, "to_dict") or not callable(oac_obj.to_dict):
            raise ValueError("OAC object is missing a valid `.to_dict()` method.")

        if not hasattr(oac_obj, "stringDescriptor"):
            raise ValueError("OAC object is missing a `stringDescriptor` attribute.")

        json_data = json.dumps(oac_obj.to_dict(), indent=2)
        filename = f"{oac_obj.stringDescriptor}.json"

        directory = jsonOACDir
        if not directory:
            raise ValueError("Please specify a save directory.")

        os.makedirs(directory, exist_ok=True)
        full_path = os.path.join(directory, filename)

        with open(full_path, "w") as f:
            f.write(json_data)

        save_oac_status.object = f"✅ OAC saved to `{full_path}`"
    except Exception as e:
        save_oac_status.object = f"❌ Save failed: {e}"

# Link button to callback
save_oac_button.on_click(save_oac)

# The rest remains the same
# Add the new widgets to the layout:
oac_tab = pn.Column(
    pn.pane.Markdown("## Create an Opposed Anvil Cell"),
    oac_type,
    model_oac,
    gasket_oac,
    gtype_oac,
    loadaxis_oac,
    temp_oac,
    oac_comment,
    oac_manufacturer,
    save_directory,
    anvil_file_oac,
    oac_file_selector,
    save_oac_button,
    save_oac_status,  # <== required for feedback
    oac_preview
)

pn.Tabs(("Opposed Anvil Cell", oac_tab), ("Anvil", anvil_tab)).servable()
