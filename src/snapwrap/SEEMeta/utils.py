# SEE metadata
import json
import os
from sqlalchemy import create_engine, text
import difflib
import re

import h5py
from mantid.simpleapi import GetIPTS #TODO: this import is soley to access GetIPTS find a more efficient way to do this...

from snapwrap.wrapConfig import WrapConfig
from snapwrap.SEEMeta.material import material
from snapwrap.SEEMeta.db import engine


def SEEJsonLoader(filePath):
    #Loads SEEMeta json file as a dictionary
    
    with open(filePath, "r") as f:
        data = json.load(f)

    return data

def SEEH5Loader(filePath):

    f = h5py.File(filePath,'r')
    try:
        bObject = f.get('entry/DASlogs/BL3:SE:SEEMeta:JSON/value')[0] #bytes object
        data = json.loads(bObject[0].decode("utf-8"))
    except: 
        print("no SEE metadata found in .nxs.h5 file")
        data = None
    return data


def SEEMetaSaver(dict,filePath):
    #save SEEMeta dictionary to file.

    with open(filePath, "w") as f:
        json.dump(dict, f, indent=4)

    print(f"successfully wrote: {filePath}")

def toString(data,compact=True):
    #converts data loaded from file as a dictionary to a string that can be added as a value to a pv
    #optionally can make a compact version with no indentation or whitespace
    
    if compact:
        jsonString = json.dumps(data, separators=(",",":"))
    else:
        jsonString = json.dumps(data, indent=4)

    return jsonString

def acquireMeta(runNumber):
    # This function will acquire SEE metadata by locating json-serialised input from two alternate locations. 
    # The schema is that the software will look for an embedded json inside the .nxs.h5 file. It will also
    # look for an override, which will be stored in:
    # IPTS-{ipts}/shared/SEE/SEE{runNumber}.json
    # If this is found, it will override the content of the embedded json (allowing for post experiment modifications)

    #TODO: confirm that runNumber can be string or int

    iptsPath = GetIPTS(Instrument="SNAP",runNumber=runNumber)
    overridePath = f"{iptsPath}shared/SEE/SEE{str(runNumber).zfill(6)}.json"
    h5Path = f"{iptsPath}nexus/SNAP_{str(runNumber)}.nxs.h5"

    print(f"checking: {overridePath}")
    print(f"checking: {h5Path}")


    #first check if an override is present
    if os.path.isfile(overridePath):
        print(f"SEE Override located in {overridePath}")
        SEEDict = SEEJsonLoader(overridePath)
        return SEEDict
    
    if os.path.isfile(h5Path):
        SEEDict = SEEH5Loader(h5Path)
        return SEEDict
    
    print("No SEE metadata found")
    return None


# SQLite database tools
def link_spectrum_to_material(material_identifier, spectrum_data):
    """
    Adds a spectrum to a material specified by its name or ID.

    Args:
        material_identifier (str|int): The name or ID of the material.
        spectrum_data (dict): A dictionary containing spectrum details (e.g., columns matching the spectra table).
    """
    try:
        # Load the material
        if isinstance(material_identifier, int):
            mat = material(id=material_identifier)
        else:
            mat = material(name=material_identifier)

        # Insert the spectrum into the database
        with engine.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO spectra (
                        material_id, spectrum_type, data_format, file_path,
                        comment, x_axis_name, y_axis_name, y_axis_units
                    )
                    VALUES (
                        :material_id, :spectrum_type, :data_format, :file_path,
                        :comment, :x_axis_name, :y_axis_name, :y_axis_units
                    )
                """),
                {
                    "material_id": mat.get_id(),
                    "spectrum_type": spectrum_data.get("spectrum_type"),
                    "data_format": spectrum_data.get("data_format"),
                    "file_path": spectrum_data.get("file_path"),
                    "comment": spectrum_data.get("comment"),
                    "x_axis_name": spectrum_data.get("x_axis_name"),
                    "y_axis_name": spectrum_data.get("y_axis_name"),
                    "y_axis_units": spectrum_data.get("y_axis_units"),
                }
            )
            conn.commit()
        print(f"Spectrum added to material '{mat.name}' (ID: {mat.get_id()}).")

    except Exception as e:
        print(f"Error adding spectrum: {e}")

def remove_spectrum_from_material(material_identifier, spectrum_id):
    """
    Removes a spectrum from a material specified by its name or ID.

    Args:
        material_identifier (str|int): The name or ID of the material.
        spectrum_name (str): The name of the spectrum to remove.
    """
    try:
        # Load the material
        if isinstance(material_identifier, int):
            mat = material(id=material_identifier)
        else:
            mat = material(name=material_identifier)

        # Delete the spectrum from the database
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    DELETE FROM spectra
                    WHERE material_id = :material_id AND id = :spectrum_id
                """),
                {
                    "material_id": mat.get_id(),
                    "spectrum_id": spectrum_id,
                }
            )
            conn.commit()

        if result.rowcount > 0:
            print(f"Spectrum '{spectrum_id}' removed from material '{mat.name}' (ID: {mat.get_id()}).")
        else:
            print(f"No spectrum named '{spectrum_id}' found for material '{mat.name}' (ID: {mat.get_id()}).")

    except Exception as e:
        print(f"Error removing spectrum: {e}")

