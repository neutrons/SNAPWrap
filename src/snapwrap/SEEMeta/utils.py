# SEE metadata
import json
import os
from sqlalchemy import create_engine, text
import re
from snapwrap.wrapConfig import WrapConfig

from snapwrap.SEEMeta.material import material
from snapwrap.SEEMeta.db import engine


def SEEMetaLoader(filePath):
    #Loads SEEMeta json file as a dictionary
    
    with open(filePath, "r") as f:
        data = json.load(f)

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
    

         