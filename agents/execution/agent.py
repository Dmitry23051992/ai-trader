from core.context import Context

from ai.trading.journal import TradeJournal

from .binance_adapter import BinanceExecutionAdapter


class ExecutionAgent:

    def __init__(self, adapter: BinanceExecutionAdapter | None = None, journal: TradeJournal | None = None):
        self.adapter = adapter or BinanceExecutionAdapter()
        self.journal = journal or TradeJournal()

    def run(self, ctx: Context) -> Context:

        decision = ctx.decision or {}
        risk = ctx.risk or {}
        action = decision.get("action", "wait")

        if risk.get("blocked", False) or not risk.get("enabled", True):
            ctx.execution = {
                "mode": self.adapter.execution_mode,
                "status": "skipped_risk_guard",
                "action": action,
                "reason": str(risk.get("reason", "Risk guard blocked trading.")),
                "journaled": False,
            }
            ctx.log(f"[Execution] Skipped by risk guard: {ctx.execution['reason']}")
            return ctx

        if action == "wait":
            ctx.execution = {
                "mode": self.adapter.execution_mode,
                "status": "skipped",
                "action": "wait",
                "reason": "Decision engine selected wait.",
                "journaled": False,
            }
            ctx.log("[Execution] Skipped: no trade planned.")
            return ctx

        try:
            intent = self.adapter.plan_execution(ctx)
            execution = self._preflight_execution(ctx, intent.as_dict())

            if execution is None:
                execution = self.adapter.execute_intent(intent)

            self.journal.record(ctx, execution)

            if execution["status"] in {"paper_executed", "live_executed"}:
                if execution.get("side") == "buy":
                    opened = self.journal.upsert_open_position(ctx, execution)
                    execution["position_state"] = "opened"
                    execution["open_position"] = opened
                elif execution.get("side") == "sell":
                    outcome = self.journal.close_open_position(ctx, execution)
                    if outcome:
                        self.journal.record_outcome(ctx, outcome)
                        execution["position_state"] = "closed"
                        execution["closed_outcome"] = outcome
                    else:
                        execution["position_state"] = "no_open_position"

            execution["journaled"] = True
            ctx.execution = execution

            ctx.log(
                f"[Execution] mode={execution['mode']} status={execution['status']} "
                f"symbol={execution['symbol']} side={execution['side']} "
                f"amount={execution['amount']}"
            )

        except Exception as e:
            ctx.execution = {
                "mode": self.adapter.execution_mode,
                "status": "failed",
                "action": action,
                "reason": str(e),
                "journaled": False,
            }
            ctx.log(f"[Execution] ERROR: {e}")

        return ctx

    def _preflight_execution(self, ctx: Context, intent: dict) -> dict | None:
        symbol = str(intent.get("symbol", ""))
        mode = str(intent.get("mode", "paper"))
        side = str(intent.get("side", ""))
        open_position = self.journal.get_open_position(symbol, mode)

        if side == "buy" and open_position:
            intent["status"] = "skipped_open_position"
            intent["reason"] = f"Open position already exists for {symbol} in {mode} mode."
            intent["payload"] = {"open_position": open_position}
            return intent

        if side == "sell" and not open_position:
            intent["status"] = "skipped_no_position"
            intent["reason"] = f"No open position to close for {symbol} in {mode} mode."
            return intent

        return None