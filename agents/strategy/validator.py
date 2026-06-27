import py_compile
from pathlib import Path

from core.context import Context


class StrategyValidator:

    def run(self, ctx: Context) -> Context:

        strategy_file = ctx.strategy.get("path")

        if not strategy_file:
            ctx.log("[Validator] Strategy path missing.")
            ctx.strategy["valid"] = False
            return ctx

        try:
            py_compile.compile(strategy_file, doraise=True)

            ctx.log("[Validator] Python syntax OK.")

            ctx.strategy["valid"] = True

        except Exception as e:

            ctx.log(f"[Validator] ERROR: {e}")

            ctx.strategy["valid"] = False

        return ctx
