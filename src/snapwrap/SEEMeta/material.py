from sqlalchemy import  text
from .db import engine #links to external materials database

class material:
    def __init__(self, *, id=None, name=None):
        self.engine = engine

        if id is None and name is None:
            raise ValueError("Must provide either id or name.")

        with engine.connect() as conn:
            if id is not None:
                result = conn.execute(text("SELECT * FROM materials WHERE id = :id"), {"id": id}).fetchone()
            else:
                result = conn.execute(
                    text("SELECT * FROM materials WHERE LOWER(name) = LOWER(:name)"),
                    {"name": name}
                ).fetchone()

            if result is None:
                raise ValueError(f"Material not found for id={id} name={name}")

            # Populate attributes from row
            for key, value in result._mapping.items():
                setattr(self, key, value)

            # gather any spectra associated with this material
            
            self.get_spectra()

    def get_id(self):
        return self.id

    def __repr__(self):
        return f"<Material {self.name} (ID: {self.id})>"

    @classmethod
    def load_all(cls,):
        with engine.connect() as conn:
            result = conn.execute(text("SELECT * FROM materials")).fetchall()
            return [cls(id=row.id) for row in result]
        
    def get_spectra(self):
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT * FROM spectra WHERE material_id = :id
            """), {"id": self.id}).fetchall()

            self.spectra = [dict(row._mapping) for row in result]
            self.hasSpectra = len(self.spectra) > 0

            return self.spectra

