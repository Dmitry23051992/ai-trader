from datetime import datetime, timezone

SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "BNB/USDT",
    "SOL/USDT",
    "XRP/USDT",
    "DOGE/USDT",
    "ADA/USDT",
    "LINK/USDT",
]

TIMEFRAMES = [
    "15m",
    "1h",
    "4h",
]

LIMIT = 1000

# Начинаем качать историю с этой даты
START_DATE = datetime(
    2017,
    1,
    1,
    tzinfo=timezone.utc
)

START_TIMESTAMP = int(
    START_DATE.timestamp() * 1000
)
