from core.director import Director

from agents.research.market import MarketAgent
from agents.strategy.agent import StrategyAgent
from agents.execution.backtester import BacktestAgent
from agents.learning.analyzer import LearningAgent


director = Director()

director.register(MarketAgent())
director.register(StrategyAgent())
director.register(BacktestAgent())
director.register(LearningAgent())

director.run()
