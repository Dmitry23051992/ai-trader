from core.context import Context
from ai.market.analyzer import MarketAnalyzer


class MarketAgent:

    def __init__(self):
        self.analyzer = MarketAnalyzer()

    def run(self, ctx: Context) -> Context:

        ctx.log("[Market] Analyzing Binance market data...")

        snapshots = self.analyzer.analyze_universe()
        summary = self.analyzer.summarize(snapshots)

        ctx.market = {
            "exchange": summary.get("states", [{}])[0].get("exchange", "binance")
            if summary.get("states")
            else "binance",
            "trade_mode": summary["trade_mode"],
            "bias": summary["bias"],
            "confidence": summary["confidence"],
            "reason": summary["reason"],
            "counts": summary["counts"],
            "states": summary["states"],
        }

        ctx.log(
            "[Market] "
            f"mode={ctx.market['trade_mode']} "
            f"bias={ctx.market['bias']} "
            f"confidence={ctx.market['confidence']}"
        )

        return ctx