def add_column_to_spectra_table(column_name, column_type="TEXT", default_value=None):
    """
    Adds a new column to the spectra table in the database.

    Args:
        column_name (str): The name of the new column to add.
        column_type (str): The SQL data type of the new column (default is "TEXT").
        default_value (any): The default value for the new column (optional).
    """
    with engine.connect() as conn:
        print("Checking existing columns...")
        result = conn.execute(text("PRAGMA table_info(spectra)")).fetchall()
        # Access column names using index 1
        existing_columns = [row[1] for row in result]
        print(f"Existing columns: {existing_columns}")

        if column_name in existing_columns:
            print(f"Column '{column_name}' already exists in the spectra table.")
            return

        print(f"Adding column '{column_name}'...")
        if default_value is not None:
            # Escape the default value properly for inclusion in the SQL string
            default_value_sql = f"'{default_value}'" if isinstance(default_value, str) else str(default_value)
            conn.execute(
                text(f"ALTER TABLE spectra ADD COLUMN {column_name} {column_type} DEFAULT {default_value_sql}")
            )
        else:
            conn.execute(
                text(f"ALTER TABLE spectra ADD COLUMN {column_name} {column_type}")
            )

        print(f"Column '{column_name}' added successfully.")
    

def suggest_similar_materials(material_name):
    """
    Suggest similar material names from the database if the specified material is not found.

    Args:
        material_name (str): The name of the material to check.

    Returns:
        list: A list of similar material names.
    """
    try:
        with engine.connect() as conn:
            # Fetch all material names from the database
            result = conn.execute(text("SELECT name FROM materials")).fetchall()
            material_names = [row[0] for row in result]

        # Normalize case for comparison
        material_name_lower = material_name.lower()
        material_names_lower = [name.lower() for name in material_names]

        # Use difflib to find similar material names
        similar_materials_lower = difflib.get_close_matches(material_name_lower, material_names_lower, n=5, cutoff=0.6)

        # Map back to original case
        similar_materials = [
            material_names[material_names_lower.index(name)]
            for name in similar_materials_lower
        ]

        return similar_materials

    except Exception as e:
        print(f"Error suggesting similar materials: {e}")
        return []

