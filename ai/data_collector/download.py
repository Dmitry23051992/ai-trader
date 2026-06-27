from pathlib import Path

import ccxt
import duckdb
import pandas as pd

DATABASE = Path("ai/database/market.duckdb")


class MarketCollector:

    def __init__(self):
        DATABASE.parent.mkdir(parents=True, exist_ok=True)

        self.db = duckdb.connect(str(DATABASE))

        self.exchange = ccxt.binance({
            "enableRateLimit": True,
        })

        self.create_tables()

    def create_tables(self):

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

        result = self.db.execute(
            """
            SELECT MAX(timestamp)
            FROM candles
            WHERE symbol = ?
              AND timeframe = ?
            """,
            [symbol, timeframe]
        ).fetchone()[0]

        return result

    def download(
        self,
        symbol: str,
        timeframe: str = "15m",
        limit: int = 1000,
    ):

        print(f"\nDownloading {symbol} {timeframe}")

        ohlcv = self.exchange.fetch_ohlcv(
            symbol,
            timeframe=timeframe,
            limit=limit,
        )

        if not ohlcv:
            print("No data received.")
            return

        df = pd.DataFrame(
            ohlcv,
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ],
        )

        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")

        df["symbol"] = symbol
        df["timeframe"] = timeframe

        df = df[
            [
                "symbol",
                "timeframe",
                "timestamp",
                "datetime",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]
        ]

        self.db.register("candles_df", df)

        self.db.execute("""
        INSERT OR REPLACE INTO candles
        SELECT *
        FROM candles_df
        """)

        print(f"Saved {len(df)} candles.")

    def count(self):

        return self.db.execute("""
            SELECT COUNT(*)
            FROM candles
        """).fetchone()[0]


if __name__ == "__main__":

    collector = MarketCollector()

    print(
        "Last timestamp:",
        collector.last_timestamp(
            "BTC/USDT",
            "15m"
        )
    )

    collector.download("BTC/USDT", "15m")

    print(
        f"\nTotal candles in DB: {collector.count():,}"
    )
