from core.context import Context


class LearningAgent:

    def run(self, ctx: Context) -> Context:

        if ctx.backtest["returncode"] != 0:

            ctx.log("[Learning] Backtest failed.")

            print(ctx.backtest["stderr"])

            return ctx

        ctx.log("[Learning] Backtest completed.")

        print(ctx.backtest["stdout"])

        return ctx
