import json, urllib.request, base64
req = urllib.request.Request("http://localhost:8080/api/v1/balance")
req.add_header("Authorization", "Basic " + base64.b64encode(b"admin:freqtrade123").decode())
d = json.load(urllib.request.urlopen(req))
print("Total:", d.get("total"), "USDT")
print("Starting:", d.get("starting_capital"))
print("Change:", d.get("starting_capital_pct"))
