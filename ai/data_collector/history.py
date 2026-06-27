from datetime import datetime
import pandas as pd

from ai.data_collector.collector import ExchangeCollector
from ai.data_collector.storage import MarketStorage
from ai.data_collector.config import SYMBOLS, TIMEFRAMES, LIMIT


class HistoryCollector:

    def __init__(self):

        self.exchange = ExchangeCollector()
        self.storage = MarketStorage()

    def run(self):

        for symbol in SYMBOLS:

            for timeframe in TIMEFRAMES:

                print(f"\n{'=' * 60}")
                print(f"{symbol}  {timeframe}")

                self.update_symbol(symbol, timeframe)

        print("\nDone.")
        print(f"Database contains {self.storage.count():,} candles")

    def update_symbol(self, symbol, timeframe):

        last = self.storage.last_timestamp(symbol, timeframe)

        if last is None:
            print("No history. Downloading full history...")
            since = None
        else:
            print(
                "Last candle:",
                datetime.fromtimestamp(last / 1000)
            )
            since = last + 1

        total = 0

        for candles in self.exchange.fetch_all(
            symbol=symbol,
            timeframe=timeframe,
            since=since,
            limit=LIMIT,
        ):

            df = pd.DataFrame(
                candles,
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

            self.storage.save(df)

            total += len(df)

        print(f"Finished. Saved {total:,} candles.")
