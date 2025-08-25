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
        print("SEE Override located in {overridePath}")
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
            print(f"Details for material '{material_name}': {material_details}")
            return material_details

    except Exception as e:
        print(f"Error retrieving material details: {e}")
        return {}