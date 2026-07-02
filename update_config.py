import json
path = "/home/user/ai-trader/freqtrade/user_data/config.json"
c = json.load(open(path))
c["max_open_trades"] = 10
json.dump(c, open(path, "w"), indent=2)
print("OK -> max_open_trades:", c["max_open_trades"])
