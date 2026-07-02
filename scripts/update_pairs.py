#!/usr/bin/env python3
"""Update Freqtrade configs with meme coin pairs."""

import json
import sys

CONFIG_HYPEROPT = "/home/user/ai-trader/freqtrade/user_data/config_hyperopt.json"
CONFIG_LIVE = "/home/user/ai-trader/freqtrade/user_data/config.json"

# BRETT and POPCAT are NOT on Binance, replaced with MEME and PEOPLE
PAIRS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "XRP/USDT",
    "ADA/USDT",
    "DOGE/USDT",
    "SHIB/USDT",
    "PEPE/USDT",
    "BONK/USDT",
    "FLOKI/USDT",
    "WIF/USDT",
    "MEME/USDT",
    "TURBO/USDT",
    "PEOPLE/USDT",
]


def main():
    # Update hyperopt config
    with open(CONFIG_HYPEROPT) as f:
        c = json.load(f)
    c["exchange"]["pair_whitelist"] = PAIRS
    c["pairlists"] = [{"method": "StaticPairList"}]
    with open(CONFIG_HYPEROPT, "w") as f:
        json.dump(c, f, indent=2)
    print(f"✅ {CONFIG_HYPEROPT}: {len(PAIRS)} pairs")

    # Update live config
    with open(CONFIG_LIVE) as f:
        c = json.load(f)
    c["exchange"]["pair_whitelist"] = PAIRS
    c["pairlists"] = [{"method": "StaticPairList"}]
    with open(CONFIG_LIVE, "w") as f:
        json.dump(c, f, indent=2)
    print(f"✅ {CONFIG_LIVE}: {len(PAIRS)} pairs")


if __name__ == "__main__":
    main()