def materialInDatabase(material_name):
    """
    Checks if a material with the specified name exists in the materials database.
    If not, suggests similar material names.

    Args:
        material_name (str): The name of the material to check.

    Returns:
        bool: True if the material exists, False otherwise.
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT COUNT(*) FROM materials WHERE name = :material_name"),
                {"material_name": material_name}
            ).scalar()

        if result > 0:
            return True
        else:
            print(f"Material '{material_name}' not found in the database.")
            similar_materials = suggest_similar_materials(material_name)
            if similar_materials:
                print(f"Did you mean one of these? {', '.join(similar_materials)}")
            else:
                print("No similar material names found.")
            return False

    except Exception as e:
        print(f"Error checking material in database: {e}")
        return False
    
def add_column_to_materials_table(column_name, column_type="TEXT", default_value=None):
    """
    Adds a new column to the materials table in the database.

    Args:
        column_name (str): The name of the new column to add.
        column_type (str): The SQL data type of the new column (default is "TEXT").
        default_value (any): The default value for the new column (optional).
    """
    try:
        with engine.connect() as conn:
            print("Checking existing columns...")
            result = conn.execute(text("PRAGMA table_info(materials)")).fetchall()
            # Access column names using index 1
            existing_columns = [row[1] for row in result]
            print(f"Existing columns: {existing_columns}")

            if column_name in existing_columns:
                print(f"Column '{column_name}' already exists in the materials table.")
                return

            print(f"Adding column '{column_name}'...")
            if default_value is not None:
                # Escape the default value properly for inclusion in the SQL string
                default_value_sql = f"'{default_value}'" if isinstance(default_value, str) else str(default_value)
                conn.execute(
                    text(f"ALTER TABLE materials ADD COLUMN {column_name} {column_type} DEFAULT {default_value_sql}")
                )
            else:
                conn.execute(
                    text(f"ALTER TABLE materials ADD COLUMN {column_name} {column_type}")
                )

            print(f"Column '{column_name}' added successfully.")

    except Exception as e:
        print(f"Error adding column: {e}")

def list_columns_in_table(table_name="materials"):
    """
    Lists all columns in the specified table in the database.

    Args:
        table_name (str): The name of the table to inspect.

    Returns:
        list: A list of column names in the table.
    """
    try:
        with engine.connect() as conn:
            # Use PRAGMA to get table information
            result = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            # Extract column names (index 1 in the result)
            columns = [row[1] for row in result]
            print(f"Columns in table '{table_name}': {columns}")
            return columns
    except Exception as e:
        print(f"Error listing columns in table '{table_name}': {e}")
        return []
    
def update_entry(material_name, column_name, new_value):
    """
    Updates the value of a specific column for a material with the given name.

    Args:
        material_name (str): The name of the material to update.
        column_name (str): The name of the column to update.
        new_value (any): The new value to set for the column.
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(f"""
                    UPDATE materials
                    SET {column_name} = :new_value
                    WHERE name = :material_name
                """),
                {"new_value": new_value, "material_name": material_name}
            )
            conn.commit()

        if result.rowcount > 0:
            print(f"Updated '{column_name}' for material '{material_name}' to {new_value}.")
        else:
            print(f"No material found with name '{material_name}'.")
    except Exception as e:
        print(f"Error updating material: {e}")

def get_material_details(material_name):
    """
    Retrieves all column names and their values for a material with the given name.

    Args:
        material_name (str): The name of the material to retrieve.

    Returns:
        dict: A dictionary of column names and their corresponding values for the material.
    """
    try:
        with engine.connect() as conn:
            # Fetch column names - PRAGMA returns tuples where index 1 is the column name
            column_names = [col[1] for col in conn.execute(text("PRAGMA table_info(materials)")).fetchall()]

            # Fetch the material details
            result = conn.execute(
                text("SELECT * FROM materials WHERE name = :material_name"),
                {"material_name": material_name}
            ).fetchone()

            if result is None:
                print(f"No material found with name '{material_name}'.")
                return {}

            # Convert result to a list if it's not already
            result_list = list(result)
            
            # Map column names to their values
            material_details = dict(zip(column_names, result_list))
            return material_details

    except Exception as e:
        print(f"Error retrieving material details: {e}")
        return {}


def _get_column_info(table_name="materials"):
    """Return a list of (name, type, notnull, default) tuples for the table.

    The ``id`` column (auto-increment primary key) is excluded since the
    database assigns it automatically.
    """
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
    return [(r[1], r[2], bool(r[3]), r[4]) for r in rows if r[1] != "id"]


