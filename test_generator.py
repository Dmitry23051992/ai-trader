from agents.strategy.generator import StrategyGenerator

generator = StrategyGenerator()

path = generator.generate("EMA_RSI_TEST")

print(path)
