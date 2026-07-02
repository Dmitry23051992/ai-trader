from core.context import Context
from ai.trading.journal import TradeJournal
from configs.settings import (
    BASE_POSITION_SIZE_PCT,
    BASE_STOP_LOSS_PCT,
    BASE_TAKE_PROFIT_PCT,
    BASE_TRAILING_STOP_PCT,
    MAX_CONSECUTIVE_LOSSES,
    MAX_DAILY_LOSS_PCT,
    MAX_POSITION_SIZE_PCT,
    MIN_POSITION_SIZE_PCT,
    PAPER_PORTFOLIO_USDT,
)


class RiskAgent:

    def __init__(self, journal: TradeJournal | None = None):
        self.journal = journal or TradeJournal()

    def run(self, ctx: Context) -> Context:

        decision = ctx.decision or {}
        market = ctx.market or {}
        action = decision.get("action", "wait")
        adaptive = self.journal.get_adaptive_params()
        guard = self.journal.risk_guard(
            portfolio_usdt=PAPER_PORTFOLIO_USDT,
            max_daily_loss_pct=MAX_DAILY_LOSS_PCT,
            max_consecutive_losses=MAX_CONSECUTIVE_LOSSES,
        )

        if action == "wait":
            ctx.risk = {
                "enabled": False,
                "action": "wait",
                "position_size_pct": 0.0,
                "stop_loss_pct": 0.0,
                "take_profit_pct": 0.0,
                "trailing_stop_pct": 0.0,
                "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
                "max_consecutive_losses": MAX_CONSECUTIVE_LOSSES,
                "guard": guard,
                "reason": "No trade edge detected.",
            }

            ctx.log("[Risk] Skipped: no trade planned.")
            return ctx

        if guard.get("blocked", False):
            ctx.risk = {
                "enabled": False,
                "blocked": True,
                "action": "wait",
                "requested_action": action,
                "position_size_pct": 0.0,
                "stop_loss_pct": 0.0,
                "take_profit_pct": 0.0,
                "trailing_stop_pct": 0.0,
                "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
                "max_consecutive_losses": MAX_CONSECUTIVE_LOSSES,
                "guard": guard,
                "reason": guard.get("reason", "Risk guard blocked trading."),
            }
            ctx.log(f"[Risk] Blocked: {ctx.risk['reason']}")
            return ctx

        confidence = float(decision.get("confidence", 0.0) or 0.0)
        volatility = market.get("volatility", "moderate")
        regime = market.get("regime", "ranging")

        confidence_boost = max(0.0, confidence - 0.5) * 4.0
        position_size = BASE_POSITION_SIZE_PCT + confidence_boost

        if regime == "trending":
            position_size += 0.5
        elif regime == "choppy":
            position_size -= 0.5

        if volatility == "high":
            position_size -= 0.75
        elif volatility == "low":
            position_size += 0.25

        position_size *= float(adaptive.get("position_size_multiplier", 1.0) or 1.0)

        position_size = max(MIN_POSITION_SIZE_PCT, min(position_size, MAX_POSITION_SIZE_PCT))

        stop_loss_pct = BASE_STOP_LOSS_PCT
        take_profit_pct = BASE_TAKE_PROFIT_PCT
        trailing_stop_pct = BASE_TRAILING_STOP_PCT

        if volatility == "high":
            stop_loss_pct += 0.75
            take_profit_pct += 1.0
        elif volatility == "low":
            stop_loss_pct -= 0.25
            take_profit_pct -= 0.25

        if regime == "trending":
            take_profit_pct += 0.5
        elif regime == "choppy":
            stop_loss_pct -= 0.25

        stop_loss_pct *= float(adaptive.get("stop_loss_multiplier", 1.0) or 1.0)
        take_profit_pct *= float(adaptive.get("take_profit_multiplier", 1.0) or 1.0)

        stop_loss_pct = max(0.5, round(stop_loss_pct, 2))
        take_profit_pct = max(0.75, round(take_profit_pct, 2))
        trailing_stop_pct = max(0.25, round(trailing_stop_pct, 2))

        ctx.risk = {
            "enabled": True,
            "action": action,
            "position_size_pct": round(position_size, 2),
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
            "trailing_stop_pct": trailing_stop_pct,
            "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
            "max_consecutive_losses": MAX_CONSECUTIVE_LOSSES,
            "guard": guard,
            "adaptive_params": adaptive,
            "reason": self._reason(action, volatility, regime, confidence),
        }

        ctx.log(
            f"[Risk] action={action} size={ctx.risk['position_size_pct']}% "
            f"sl={stop_loss_pct}% tp={take_profit_pct}% tsl={trailing_stop_pct}%"
        )

        return ctx

    def _reason(self, action: str, volatility: str, regime: str, confidence: float) -> str:
        parts = [f"Action={action}", f"volatility={volatility}", f"regime={regime}", f"confidence={round(confidence, 3)}"]
        return ", ".join(parts)