def add_material_to_database(material_data):
    """
    Adds a new material to the materials table after validating all required properties.

    The function reads the current schema from the database so it adapts
    automatically if columns are added or removed.

    Args:
        material_data (dict): Dictionary of material properties (column → value).

    Returns:
        int: The new material's ID if successful, or None on failure.
    """
    from snapwrap.SEEMeta.component import _validate_chemical_formula

    try:
        col_info = _get_column_info("materials")
        all_columns = [name for name, _, _, _ in col_info]

        # ── missing / empty check (mandatory fields only) ──
        missing = [
            col for col in _MANDATORY_FIELDS
            if col not in material_data or material_data[col] in (None, "")
        ]
        if missing:
            print(f"Missing or empty required fields: {sorted(missing)}")
            return None

        # ── duplicate-name check ──
        name = material_data.get("name")
        if not name:
            print("Material 'name' must be specified.")
            return None
        if materialInDatabase(name):
            print(f"Material with name '{name}' already exists.")
            return None

        # ── chemical formula validation ──
        formula = material_data.get("chemical_formula")
        if formula and not _validate_chemical_formula(str(formula)):
            print(f"Invalid chemical formula: '{formula}'")
            return None

        # ── density sanity check ──
        density = material_data.get("mass_density_g_cm3")
        if density is not None:
            try:
                density = float(density)
            except (ValueError, TypeError):
                print(f"mass_density_g_cm3 must be a number, got '{density}'")
                return None
            if density <= 0:
                print(f"mass_density_g_cm3 must be positive, got {density}")
                return None

        # ── build and execute INSERT ──
        # Only include columns present in the supplied data
        supplied_cols = [c for c in all_columns if c in material_data]
        insert_cols = ", ".join(supplied_cols)
        insert_vals = ", ".join([f":{col}" for col in supplied_cols])
        sql = f"INSERT INTO materials ({insert_cols}) VALUES ({insert_vals})"

        with engine.connect() as conn:
            result = conn.execute(
                text(sql),
                {col: material_data[col] for col in supplied_cols},
            )
            conn.commit()
            new_id = result.lastrowid if hasattr(result, "lastrowid") else None
            if new_id is None:
                new_id = conn.execute(
                    text("SELECT id FROM materials WHERE name = :name"),
                    {"name": name},
                ).scalar()

        print(f"Material '{name}' added with ID {new_id}.")
        return new_id

    except Exception as e:
        print(f"Error adding material: {e}")
        return None


# ---------------------------------------------------------------------------
# PyQt5 dialog — launches inside Mantid Workbench (non-modal to avoid segfault)
# ---------------------------------------------------------------------------

_TYPE_HINTS = {
    "name":               ("str",   "Unique short name, e.g. 'singleCrystalDiamond'"),
    "chemical_formula":   ("str",   "Mantid-style formula, e.g. 'C' or '(Li7)2-C-H4-N-Cl6'"),
    "mass_density_g_cm3": ("float", "Mass density in g/cm³, e.g. 3.51"),
    "data_source":        ("str",   "Where the data came from, e.g. 'NIST'"),
    "isSingleCrystal":    ("bool",  ""),
}

_MANDATORY_FIELDS = {"name", "chemical_formula", "mass_density_g_cm3", "data_source"}

# Module-level reference keeps the dialog alive while it is open.
_active_dialog = None


def _is_bool_column(col_name, col_type):
    """Return True if a column should be treated as a boolean."""
    return col_name == "isSingleCrystal" or col_type.upper() == "BOOLEAN"


def _is_float_column(col_name, col_type):
    """Return True if a column should be treated as a float."""
    upper = col_type.upper()
    return upper in ("REAL", "FLOAT", "DOUBLE", "NUMERIC") or col_name == "mass_density_g_cm3"


def _is_int_column(col_name, col_type):
    """Return True if a column should be treated as an integer."""
    return col_type.upper() in ("INTEGER", "INT")


