#!/usr/bin/env python3
"""Check available meme coin markets on Binance."""
import asyncio
import json
from freqtrade.exchange import Binance

async def main():
    ex = Binance({
        "name": "binance",
        "key": "",
        "secret": "",
        "ccxt_config": {},
        "ccxt_async_config": {}
    })
    markets = await ex.get_markets()
    targets = ["PEPE", "BONK", "FLOKI", "WIF", "BRETT", "POPCAT", 
               "TURBO", "MEME", "PEOPLE", "LADYS", "MYRO", "DOGE", "SHIB",
               "USDC", "SYN"]
    result = {}
    for m in sorted(markets):
        if m.endswith("/USDT") and any(t in m for t in targets):
            result[m] = markets[m].get("active", False)
    print(json.dumps(result, indent=2))

asyncio.run(main())
