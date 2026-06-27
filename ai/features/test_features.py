import duckdb

db = duckdb.connect("ai/database/market.duckdb")

print(
    db.sql("""
    SELECT
        symbol,
        datetime,
        close,
        ema20,
        ema50,
        ema200,
        rsi,
        atr,
        adx
    FROM features
    LIMIT 15
    """)
)
