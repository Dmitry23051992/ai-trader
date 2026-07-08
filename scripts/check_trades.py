"""Проверка открытых сделок"""
import json, urllib.request, base64

req = urllib.request.Request("http://localhost:8080/api/v1/status")
req.add_header("Authorization", "Basic " + base64.b64encode(b"admin:freqtrade123").decode())
data = json.loads(urllib.request.urlopen(req).read())

print(f"Open trades: {len(data)}/3 slots")
for t in data:
    tid = t["trade_id"]
    pair = t["pair"]
    pct = t.get("profit_pct", 0)
    print(f"  #{tid} {pair}: {pct:+.2f}%")
