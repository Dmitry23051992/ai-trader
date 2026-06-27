from agents.strategy.generator import StrategyGenerator
from core.context import Context


class StrategyAgent:

    def __init__(self):
        self.generator = StrategyGenerator()

    def run(self, ctx: Context):

        strategy_name = f"EMA_RSI_{ctx.iteration:04d}"

        print(f"[Strategy] Generating {strategy_name}")

        path = self.generator.generate(
            strategy_name,
            getattr(ctx, "report", "")
        )

        ctx.strategy = {
            "name": strategy_name,
            "path": str(path),
            "valid": False,
        }

        return ctx
