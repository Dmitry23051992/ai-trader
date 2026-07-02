#!/usr/bin/env python3
"""Check ML model and training data status."""
import json
from pathlib import Path
import joblib
import duckdb

# Check ML model
model_dir = Path("models")
predictor_path = model_dir / "adaptive_model.joblib"
scaler_path = model_dir / "adaptive_scaler.joblib"
meta_path = model_dir / "adaptive_meta.json"
cache_path = model_dir / "training_cache.jsonl"

print("=== ML Model Status ===")
print(f"Model exists: {predictor_path.exists()}")
print(f"Scaler exists: {scaler_path.exists()}")

if predictor_path.exists():
    models = joblib.load(predictor_path)
    print(f"Models: {list(models.keys())}")

if meta_path.exists():
    meta = json.loads(meta_path.read_text())
    print(f"Features: {meta.get('feature_names', [])}")
    print(f"Model keys: {meta.get('model_keys', [])}")

if cache_path.exists():
    cache_lines = cache_path.read_text().strip().splitlines()
    print(f"Training cache: {len(cache_lines)} samples")
else:
    print("Training cache: not found")

# Check trades database
print("\n=== Trades Database ===")
db_path = Path("ai/database/trades.duckdb")
if db_path.exists():
    db = duckdb.connect(str(db_path), read_only=True)
    tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    for t in tables:
        name = t[0]
        count = db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        print(f"  {name}: {count} rows")
    db.close()
else:
    print("  trades.duckdb not found")

# List strategies
print("\n=== Generated Strategies ===")
strategy_dir = Path("freqtrade/user_data/strategies")
for f in sorted(strategy_dir.glob("EMA_RSI_*.py")):
    stat = f.stat()
    print(f"  {f.name} ({stat.st_size} bytes)")
