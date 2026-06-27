#!/bin/bash

cd ~/ai-trader/freqtrade || exit 1

docker compose run --rm freqtrade list-strategies
