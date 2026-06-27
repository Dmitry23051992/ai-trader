import duckdb
import pandas as pd

from ai.features.indicators import add_indicators


DB = "ai/database/market.duckdb"


def build():

    db = duckdb.connect(DB)

    df = db.sql("""
        SELECT *
        FROM candles
        ORDER BY symbol, timeframe, timestamp
    """).df()

    print(f"Loaded {len(df)} candles")

    result = []

    for (symbol, timeframe), group in df.groupby(["symbol", "timeframe"]):

        print(f"Processing {symbol} {timeframe}")

        group = group.copy()

        group = add_indicators(group)

        result.append(group)

    df = pd.concat(result)

    db.register("features_df", df)

    db.execute("""
        CREATE OR REPLACE TABLE features AS
        SELECT *
        FROM features_df
    """)

    print("Features saved.")


if __name__ == "__main__":
    build()
