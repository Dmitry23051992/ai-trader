#!/bin/sh
# Проверяет, запущен ли контейнер freqtrade, и перезапускает если нет
if ! docker ps --filter name=freqtrade --format "{{.Names}}" | grep -q freqtrade; then
    cd /home/user/ai-trader/freqtrade && docker compose up -d freqtrade
fi
