from agents.strategy.generator import StrategyGenerator
from core.context import Context


class StrategyAgent:

    def __init__(self):
        self.generator = StrategyGenerator()

    def run(self, ctx: Context):

        decision = ctx.decision or {}
        risk = ctx.risk or {}
        action = decision.get("action", "wait")

        if action == "wait":
            ctx.log("[Strategy] Skipped: decision engine selected wait.")
            ctx.strategy = {
                "name": "",
                "path": "",
                "valid": False,
                "error": "Decision engine selected wait.",
                "skipped": True,
            }
            return ctx

        if action == "explore":
            ctx.log("[Strategy] Bootstrap explore: generating strategy for data collection.")

        strategy_name = f"EMA_RSI_{ctx.iteration:04d}"

        print(f"[Strategy] Generating {strategy_name}")

        try:
            path = self.generator.generate(
                strategy_name,
                self._build_prompt_context(ctx, risk)
            )

            ctx.strategy = {
                "name": strategy_name,
                "path": str(path),
                "valid": False,
                "error": "",
                "skipped": False,
            }

        except Exception as e:
            ctx.log(f"[Strategy] ERROR: {e}")
            ctx.strategy = {
                "name": strategy_name,
                "path": "",
                "valid": False,
                "error": str(e),
                "skipped": False,
            }

        return ctx

    def _build_prompt_context(self, ctx: Context, risk: dict) -> str:
        market = ctx.market or {}
        return (
            f"Market Analysis:\n"
            f"  trade_mode={market.get('trade_mode', '?')}\n"
            f"  bias={market.get('bias', '?')}\n"
            f"  confidence={market.get('confidence', '?')}\n"
            f"  reason={market.get('reason', '?')}\n"
            f"  counts={market.get('counts', {})}\n\n"
            f"Decision:\n{ctx.decision}\n\n"
            f"Risk:\n{risk}\n\n"
            f"Previous Report:\n{getattr(ctx, 'report', '')}\n"
        )
