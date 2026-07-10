import json, urllib.request, base64
req = urllib.request.Request("http://localhost:8080/api/v1/trades?limit=30")
req.add_header("Authorization", "Basic " + base64.b64encode(b"admin:freqtrade123").decode())
data = json.load(urllib.request.urlopen(req))
trades = data.get("trades", [])
closed = [t for t in trades if not t["is_open"] and t.get("close_profit_abs") is not None]
print("Total trades:", len(trades), "Open:", sum(1 for t in trades if t["is_open"]))
roi = sum((t.get("close_profit_abs") or 0) for t in trades if not t["is_open"] and t.get("exit_reason")=="roi")
sig = sum((t.get("close_profit_abs") or 0) for t in trades if not t["is_open"] and t.get("exit_reason")!="roi")
print("ROI closed:", roi, "Signal closed:", sig, "Total:", roi+sig)
