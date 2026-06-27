#!/bin/bash

cd ~/ai-trader/freqtrade || exit 1

docker compose run --rm freqtrade backtesting \
    --config user_data/config.json \
    --strategy "$1"
