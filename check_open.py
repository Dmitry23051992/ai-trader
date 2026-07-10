import json, urllib.request, base64
req = urllib.request.Request("http://localhost:8080/api/v1/status")
req.add_header("Authorization", "Basic " + base64.b64encode(b"admin:freqtrade123").decode())
data = json.load(urllib.request.urlopen(req))
open_trades = [t for t in data if isinstance(t, dict) and t.get("is_open")]
print("Open trades:", len(open_trades))
for t in open_trades:
    print(" ", t["pair"], ":", t.get("profit_pct",0), "%")
