import json

json_path = "/home/user/ai-trader/freqtrade/user_data/strategies/AI_AdaptiveStrategy.json"

with open(json_path) as f:
    data = json.load(f)

# Fix ROI — ранний выход вместо 18.7%
data["params"]["roi"] = {
    "0": 0.01,      # 1% сразу
    "40": 0.008,    # 0.8% через 40 мин
    "80": 0.005,    # 0.5% через 80 мин
    "160": 0.002,   # 0.2% через 160 мин
}

# Fix trailing stop — разумные значения
data["params"]["trailing"] = {
    "trailing_stop": True,
    "trailing_stop_positive": 0.008,      # 0.8% трейлинг
    "trailing_stop_positive_offset": 0.025, # активация с 2.5%
    "trailing_only_offset_is_reached": True
}

# Fix stoploss — не -15.8%, а -3.5% как в стратегии
data["params"]["stoploss"]["stoploss"] = -0.035

with open(json_path, "w") as f:
    json.dump(data, f, indent=2)

print("✅ Fixed hyperopt overrides:")
print(f"  ROI: {data['params']['roi']}")
print(f"  Stoploss: {data['params']['stoploss']['stoploss']}")
print(f"  Trailing: {data['params']['trailing']}")
