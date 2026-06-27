from __future__ import annotations

import duckdb

from configs.settings import DB_PATH


class CandleStorage:

    def __init__(self):

        self.db = duckdb.connect(str(DB_PATH))

        self.create()

    def create(self):

        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS candles(

                symbol VARCHAR,

                timeframe VARCHAR,

                timestamp BIGINT,

                datetime TIMESTAMP,

                open DOUBLE,

                high DOUBLE,

                low DOUBLE,

                close DOUBLE,

                volume DOUBLE,

                PRIMARY KEY(symbol,timeframe,timestamp)

            )
            """
        )

    def last_timestamp(self, symbol: str, timeframe: str):

        row = self.db.execute(
            """
            SELECT MAX(timestamp)

            FROM candles

            WHERE symbol=?

            AND timeframe=?
            """,
            [symbol, timeframe],
        ).fetchone()

        return row[0]

    def insert(self, rows):

        self.db.executemany(
            """
            INSERT OR IGNORE INTO candles
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )

    def count(self):

        return self.db.execute(
            "SELECT COUNT(*) FROM candles"
        ).fetchone()[0]

    def close(self):

        self.db.close()