def _all_material_names():
    """Return a sorted list of all material names in the database."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT name FROM materials ORDER BY name COLLATE NOCASE")
            ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


def _build_material_dialog():
    """Construct the combined edit / create material dialog.

    All Qt imports are deferred so the module can be imported outside of
    Mantid Workbench without error.
    """
    from qtpy.QtWidgets import (  # type: ignore
        QDialog, QFormLayout, QLineEdit, QCheckBox,
        QComboBox, QPushButton, QLabel,
        QVBoxLayout, QHBoxLayout, QGroupBox, QWidget,
        QListWidget, QListWidgetItem, QFileDialog,
    )
    from qtpy.QtCore import Qt, QTimer  # type: ignore
    from snapwrap.SEEMeta.component import _validate_chemical_formula

    spectra_dir = WrapConfig.get("SEE/materials/spectra")

    col_info = _get_column_info("materials")
    if not col_info:
        raise RuntimeError("Could not read materials table schema.")

    # ── state flags ───────────────────────────────────────────────
    # mode: "edit" or "new"
    state = {"mode": "edit", "original_name": None}

    # ── dialog shell ──────────────────────────────────────────────
    dialog = QDialog()
    dialog.setWindowTitle("Material Editor")
    dialog.setMinimumWidth(520)
    dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)

    outer = QVBoxLayout(dialog)

    # ── selector row ──────────────────────────────────────────────
    sel_layout = QHBoxLayout()
    sel_label = QLabel("Material:")
    material_combo = QComboBox()
    material_combo.setMinimumWidth(220)
    btn_new = QPushButton("New Material")
    sel_layout.addWidget(sel_label)
    sel_layout.addWidget(material_combo, 1)
    sel_layout.addWidget(btn_new)
    outer.addLayout(sel_layout)

    # ── mandatory fields group ────────────────────────────────────
    mandatory_group = QGroupBox("Required Properties")
    mandatory_form = QFormLayout()
    mandatory_group.setLayout(mandatory_form)
    outer.addWidget(mandatory_group)

    # ── optional fields group ─────────────────────────────────────
    optional_group = QGroupBox("Optional Properties")
    optional_form = QFormLayout()
    optional_group.setLayout(optional_form)
    outer.addWidget(optional_group)

    # ── build widgets from schema ─────────────────────────────────
    widgets = {}  # col_name -> widget

    for col_name, col_type, _, _ in col_info:
        hint_type, hint_desc = _TYPE_HINTS.get(col_name, (col_type, ""))
        label_text = col_name
        if hint_desc:
            label_text += f"  ({hint_desc})"

        if _is_bool_column(col_name, col_type):
            widget = QCheckBox()
        else:
            widget = QLineEdit()
            widget.setPlaceholderText(hint_desc or hint_type)

        widgets[col_name] = widget

        if col_name in _MANDATORY_FIELDS:
            mandatory_form.addRow(label_text + ":", widget)
        else:
            optional_form.addRow(label_text + ":", widget)

    # ── linked spectra group ──────────────────────────────────────
    spectra_group = QGroupBox("Linked Spectra")
    spectra_vbox = QVBoxLayout()
    spectra_group.setLayout(spectra_vbox)

    spectra_list = QListWidget()
    spectra_list.setSelectionMode(QListWidget.SingleSelection)
    spectra_list.setMaximumHeight(120)
    spectra_vbox.addWidget(spectra_list)

    spectra_btn_layout = QHBoxLayout()
    btn_link_spectrum = QPushButton("Link Spectrum…")
    btn_remove_spectrum = QPushButton("Remove Selected")
    btn_remove_spectrum.setEnabled(False)
    spectra_btn_layout.addStretch()
    spectra_btn_layout.addWidget(btn_link_spectrum)
    spectra_btn_layout.addWidget(btn_remove_spectrum)
    spectra_vbox.addLayout(spectra_btn_layout)

    outer.addWidget(spectra_group)

    # ── status label ──────────────────────────────────────────────
    status_label = QLabel("")
    outer.addWidget(status_label)

    # ── action buttons ────────────────────────────────────────────
    btn_layout = QHBoxLayout()
    btn_apply = QPushButton("Apply")
    btn_close = QPushButton("Close")
    btn_layout.addStretch()
    btn_layout.addWidget(btn_apply)
    btn_layout.addWidget(btn_close)
    outer.addLayout(btn_layout)

    # ── fix tab order (mandatory fields → optional fields → buttons) ──
    ordered_widgets = []
    for col_name, _, _, _ in col_info:
        if col_name in _MANDATORY_FIELDS:
            ordered_widgets.append(widgets[col_name])
    for col_name, _, _, _ in col_info:
        if col_name not in _MANDATORY_FIELDS:
            ordered_widgets.append(widgets[col_name])
    ordered_widgets.extend([btn_apply, btn_close])

    for i in range(len(ordered_widgets) - 1):
        QWidget.setTabOrder(ordered_widgets[i], ordered_widgets[i + 1])

    # ══════════════════════════════════════════════════════════════
    # helpers
    # ══════════════════════════════════════════════════════════════

    def _populate_combo():
        """Refresh the material dropdown."""
        state["_populating"] = True
        material_combo.blockSignals(True)
        material_combo.clear()
        for name in _all_material_names():
            material_combo.addItem(name)
        material_combo.blockSignals(False)
        state["_populating"] = False

    def _set_fields_from_db(mat_name):
        """Load a material from the DB and populate every widget."""
        details = get_material_details(mat_name)
        for col_name, _, _, _ in col_info:
            widget = widgets[col_name]
            val = details.get(col_name, "")
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(val))
            else:
                widget.setText("" if val is None else str(val))
        _refresh_spectra_list(mat_name)

    def _clear_fields():
        """Reset every widget to blank / unchecked."""
        for col_name, _, _, _ in col_info:
            widget = widgets[col_name]
            if isinstance(widget, QCheckBox):
                widget.setChecked(False)
            else:
                widget.clear()
        _refresh_spectra_list(None)

    def _refresh_spectra_list(mat_name):
        """Reload the spectra list widget for the given material."""
        spectra_list.clear()
        btn_remove_spectrum.setEnabled(False)
        if mat_name is None:
            spectra_group.setTitle("Linked Spectra")
            btn_link_spectrum.setEnabled(False)
            return
        btn_link_spectrum.setEnabled(True)
        try:
            mat = material(name=mat_name)
            spectra = mat.get_spectra()
        except Exception:
            spectra = []
        spectra_group.setTitle(f"Linked Spectra ({len(spectra)})")
        for spec in spectra:
            file_path = spec.get("file_path", "")
            spec_type = spec.get("spectrum_type", "")
            spec_id = spec.get("id")
            display = os.path.basename(file_path) if file_path else "(no file)"
            if spec_type:
                display += f"  [{spec_type}]"
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, spec_id)
            item.setToolTip(file_path or "")
            spectra_list.addItem(item)

    def _on_spectra_selection_changed():
        btn_remove_spectrum.setEnabled(spectra_list.currentItem() is not None)

    spectra_list.currentItemChanged.connect(lambda *_: _on_spectra_selection_changed())

    def _on_link_spectrum():
        """Open a file dialog in the spectra directory and link the chosen file."""
        if state["mode"] != "edit" or not state["original_name"]:
            status_label.setText(
                "<span style='color:red'>Save the material first before linking spectra.</span>"
            )
            return
        start_dir = spectra_dir if os.path.isdir(spectra_dir) else ""
        file_path, _ = QFileDialog.getOpenFileName(
            dialog,
            "Select Spectrum File",
            start_dir,
            "Data files (*.dat *.csv *.txt);;All files (*)",
        )
        if not file_path:
            return
        # Build minimal spectrum_data dict
        spectrum_data = {
            "spectrum_type": "experimental",
            "data_format": os.path.splitext(file_path)[1].lstrip(".") or "dat",
            "file_path": file_path,
            "comment": "",
            "x_axis_name": "Wavelength",
            "y_axis_name": "Linear attenuation coefficient",
            "y_axis_units": "mm^-1",
        }
        try:
            link_spectrum_to_material(state["original_name"], spectrum_data)
            _refresh_spectra_list(state["original_name"])
            status_label.setText(
                f"<span style='color:green'>✓ Linked '{os.path.basename(file_path)}'.</span>"
            )
        except Exception as exc:
            status_label.setText(
                f"<span style='color:red'>Failed to link spectrum: {exc}</span>"
            )

    btn_link_spectrum.clicked.connect(_on_link_spectrum)

    def _on_remove_spectrum():
        """Remove the selected spectrum from the database."""
        item = spectra_list.currentItem()
        if item is None:
            return
        spec_id = item.data(Qt.UserRole)
        mat_name = state["original_name"]
        if spec_id is None or not mat_name:
            return
        try:
            remove_spectrum_from_material(mat_name, spec_id)
            _refresh_spectra_list(mat_name)
            status_label.setText(
                "<span style='color:green'>✓ Spectrum removed.</span>"
            )
        except Exception as exc:
            status_label.setText(
                f"<span style='color:red'>Failed to remove spectrum: {exc}</span>"
            )

    btn_remove_spectrum.clicked.connect(_on_remove_spectrum)

    def _set_mode(mode, mat_name=None):
        """Switch between 'edit' and 'new' modes."""
        state["mode"] = mode
        state["original_name"] = mat_name
        if mode == "edit":
            dialog.setWindowTitle("Material Editor — Edit")
            btn_apply.setText("Apply Changes")
            material_combo.setEnabled(True)
            spectra_group.setEnabled(True)
            if "name" in widgets:
                widgets["name"].setReadOnly(True)
        else:
            dialog.setWindowTitle("Material Editor — New")
            btn_apply.setText("Create Material")
            material_combo.setEnabled(False)
            spectra_group.setEnabled(False)
            if "name" in widgets:
                widgets["name"].setReadOnly(False)
        btn_apply.setEnabled(True)
        status_label.setText("")

    # ══════════════════════════════════════════════════════════════
    # signal handlers
    # ══════════════════════════════════════════════════════════════

    def _on_combo_changed(index):
        if state.get("_populating"):
            return
        mat_name = material_combo.currentText()
        if mat_name:
            _set_fields_from_db(mat_name)
            _set_mode("edit", mat_name)

    material_combo.currentIndexChanged.connect(_on_combo_changed)

    def _on_new():
        _clear_fields()
        _set_mode("new")
        if "name" in widgets:
            widgets["name"].setFocus()

    btn_new.clicked.connect(_on_new)

    def _on_close():
        global _active_dialog
        dialog.close()
        _active_dialog = None

    btn_close.clicked.connect(_on_close)

    def _collect_values():
        """Read all widgets, coerce types, return (values_dict, errors_list)."""
        values = {}
        errors = []

        for col_name, col_type, _, _ in col_info:
            widget = widgets[col_name]

            if isinstance(widget, QCheckBox):
                values[col_name] = widget.isChecked()
                continue

            raw = widget.text().strip()

            # mandatory check
            if col_name in _MANDATORY_FIELDS and not raw:
                errors.append(f"'{col_name}' is required.")
                continue

            if not raw:
                values[col_name] = None
                continue

            # type coercion
            if _is_float_column(col_name, col_type):
                try:
                    values[col_name] = float(raw)
                except ValueError:
                    errors.append(f"'{col_name}' must be a number.")
                    continue
            elif _is_int_column(col_name, col_type):
                try:
                    values[col_name] = int(raw)
                except ValueError:
                    errors.append(f"'{col_name}' must be an integer.")
                    continue
            else:
                values[col_name] = raw

        # field-specific validation
        if "chemical_formula" in values and values["chemical_formula"]:
            if not _validate_chemical_formula(str(values["chemical_formula"])):
                errors.append(
                    f"Invalid Mantid chemical formula: '{values['chemical_formula']}'"
                )

        if "mass_density_g_cm3" in values and isinstance(values["mass_density_g_cm3"], (int, float)):
            if values["mass_density_g_cm3"] <= 0:
                errors.append("mass_density_g_cm3 must be a positive number.")

        return values, errors

    def _on_apply():
        values, errors = _collect_values()

        if state["mode"] == "new":
            # duplicate-name check (only for new materials)
            name = values.get("name")
            if name and materialInDatabase(str(name)):
                errors.append(f"A material named '{name}' already exists.")

        if errors:
            status_label.setText(
                "<span style='color:red'>"
                + "<br>".join(f"• {e}" for e in errors)
                + "</span>"
            )
            return

        if state["mode"] == "new":
            # ── create ────────────────────────────────────────────
            new_id = add_material_to_database(values)
            if new_id is not None:
                status_label.setText(
                    f"<span style='color:green'>✓ Material '{values.get('name')}' "
                    f"created (ID {new_id}).</span>"
                )
                # Refresh combo, switch to edit mode for the new entry
                _populate_combo()
                idx = material_combo.findText(values["name"])
                if idx >= 0:
                    material_combo.setCurrentIndex(idx)
                _set_mode("edit", values["name"])
            else:
                status_label.setText(
                    "<span style='color:red'>Insert failed — see terminal.</span>"
                )
        else:
            # ── update ────────────────────────────────────────────
            mat_name = state["original_name"]
            changed = 0
            original = get_material_details(mat_name)
            for col_name in [c for c, _, _, _ in col_info if c != "name"]:
                new_val = values.get(col_name)
                old_val = original.get(col_name)
                # normalise for comparison
                if isinstance(new_val, bool):
                    old_val = bool(old_val)
                if new_val != old_val:
                    update_entry(mat_name, col_name, new_val)
                    changed += 1

            if changed:
                status_label.setText(
                    f"<span style='color:green'>✓ Updated {changed} "
                    f"field(s) for '{mat_name}'.</span>"
                )
            else:
                status_label.setText(
                    "<span style='color:gray'>No changes detected.</span>"
                )

    btn_apply.clicked.connect(_on_apply)

    # ── cleanup on X-button close ─────────────────────────────────
    def _on_destroyed():
        global _active_dialog
        _active_dialog = None

    dialog.destroyed.connect(_on_destroyed)

    # ── initial population (deferred until dialog is shown) ─────────
    def _deferred_init():
        """Populate the combo and load the first material.

        Using QTimer.singleShot(0, ...) pushes this to the next event-loop
        iteration, so the dialog is fully constructed and visible before
        any widget updates occur.  This avoids the SIGSEGV that Mantid
        Workbench triggers when widgets are mutated before the backing
        store is ready.
        """
        _populate_combo()
        if material_combo.count() > 0:
            material_combo.setCurrentIndex(0)
            _set_fields_from_db(material_combo.currentText())
            _set_mode("edit", material_combo.currentText())
        else:
            _set_mode("new")

    QTimer.singleShot(0, _deferred_init)

    return dialog


def add_material_dialog():
    """Open a non-modal PyQt5 dialog to create or edit materials.

    Safe to call from a Mantid Workbench script window.  The script window
    executes Python on a **worker thread**, so all Qt widget creation and
    interaction must happen on the main GUI thread.  We use Mantid's
    ``QAppThreadCall`` to marshal the work there.

    Usage::

        from snapwrap.SEEMeta import utils
        utils.add_material_dialog()
    """
    from mantidqt.utils.qt.qappthreadcall import QAppThreadCall

    def _open():
        global _active_dialog
        if _active_dialog is not None:
            _active_dialog.raise_()
            _active_dialog.activateWindow()
            return

        _active_dialog = _build_material_dialog()
        _active_dialog.show()
        _active_dialog.raise_()
        _active_dialog.activateWindow()

    # blocking=True is safe here because _open() only creates widgets and
    # calls show() (which is non-blocking), so it returns almost instantly.
    # The blocking connection ensures the callable actually executes on the
    # GUI thread before we return.
    QAppThreadCall(_open, blocking=True)()