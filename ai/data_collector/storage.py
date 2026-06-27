from pathlib import Path

import duckdb
import pandas as pd

DATABASE = Path("ai/database/market.duckdb")


class MarketStorage:

    def __init__(self):
        DATABASE.parent.mkdir(parents=True, exist_ok=True)
        self.db = duckdb.connect(str(DATABASE))
        self.create()

    def create(self):
        self.db.execute("""
        CREATE TABLE IF NOT EXISTS candles (

            symbol TEXT,
            timeframe TEXT,
            timestamp BIGINT,
            datetime TIMESTAMP,

            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume DOUBLE,

            PRIMARY KEY(symbol, timeframe, timestamp)

        )
        """)

    def last_timestamp(self, symbol: str, timeframe: str):

        return self.db.execute(
            """
            SELECT MAX(timestamp)
            FROM candles
            WHERE symbol = ?
            AND timeframe = ?
            """,
            [symbol, timeframe],
        ).fetchone()[0]

    def save(self, df: pd.DataFrame):

        if df.empty:
            return

        self.db.register("candles_df", df)

        self.db.execute("""
        INSERT OR REPLACE INTO candles
        SELECT *
        FROM candles_df
        """)

    def count(self):

        return self.db.execute(
            "SELECT COUNT(*) FROM candles"
        ).fetchone()[0]
