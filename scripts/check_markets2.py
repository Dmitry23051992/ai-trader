#!/usr/bin/env python3
"""Check available meme coin markets on Binance using Freqtrade's exchange."""
import json
import asyncio
import sys

sys.path.insert(0, "/freqtrade")

from freqtrade.exchange import Binance

async def main():
    config_path = "/freqtrade/user_data/config.json"
    with open(config_path) as f:
        full_config = json.load(f)
    
    ex = Binance(full_config)
    markets = await ex.get_markets()
    
    # Check all our target pairs
    targets = [
        "PEPE/USDT", "BONK/USDT", "FLOKI/USDT", "WIF/USDT", 
        "BRETT/USDT", "POPCAT/USDT", "TURBO/USDT", 
        "MEME/USDT", "PEOPLE/USDT", "LADYS/USDT", "MYRO/USDT",
        "DOGE/USDT", "SHIB/USDT", "USDC/USDT", "SYN/USDT"
    ]
    
    for t in sorted(targets):
        if t in markets:
            info = markets[t]
            print(f"✓ {t}: active={info.get('active', False)}, spot={info.get('spot', False)}")
        else:
            print(f"✗ {t}: NOT FOUND on Binance")
    
    # Also find what USDC and SYN pairs look like
    for p in ["USDC/USDT", "SYN/USDT"]:
        if p in markets:
            info = markets[p]
            print(f"\n{p} details:")
            print(f"  active: {info.get('active')}")
            print(f"  spot: {info.get('spot')}")
            print(f"  limits: {info.get('limits', {})}")

asyncio.run(main())
