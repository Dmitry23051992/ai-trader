#!/usr/bin/env python3
"""Check available meme coin markets on Binance using ccxt directly."""
import ccxt

def main():
    ex = ccxt.binance()
    ex.load_markets()
    
    targets = [
        "PEPE/USDT", "BONK/USDT", "FLOKI/USDT", "WIF/USDT", 
        "BRETT/USDT", "POPCAT/USDT", "TURBO/USDT", 
        "MEME/USDT", "PEOPLE/USDT", "LADYS/USDT", "MYRO/USDT",
        "DOGE/USDT", "SHIB/USDT", "USDC/USDT", "SYN/USDT"
    ]
    
    for t in sorted(targets):
        if t in ex.markets:
            info = ex.markets[t]
            print(f"✓ {t}: active={info.get('active', False)}, spot={info.get('spot', True)}")
        else:
            print(f"✗ {t}: NOT FOUND on Binance")

if __name__ == "__main__":
    main()
