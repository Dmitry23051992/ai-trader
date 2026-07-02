from __future__ import annotations

from typing import Any

from core.context import Context
from core.logger import log

from ai.learning.predictor import AdaptivePredictor
from ai.trading.backtest_parser import BacktestReportParser
from ai.trading.journal import TradeJournal
from configs.settings import (
    ADAPTIVE_MAX_CONFIDENCE_THRESHOLD,
    ADAPTIVE_MAX_POSITION_SIZE_MULTIPLIER,
    ADAPTIVE_MIN_CLOSED_TRADES,
    ADAPTIVE_MIN_CONFIDENCE_THRESHOLD,
    ADAPTIVE_MIN_POSITION_SIZE_MULTIPLIER,
    DECISION_CONFIDENCE_THRESHOLD,
)
from ai.bot.parameter_provider import AIParameterProvider


class LearningAgent:

    def __init__(
        self,
        journal: TradeJournal | None = None,
        backtest_parser: BacktestReportParser | None = None,
        ml_predictor: AdaptivePredictor | None = None,
    ):
        self.journal = journal or TradeJournal()
        self.backtest_parser = backtest_parser or BacktestReportParser()
        self.ml_predictor = ml_predictor or AdaptivePredictor()

    def run(self, ctx: Context) -> Context:
        outcome_summary = self.journal.performance_summary(limit=50)
        recent_outcomes = self.journal.recent_outcomes(limit=10)

        # ── ML-based adaptive params (with rule-based fallback) ──────────
        if self.ml_predictor.is_trained() and ctx.market:
            ml_params = self.ml_predictor.predict(ctx.market)
            adaptive_params = self._blend_ml_with_rules(ml_params, outcome_summary)
            ctx.log("[Learning] Using ML-predicted adaptive params.")
        else:
            adaptive_params = self._build_adaptive_params(outcome_summary)
            ctx.log("[Learning] Using rule-based adaptive params (ML not ready).")

        # Collect a training sample from this iteration for future model updates
        self._collect_training_sample(ctx, adaptive_params)

        # Try batch training from cache when we have enough samples
        if not self.ml_predictor.is_trained():
            train_result = self.ml_predictor.batch_train_from_cache(min_samples=10)
            if train_result.get("trained"):
                ctx.log("[Learning] ML model trained from cache on {} samples.", train_result.get("n"))

        backtest_summary = self.backtest_parser.parse(
            ctx.backtest.get("report", ""),
            strategy_name=ctx.strategy.get("name", ""),
        )
        self.journal.save_adaptive_params(adaptive_params)

        # ── Export adaptive params to ai_params.json for live bot ───
        try:
            provider = AIParameterProvider()
            bot_params = {
                "stoploss": -0.025 * adaptive_params.get("stop_loss_multiplier", 1.0),
                "position_size_pct": min(
                    adaptive_params.get("position_size_multiplier", 1.0), 1.0
                ),
                "market_regime": str(ctx.market.get("bias", "neutral"))
                    if ctx.market else "neutral",
                "confidence_threshold": adaptive_params.get(
                    "decision_confidence_threshold", 0.65
                ),
            }
            provider.save(bot_params)
        except Exception as exc:
            log.warning("Failed to export AI params to bot: {}", exc)

        if ctx.strategy.get("skipped", False):
            ctx.log("[Learning] Strategy generation skipped by decision engine.")

            ctx.learning = self._build_learning_state(
                ctx=ctx,
                mode="wait",
                status="skipped",
                summary=outcome_summary,
                recent_outcomes=recent_outcomes,
                adaptive_params=adaptive_params,
                backtest_summary=backtest_summary,
            )

            ctx.report = self._compose_report(ctx.learning)
            return ctx

        if ctx.backtest["returncode"] != 0:

            ctx.log("[Learning] Backtest failed.")

            print(ctx.backtest["stderr"])

            ctx.learning = self._build_learning_state(
                ctx=ctx,
                mode="backtest_failed",
                status="failed",
                summary=outcome_summary,
                recent_outcomes=recent_outcomes,
                adaptive_params=adaptive_params,
                backtest_summary=backtest_summary,
                note=ctx.backtest.get("stderr", "")[:1500],
            )

            ctx.report = self._compose_report(ctx.learning)
            return ctx

        ctx.log("[Learning] Backtest completed.")

        print(ctx.backtest["stdout"])

        ctx.learning = self._build_learning_state(
            ctx=ctx,
            mode="backtest_success",
            status="success",
            summary=outcome_summary,
            recent_outcomes=recent_outcomes,
            adaptive_params=adaptive_params,
            backtest_summary=backtest_summary,
            note=ctx.backtest.get("stdout", "")[:1500],
        )

        ctx.report = self._compose_report(ctx.learning)
        return ctx

    # ── ML-enhanced methods ─────────────────────────────────────────

    def _blend_ml_with_rules(
        self, ml_params: dict[str, float], summary: dict
    ) -> dict:
        """Blend ML predictions with rule-based safety constraints."""
        total = int(summary.get("total", 0) or 0)
        winrate = float(summary.get("winrate", 0.0) or 0.0)
        profit_factor = float(summary.get("profit_factor", 0.0) or 0.0)

        # Start with ML prediction
        params: dict[str, Any] = {
            "decision_confidence_threshold": float(
                ml_params.get("confidence_threshold", DECISION_CONFIDENCE_THRESHOLD)
            ),
            "position_size_multiplier": float(
                ml_params.get("position_size_multiplier", 1.0)
            ),
            "stop_loss_multiplier": float(
                ml_params.get("stop_loss_multiplier", 1.0)
            ),
            "take_profit_multiplier": float(
                ml_params.get("take_profit_multiplier", 1.0)
            ),
            "caution_mode": False,
            "based_on_trades": total,
            "winrate": round(winrate, 3),
            "profit_factor": round(profit_factor, 3),
            "reason": "ML prediction with rule-based overlay.",
            "payload": {},
        }

        # ── Rule-based safety overlays ──────────────────────────
        reasons: list[str] = ["ML prediction"]

        if winrate < 0.5 and total >= ADAPTIVE_MIN_CLOSED_TRADES:
            params["position_size_multiplier"] *= 0.85
            params["caution_mode"] = True
            reasons.append("Winrate below target (overlay)")

        if profit_factor < 1.2 and total >= ADAPTIVE_MIN_CLOSED_TRADES:
            params["position_size_multiplier"] *= 0.9
            params["stop_loss_multiplier"] *= 0.95
            params["caution_mode"] = True
            reasons.append("PF below target (overlay)")

        # Clamp within safety bounds
        params["decision_confidence_threshold"] = round(
            max(
                ADAPTIVE_MIN_CONFIDENCE_THRESHOLD,
                min(
                    params["decision_confidence_threshold"],
                    ADAPTIVE_MAX_CONFIDENCE_THRESHOLD,
                ),
            ),
            3,
        )
        params["position_size_multiplier"] = round(
            max(
                ADAPTIVE_MIN_POSITION_SIZE_MULTIPLIER,
                min(
                    params["position_size_multiplier"],
                    ADAPTIVE_MAX_POSITION_SIZE_MULTIPLIER,
                ),
            ),
            3,
        )
        params["stop_loss_multiplier"] = round(
            max(0.5, min(float(params["stop_loss_multiplier"]), 1.5)), 3
        )
        params["take_profit_multiplier"] = round(
            max(0.5, min(float(params["take_profit_multiplier"]), 2.0)), 3
        )
        params["reason"] = "; ".join(reasons)
        params["payload"] = {
            "ml_source": ml_params.get("source", "ml"),
            "wins": int(summary.get("wins", 0) or 0),
            "losses": int(summary.get("losses", 0) or 0),
        }
        return params

    def _collect_training_sample(self, ctx: Context, adaptive_params: dict) -> None:
        """Collect a training sample from the current market + outcome."""
        if not ctx.market:
            return

        # Pick the first state as representative features
        states = ctx.market.get("states", [])
        if not states:
            return
        state = states[0]

        features = {
            "confidence": float(state.get("confidence", 0.0) or 0.0),
            "adx": float(state.get("adx", 20.0) or 20.0),
            "rsi": float(state.get("rsi", 50.0) or 50.0),
            "atr_pct": float(state.get("atr_pct", 1.0) or 1.0),
            "volatility": float(
                {"low": 0.0, "moderate": 0.5, "high": 1.0}.get(
                    str(state.get("volatility", "moderate")).lower(), 0.5
                )
            ),
            "trend": float(
                {"bearish": -1.0, "neutral": 0.0, "bullish": 1.0}.get(
                    str(state.get("trend", "neutral")).lower(), 0.0
                )
            ),
            "regime": float(
                {"choppy": 0.0, "ranging": 0.5, "trending": 1.0}.get(
                    str(state.get("regime", "ranging")).lower(), 0.5
                )
            ),
        }

        # Target: the actual adaptive params used (they reflect what worked)
        targets = {
            "position_size_multiplier": float(
                adaptive_params.get("position_size_multiplier", 1.0)
            ),
            "stop_loss_multiplier": float(
                adaptive_params.get("stop_loss_multiplier", 1.0)
            ),
            "take_profit_multiplier": float(
                adaptive_params.get("take_profit_multiplier", 1.0)
            ),
            "confidence_threshold": float(
                adaptive_params.get("decision_confidence_threshold", 0.65)
            ),
        }

        self.ml_predictor.add_sample(features, targets)

    def _build_learning_state(
        self,
        ctx: Context,
        mode: str,
        status: str,
        summary: dict,
        recent_outcomes: list[dict],
        adaptive_params: dict,
        backtest_summary: dict,
        note: str = "",
    ) -> dict:
        suggestions = self._suggest_improvements(ctx, summary, recent_outcomes, backtest_summary)
        return {
            "mode": mode,
            "status": status,
            "trade_summary": summary,
            "recent_outcomes": recent_outcomes,
            "adaptive_params": adaptive_params,
            "backtest_summary": backtest_summary,
            "suggestions": suggestions,
            "note": note,
        }

    def _build_adaptive_params(self, summary: dict) -> dict:
        total = int(summary.get("total", 0) or 0)
        winrate = float(summary.get("winrate", 0.0) or 0.0)
        profit_factor = float(summary.get("profit_factor", 0.0) or 0.0)

        params = {
            "decision_confidence_threshold": DECISION_CONFIDENCE_THRESHOLD,
            "position_size_multiplier": 1.0,
            "stop_loss_multiplier": 1.0,
            "take_profit_multiplier": 1.0,
            "caution_mode": False,
            "based_on_trades": total,
            "winrate": round(winrate, 3),
            "profit_factor": round(profit_factor, 3),
            "reason": "Insufficient closed trades for adaptive tuning.",
            "payload": {},
        }

        if total < ADAPTIVE_MIN_CLOSED_TRADES:
            return params

        reasons: list[str] = []

        if winrate < 0.5:
            params["decision_confidence_threshold"] += 0.05
            params["position_size_multiplier"] *= 0.85
            params["caution_mode"] = True
            reasons.append("Winrate below target")
        elif winrate > 0.6 and profit_factor >= 1.5:
            params["decision_confidence_threshold"] -= 0.03
            params["position_size_multiplier"] *= 1.1
            reasons.append("Winrate and PF are strong")

        if profit_factor < 1.2:
            params["position_size_multiplier"] *= 0.85
            params["stop_loss_multiplier"] *= 0.9
            params["take_profit_multiplier"] *= 0.95
            params["caution_mode"] = True
            reasons.append("Profit factor below target")
        elif profit_factor > 1.8:
            params["take_profit_multiplier"] *= 1.05
            reasons.append("Profit factor supports wider targets")

        params["decision_confidence_threshold"] = round(
            max(
                ADAPTIVE_MIN_CONFIDENCE_THRESHOLD,
                min(params["decision_confidence_threshold"], ADAPTIVE_MAX_CONFIDENCE_THRESHOLD),
            ),
            3,
        )
        params["position_size_multiplier"] = round(
            max(
                ADAPTIVE_MIN_POSITION_SIZE_MULTIPLIER,
                min(params["position_size_multiplier"], ADAPTIVE_MAX_POSITION_SIZE_MULTIPLIER),
            ),
            3,
        )
        params["stop_loss_multiplier"] = round(float(params["stop_loss_multiplier"]), 3)
        params["take_profit_multiplier"] = round(float(params["take_profit_multiplier"]), 3)
        params["reason"] = "; ".join(reasons) if reasons else "Performance is stable. Keep baseline thresholds."
        params["payload"] = {
            "wins": int(summary.get("wins", 0) or 0),
            "losses": int(summary.get("losses", 0) or 0),
            "gross_profit_usdt": float(summary.get("gross_profit_usdt", 0.0) or 0.0),
            "gross_loss_usdt": float(summary.get("gross_loss_usdt", 0.0) or 0.0),
        }
        return params

    def _suggest_improvements(
        self,
        ctx: Context,
        summary: dict,
        recent_outcomes: list[dict],
        backtest_summary: dict,
    ) -> list[str]:
        suggestions: list[str] = []

        winrate = float(summary.get("winrate", 0.0) or 0.0)
        profit_factor = float(summary.get("profit_factor", 0.0) or 0.0)
        avg_pnl_pct = float(summary.get("avg_pnl_pct", 0.0) or 0.0)
        avg_loss_pct = float(summary.get("avg_loss_pct", 0.0) or 0.0)

        if summary.get("total", 0) == 0:
            suggestions.append("No closed trades yet. Keep collecting outcomes before changing strategy rules.")
            return suggestions

        if winrate < 0.5:
            suggestions.append("Winrate is weak. Tighten market filters and trade only in stronger trend regimes.")

        if profit_factor < 1.2 and summary.get("losses", 0) > 0:
            suggestions.append("Profit factor is weak. Reduce position size and improve stop-loss logic in choppy markets.")

        if avg_loss_pct < -1.0:
            suggestions.append("Average loss is too large. Use tighter stops or avoid entries during high volatility.")

        if avg_pnl_pct <= 0:
            suggestions.append("Average trade is not profitable. Review entry timing and require stronger confirmation before buy.")

        if recent_outcomes:
            last = recent_outcomes[0]
            if not bool(last.get("was_win", False)):
                suggestions.append(
                    f"Last trade lost. Inspect {last.get('symbol', 'unknown')} in regime={last.get('regime', 'n/a')} and volatility={last.get('volatility', 'n/a')}."
                )

        if ctx.market.get("trade_mode") == "wait":
            suggestions.append("Wait mode is healthy. Do not force trades when there is no edge.")

        if backtest_summary.get("status") == "parsed":
            backtest_trades = int(backtest_summary.get("total_trades", 0) or 0)
            backtest_drawdown = float(backtest_summary.get("max_drawdown_pct", 0.0) or 0.0)
            backtest_profit_factor = float(backtest_summary.get("profit_factor", 0.0) or 0.0)

            if backtest_trades < 20:
                suggestions.append("Backtest sample is small. Increase timerange or pair coverage before trusting the edge.")

            if backtest_drawdown > 10.0:
                suggestions.append("Backtest drawdown is elevated. Tighten risk or add stronger exit protections before scaling risk.")

            if backtest_profit_factor and backtest_profit_factor < 1.2:
                suggestions.append("Backtest profit factor is weak. Rework exits and avoid low-quality entries.")

            top_exit_reasons = backtest_summary.get("top_exit_reasons", [])
            if "stop_loss" in top_exit_reasons:
                suggestions.append("Stop-loss exits dominate the backtest. Review entry timing and reduce exposure in unstable regimes.")

        if not suggestions:
            suggestions.append("Current approach is working. Keep the same filters and collect more data before expanding risk.")

        return suggestions

    def _compose_report(self, learning_state: dict) -> str:
        summary = learning_state.get("trade_summary", {})
        backtest = learning_state.get("backtest_summary", {})
        suggestions = learning_state.get("suggestions", [])

        lines = [
            f"Mode: {learning_state.get('mode', 'n/a')}",
            f"Status: {learning_state.get('status', 'n/a')}",
            f"Trades: {summary.get('total', 0)}",
            f"Winrate: {summary.get('winrate', 0.0)}",
            f"Profit Factor: {summary.get('profit_factor', 0.0)}",
            f"Total PnL USDT: {summary.get('total_pnl_usdt', 0.0)}",
            f"Avg PnL %: {summary.get('avg_pnl_pct', 0.0)}",
            f"Adaptive Threshold: {learning_state.get('adaptive_params', {}).get('decision_confidence_threshold', DECISION_CONFIDENCE_THRESHOLD)}",
            f"Adaptive Size Multiplier: {learning_state.get('adaptive_params', {}).get('position_size_multiplier', 1.0)}",
            f"Backtest Parsed: {backtest.get('status', 'missing')}",
            "Suggestions:",
        ]

        if backtest.get("status") == "parsed":
            lines[7:7] = [
                f"Backtest Trades: {backtest.get('total_trades', 0)}",
                f"Backtest PF: {backtest.get('profit_factor', 0.0)}",
                f"Backtest DD %: {backtest.get('max_drawdown_pct', 0.0)}",
                f"Backtest Profit %: {backtest.get('total_profit_pct', 0.0)}",
            ]

        for suggestion in suggestions:
            lines.append(f"- {suggestion}")

        note = learning_state.get("note", "")
        if note:
            lines.extend(["Note:", note[:1500]])

        return "\n".join(lines)

    def export_ai_params(self, ctx: Context) -> dict:
        """Export the current AI parameters to a JSON file."""
        params = {
            "decision_confidence_threshold": ctx.learning.get("adaptive_params", {}).get("decision_confidence_threshold", DECISION_CONFIDENCE_THRESHOLD),
            "position_size_multiplier": ctx.learning.get("adaptive_params", {}).get("position_size_multiplier", 1.0),
            "stop_loss_multiplier": ctx.learning.get("adaptive_params", {}).get("stop_loss_multiplier", 1.0),
            "take_profit_multiplier": ctx.learning.get("adaptive_params", {}).get("take_profit_multiplier", 1.0),
            "caution_mode": ctx.learning.get("adaptive_params", {}).get("caution_mode", False),
            "based_on_trades": ctx.learning.get("adaptive_params", {}).get("based_on_trades", 0),
            "winrate": ctx.learning.get("adaptive_params", {}).get("winrate", 0.0),
            "profit_factor": ctx.learning.get("adaptive_params", {}).get("profit_factor", 0.0),
            "reason": ctx.learning.get("adaptive_params", {}).get("reason", "Insufficient closed trades for adaptive tuning."),
            "payload": ctx.learning.get("adaptive_params", {}).get("payload", {}),
        }
        return params
