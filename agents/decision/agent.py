from core.context import Context

from ai.trading.journal import TradeJournal
from configs.settings import DECISION_CONFIDENCE_THRESHOLD


class DecisionAgent:

    def __init__(self, journal: TradeJournal | None = None):
        self.journal = journal or TradeJournal()

    def run(self, ctx: Context) -> Context:

        market = ctx.market or {}
        trade_mode = market.get("trade_mode", "wait")
        bias = market.get("bias", "neutral")
        confidence = float(market.get("confidence", 0.0) or 0.0)
        adaptive = self.journal.get_adaptive_params()
        threshold = float(adaptive.get("decision_confidence_threshold", DECISION_CONFIDENCE_THRESHOLD) or DECISION_CONFIDENCE_THRESHOLD)

        # ── Bootstrap mode: force strategy generation for data collection ──
        if ctx.bootstrap and trade_mode == "wait":
            action = "explore"
            reason = "Bootstrap mode: generating strategy to collect training data."
            ctx.log("[Decision] BOOTSTRAP: forcing strategy generation despite neutral market.")
        elif trade_mode == "trade" and confidence >= threshold:
            action = "buy"
            reason = "Market conditions support an entry."
        elif trade_mode == "protect":
            action = "sell"
            reason = "Market conditions suggest protection or exit."
        else:
            action = "wait"
            reason = "No strong edge detected."

        ctx.decision = {
            "action": action,
            "trade_mode": trade_mode,
            "bias": bias,
            "confidence": round(confidence, 3),
            "confidence_threshold": round(threshold, 3),
            "adaptive_reason": str(adaptive.get("reason", "")),
            "reason": reason,
        }

        ctx.log(
            f"[Decision] action={action} mode={trade_mode} "
            f"bias={bias} confidence={ctx.decision['confidence']} threshold={ctx.decision['confidence_threshold']}"
        )

        return ctx