import json, urllib.request

req = urllib.request.Request("http://localhost:8080/api/v1/trades?limit=15")
req.add_header("Authorization", "Basic YWRtaW46ZnJlcXRyYWRlMTIz")
data = json.loads(urllib.request.urlopen(req).read())
trades = data.get("trades", [])
print(f"History: {len(trades)} trades")
total = 0
for t in trades:
    pct = t.get("profit_pct", 0) or 0
    pabs = t.get("profit_abs", 0) or 0
    reason = t.get("exit_reason", "open")
    status = "OPEN" if t["is_open"] else "CLOSED"
    print(f"  {status} {t['pair']}: {pct:.2f}% ({pabs:+.2f}) | {reason}")
    total += pabs
print(f"\nTotal: {total:+.2f} USDT")
