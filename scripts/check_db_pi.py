#!/usr/bin/env python3
"""Check DuckDB contents on Raspberry Pi."""
import duckdb
import os

for dbname in ["market.duckdb", "trades.duckdb"]:
    path = f"ai/database/{dbname}"
    if not os.path.exists(path):
        print(f"{dbname}: NOT FOUND")
        continue
    size = os.path.getsize(path)
    print(f"\n=== {dbname} ({size} bytes) ===")
    db = duckdb.connect(path, read_only=True)
    tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    for t in tables:
        name = t[0]
        row_count = db.execute(f'SELECT COUNT(*) as cnt FROM "{name}"').fetchone()[0]
        print(f"  [{name}]: {row_count} rows")
        if row_count > 0:
            if name == "candles":
                print(db.execute(f'SELECT symbol, timeframe, datetime, open, close FROM "{name}" LIMIT 4').fetchdf().to_string())
            else:
                print(db.execute(f'SELECT * FROM "{name}" LIMIT 3').fetchdf().to_string())
    db.close()
