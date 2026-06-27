import subprocess
from pathlib import Path

from core.context import Context


class BacktestAgent:

    def run(self, ctx: Context) -> Context:

        strategy = ctx.strategy["name"]

        ctx.log(f"[Backtest] Starting {strategy}")

        result = subprocess.run(
            [
                "./automation/backtest.sh",
                strategy
            ],
            capture_output=True,
            text=True
        )

        report = Path(
            f"freqtrade/user_data/backtest_results/{strategy}.json"
        )

        ctx.backtest = {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "report": str(report),
        }

        if result.returncode == 0:
            ctx.log("[Backtest] Finished successfully.")
        else:
            ctx.log("[Backtest] Failed.")

        return ctx
