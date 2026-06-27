from __future__ import annotations

import time

import ccxt

from configs.settings import EXCHANGE


class ExchangeClient:

    def __init__(self):

        exchange_class = getattr(ccxt, EXCHANGE)

        self.exchange = exchange_class(
            {
                "enableRateLimit": True,
            }
        )

        self.exchange.load_markets()

    def fetch(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int = 1000,
        retries: int = 5,
    ):

        last_error = None

        for _ in range(retries):

            try:

                return self.exchange.fetch_ohlcv(
                    symbol=symbol,
                    timeframe=timeframe,
                    since=since,
                    limit=limit,
                )

            except Exception as e:

                last_error = e

                time.sleep(2)

        raise last_error
