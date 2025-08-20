#!/usr/bin/env python3
"""
List material names from the SEE sqlite DB configured in src/snapwrap/SEEMeta/db.py

Run from the repo root (so ../src is found), or the script will add ../src to sys.path
so it works when executed from the scripts/ directory.
"""
import os
import sys
from textwrap import shorten

# ensure src is on sys.path when running this script from scripts/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from sqlalchemy import inspect, text
from snapwrap.SEEMeta import db  # uses WrapConfig to build engine

def list_materials():
    engine = db.engine
    inspector = inspect(engine)

    tables = inspector.get_table_names()
    if not tables:
        print("No tables found in DB.")
        return

    candidates = []
    # prefer tables that have a 'name'-like column
    for t in tables:
        cols = [c["name"] for c in inspector.get_columns(t)]
        lower = [c.lower() for c in cols]
        if "name" in lower or "material" in lower or "material_name" in lower:
            candidates.append((t, cols))
    # if no candidate found, fall back to first table
    if not candidates:
        t = tables[0]
        cols = [c["name"] for c in inspector.get_columns(t)]
        candidates = [(t, cols)]

    for table, cols in candidates:
        print(f"\nTable: {table}  (columns: {', '.join(cols)})")
        # choose best column to represent material name
        key_candidates = [c for c in cols if c.lower() in ("name", "material", "material_name")]
        if not key_candidates:
            key_candidates = [cols[0]]  # fallback to first column

        name_col = key_candidates[0]
        query = text(f"SELECT DISTINCT {name_col} FROM {table} ORDER BY {name_col} COLLATE NOCASE")
        try:
            with engine.connect() as conn:
                rows = conn.execute(query).fetchall()
        except Exception as exc:
            print(f"  Failed to query {table}: {exc!r}")
            continue

        if not rows:
            print("  (no rows)")
            continue

        print(f"  Found {len(rows)} distinct values in column '{name_col}':")
        for r in rows:
            val = r[0]
            print("   ", val)

if __name__ == "__main__":
    list_materials()