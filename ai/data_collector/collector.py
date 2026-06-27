from __future__ import annotations

from datetime import datetime
import time

from configs.settings import START_DATE, SYMBOLS, TIMEFRAMES

from .exchange import ExchangeClient
from .storage import CandleStorage


class MarketCollector:

    def __init__(self):

        self.exchange = ExchangeClient()
        self.storage = CandleStorage()

    def collect_symbol(
        self,
        symbol: str,
        timeframe: str,
    ):

        since = self.storage.last_timestamp(symbol, timeframe)

        if since is None:

            since = int(
                datetime.fromisoformat(START_DATE).timestamp() * 1000
            )

            print(f"[{symbol}][{timeframe}] FULL DOWNLOAD")

        else:

            since += 1

            print(f"[{symbol}][{timeframe}] UPDATE")

        inserted = 0

        while True:

            candles = self.exchange.fetch(
                symbol=symbol,
                timeframe=timeframe,
                since=since,
                limit=1000,
            )

            if not candles:
                break

            rows = []

            for c in candles:

                rows.append(
                    (
                        symbol,
                        timeframe,
                        c[0],
                        datetime.utcfromtimestamp(c[0] / 1000),
                        c[1],
                        c[2],
                        c[3],
                        c[4],
                        c[5],
                    )
                )

            self.storage.insert(rows)

            inserted += len(rows)

            print(
                f"[{symbol}][{timeframe}] +{len(rows)} candles (total {inserted})"
            )

            since = candles[-1][0] + 1

            if len(candles) < 1000:
                break

            time.sleep(self.exchange.exchange.rateLimit / 1000)

        print(f"[{symbol}][{timeframe}] DONE")

    def run(self):

        for symbol in SYMBOLS:

            for timeframe in TIMEFRAMES:

                self.collect_symbol(symbol, timeframe)

        print()

        print("Database candles:", self.storage.count())

        self.storage.close()


if __name__ == "__main__":

    MarketCollector().run()
