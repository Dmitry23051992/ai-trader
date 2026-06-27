#!/bin/bash

set -e

STRATEGY="$1"

cd ~/ai-trader/freqtrade || exit 1

mkdir -p user_data/backtest_results

docker compose run --rm freqtrade backtesting \
    --config user_data/config_backtest.json \
    --strategy "$STRATEGY" \
    --export trades \
    --export-filename "user_data/backtest_results/${STRATEGY}.json"
