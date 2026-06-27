from __future__ import annotations

import time

import ccxt

from configs.settings import (
    DOWNLOAD_LIMIT,
    EXCHANGE,
    REQUEST_DELAY,
)


class ExchangeClient:

    def __init__(self):

        exchange_class = getattr(ccxt, EXCHANGE)

        self.exchange = exchange_class(
            {
                "enableRateLimit": True,
            }
        )

        self.exchange.load_markets()

    def fetch_page(
        self,
        symbol: str,
        timeframe: str,
        since: int,
    ):

        while True:

            try:

                data = self.exchange.fetch_ohlcv(
                    symbol=symbol,
                    timeframe=timeframe,
                    since=since,
                    limit=DOWNLOAD_LIMIT,
                )

                time.sleep(REQUEST_DELAY)

                return data

            except Exception as e:

                print(e)

                time.sleep(5)
