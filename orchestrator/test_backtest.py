from backtester import Backtester

bt = Backtester()

result = bt.run("EMA_RSI_v1")

print(result["returncode"])
print(result["stdout"])
print(result["stderr"])
