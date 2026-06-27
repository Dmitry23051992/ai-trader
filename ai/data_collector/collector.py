import time

import ccxt


class ExchangeCollector:

    def __init__(self):

        self.exchange = ccxt.binance({
            "enableRateLimit": True,
            "options": {
                "defaultType": "spot"
            }
        })

    def fetch(
        self,
        symbol,
        timeframe,
        since=None,
        limit=1000
    ):

        while True:

            try:

                return self.exchange.fetch_ohlcv(
                    symbol=symbol,
                    timeframe=timeframe,
                    since=since,
                    limit=limit
                )

            except Exception as e:

                print(e)

                time.sleep(5)

    def fetch_all(
        self,
        symbol,
        timeframe,
        since=None,
        limit=1000
    ):

        total = 0

        while True:

            candles = self.fetch(
                symbol,
                timeframe,
                since,
                limit
            )

            if not candles:

                break

            yield candles

            total += len(candles)

            print(f"Downloaded {total:,} candles")

            if len(candles) < limit:

                break

            since = candles[-1][0] + 1
