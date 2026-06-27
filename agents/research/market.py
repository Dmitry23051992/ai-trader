from core.context import Context


class MarketAgent:

    def run(self, ctx: Context) -> Context:

        ctx.log("[Market] Collecting market information...")

        # Пока заглушка
        ctx.market = {
            "trend": "unknown",
            "volatility": "unknown",
            "sentiment": "unknown"
        }

        return ctx
