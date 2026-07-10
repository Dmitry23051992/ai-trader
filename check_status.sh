#!/bin/bash
echo "=== Docker ==="
docker ps --format "table {{.Names}}\t{{.Status}}"
echo ""
echo "=== Balance ==="
python3 /home/user/ai-trader/check_balance.py 2>/dev/null || echo "API not ready"
echo ""
echo "=== Open Trades ==="
python3 /home/user/ai-trader/check_open.py 2>/dev/null || echo "API not ready"
