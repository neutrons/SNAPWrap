import os
from sqlalchemy import create_engine
from snapwrap.wrapConfig import WrapConfig

db_path = WrapConfig.get("SEE/materials/database")
engine = create_engine(f"sqlite:///{os.path.abspath(db_path)}")
