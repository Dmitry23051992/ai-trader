from __future__ import annotations

import time
from datetime import datetime

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

        total = 0

        while True:

            candles = self.exchange.fetch_page(
                symbol=symbol,
                timeframe=timeframe,
                since=since,
            )

            if not candles:
                break

rows = []

last_db = self.storage.last_timestamp(symbol, timeframe)

for c in candles:

    if last_db is not None and c[0] <= last_db:
        continue
                rows.append(
                    (
                        symbol,
                        timeframe,
                        candle[0],
                        datetime.utcfromtimestamp(candle[0] / 1000),
                        candle[1],
                        candle[2],
                        candle[3],
                        candle[4],
                        candle[5],
                    )
                )

inserted = self.storage.insert(rows)

total += inserted

print(
    f"[{symbol}][{timeframe}] "
    f"Fetched={len(candles)} "
    f"New={len(rows)} "
    f"Inserted={inserted} "
    f"Total={total}"
)            )

            last_timestamp = candles[-1][0]

            if last_timestamp <= since:
                break

            since = last_timestamp + 1

            if len(candles) < 1000:
                break

            time.sleep(0.2)

        print(f"[{symbol}][{timeframe}] DONE")

    def run(self):

        for symbol in SYMBOLS:

            for timeframe in TIMEFRAMES:

                self.collect_symbol(
                    symbol,
                    timeframe,
                )

        print()
        print("=" * 60)
        print("Database candles:", self.storage.count())
        print("=" * 60)

        self.storage.close()


def main():
    collector = MarketCollector()
    collector.run()


if __name__ == "__main__":
    main()
