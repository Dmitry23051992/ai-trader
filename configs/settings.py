"""
Global project settings.

Все остальные модули импортируют настройки только отсюда.
"""

from pathlib import Path

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

AI_DIR = PROJECT_ROOT / "ai"

DATA_DIR = PROJECT_ROOT / "data"

DATABASE_DIR = AI_DIR / "database"

DB_PATH = DATABASE_DIR / "market.duckdb"

LOG_DIR = PROJECT_ROOT / "logs"

MODEL_DIR = PROJECT_ROOT / "models"

REPORT_DIR = PROJECT_ROOT / "reports"

# -----------------------------------------------------------------------------
# Exchange
# -----------------------------------------------------------------------------

EXCHANGE = "bybit"

# -----------------------------------------------------------------------------
# Data collection
# -----------------------------------------------------------------------------

START_DATE = "2019-01-01"

DOWNLOAD_LIMIT = 1000

REQUEST_DELAY = 0.2

UPDATE_OVERLAP = 10

# -----------------------------------------------------------------------------
# Trading
# -----------------------------------------------------------------------------

TIMEFRAMES = [
    "5m",
    "15m",
    "1h",
    "4h",
]

SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
]

# -----------------------------------------------------------------------------
# Machine Learning
# -----------------------------------------------------------------------------

RANDOM_SEED = 42

TRAIN_TEST_SPLIT = 0.8

VALIDATION_SPLIT = 0.1
