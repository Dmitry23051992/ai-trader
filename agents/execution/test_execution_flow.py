import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agents.decision.agent import DecisionAgent
from agents.execution.agent import ExecutionAgent
from agents.learning.analyzer import LearningAgent
from agents.risk.agent import RiskAgent
from ai.trading.journal import TradeJournal
from core.context import Context


class StubAdapter:
    execution_mode = "paper"

    def __init__(self, intents):
        self._intents = list(intents)

    def plan_execution(self, ctx):
        return self._intents[0]

    def execute_intent(self, intent):
        self._intents.pop(0)
        payload = intent.as_dict()
        payload["status"] = "paper_executed"
        payload["reason"] = "Stub execution."
        return payload


class ExecutionFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "trades.duckdb"
        self.journal = TradeJournal(self.db_path)

    def tearDown(self):
        self.journal.close()
        self.temp_dir.cleanup()

    def test_buy_then_sell_records_outcome_and_adaptive_params(self):
        from agents.execution.binance_adapter import ExecutionIntent

        buy_intent = ExecutionIntent(
            mode="paper",
            status="planned",
            action="buy",
            symbol="BTC/USDT",
            side="buy",
            amount=0.01,
            price=100.0,
            notional_usdt=1.0,
            position_size_pct=1.0,
            stop_loss_pct=1.5,
            take_profit_pct=3.0,
            trailing_stop_pct=1.0,
        )
        sell_intent = ExecutionIntent(
            mode="paper",
            status="planned",
            action="sell",
            symbol="BTC/USDT",
            side="sell",
            amount=0.01,
            price=90.0,
            notional_usdt=0.9,
            position_size_pct=1.0,
            stop_loss_pct=1.5,
            take_profit_pct=3.0,
            trailing_stop_pct=1.0,
        )

        execution_agent = ExecutionAgent(adapter=StubAdapter([buy_intent, sell_intent]), journal=self.journal)
        decision_agent = DecisionAgent(journal=self.journal)
        risk_agent = RiskAgent(journal=self.journal)
        learning_agent = LearningAgent(journal=self.journal)

        buy_ctx = Context(
            market={"trade_mode": "trade", "bias": "bullish", "confidence": 0.72, "regime": "trending", "volatility": "moderate"},
            decision={"action": "buy", "confidence": 0.72},
            risk={"position_size_pct": 1.0, "stop_loss_pct": 1.5, "take_profit_pct": 3.0, "trailing_stop_pct": 1.0},
            iteration=1,
        )
        execution_agent.run(buy_ctx)

        self.assertEqual(len(self.journal.active_positions()), 1)
        self.assertEqual(self.journal.outcomes_count(), 0)

        sell_ctx = Context(
            market={"trade_mode": "protect", "bias": "bearish", "confidence": 0.68, "regime": "choppy", "volatility": "high"},
            decision={"action": "sell", "confidence": 0.68},
            risk={"position_size_pct": 1.0, "stop_loss_pct": 1.5, "take_profit_pct": 3.0, "trailing_stop_pct": 1.0},
            iteration=2,
        )
        execution_agent.run(sell_ctx)

        self.assertEqual(len(self.journal.active_positions()), 0)
        self.assertEqual(self.journal.outcomes_count(), 1)

        summary = self.journal.performance_summary(limit=10)
        self.assertEqual(summary["losses"], 1)
        self.assertLess(summary["profit_factor"], 1.2)

        for iteration in range(3, 5):
            loss_ctx = Context(
                market={"trade_mode": "trade", "bias": "bullish", "confidence": 0.66, "regime": "trending", "volatility": "moderate"},
                decision={"action": "buy", "confidence": 0.66},
                risk={"position_size_pct": 1.0, "stop_loss_pct": 1.5, "take_profit_pct": 3.0, "trailing_stop_pct": 1.0},
                iteration=iteration,
            )
            self.journal.upsert_open_position(loss_ctx, {"mode": "paper", "symbol": f"ETH/USDT-{iteration}", "amount": 0.01, "price": 100.0, "notional_usdt": 1.0, "stop_loss_pct": 1.5, "take_profit_pct": 3.0, "trailing_stop_pct": 1.0, "reason": "Test entry", "payload": {}})
            outcome = self.journal.close_open_position(loss_ctx, {"mode": "paper", "symbol": f"ETH/USDT-{iteration}", "price": 95.0, "reason": "Test exit"})
            self.journal.record_outcome(loss_ctx, outcome)

        learning_ctx = Context(strategy={"skipped": True}, backtest={"returncode": 0})
        learning_agent.run(learning_ctx)

        adaptive = self.journal.get_adaptive_params()
        self.assertGreater(float(adaptive["decision_confidence_threshold"]), 0.65)
        self.assertLess(float(adaptive["position_size_multiplier"]), 1.0)

        decision_ctx = Context(market={"trade_mode": "trade", "bias": "bullish", "confidence": 0.66})
        decision_agent.run(decision_ctx)
        self.assertEqual(decision_ctx.decision["action"], "wait")

        risk_ctx = Context(
            market={"trade_mode": "trade", "volatility": "moderate", "regime": "trending"},
            decision={"action": "buy", "confidence": 0.8},
        )
        risk_agent.run(risk_ctx)
        self.assertLess(risk_ctx.risk["position_size_pct"], 2.7)

    def test_risk_guard_blocks_new_trade_after_loss_streak_and_daily_drawdown(self):
        from agents.execution.binance_adapter import ExecutionIntent

        execution_agent = ExecutionAgent(
            adapter=StubAdapter([
                ExecutionIntent(
                    mode="paper",
                    status="planned",
                    action="buy",
                    symbol="SOL/USDT",
                    side="buy",
                    amount=0.1,
                    price=100.0,
                    notional_usdt=10.0,
                    position_size_pct=1.0,
                    stop_loss_pct=1.5,
                    take_profit_pct=3.0,
                    trailing_stop_pct=1.0,
                )
            ]),
            journal=self.journal,
        )
        risk_agent = RiskAgent(journal=self.journal)

        now = datetime.now(timezone.utc)
        for index in range(3):
            self.journal.record_outcome(
                Context(iteration=index + 1),
                {
                    "symbol": f"LOSS-{index}",
                    "side": "long",
                    "entry_price": 100.0,
                    "exit_price": 85.0,
                    "amount": 1.0,
                    "fees": 0.0,
                    "pnl_usdt": -15.0,
                    "pnl_pct": -15.0,
                    "was_win": False,
                    "hold_bars": 1,
                    "regime": "choppy",
                    "volatility": "high",
                    "confidence": 0.6,
                    "mistake": "",
                    "lesson": "",
                    "payload": {"recorded_at": now.isoformat()},
                },
            )

        risk_ctx = Context(
            market={"trade_mode": "trade", "volatility": "moderate", "regime": "trending"},
            decision={"action": "buy", "confidence": 0.8},
            iteration=10,
        )
        risk_agent.run(risk_ctx)

        self.assertFalse(risk_ctx.risk["enabled"])
        self.assertTrue(risk_ctx.risk["blocked"])
        self.assertGreaterEqual(risk_ctx.risk["guard"]["consecutive_losses"], 3)
        self.assertGreaterEqual(risk_ctx.risk["guard"]["daily_loss_pct"], 3.0)

        execution_ctx = Context(
            market={"trade_mode": "trade", "volatility": "moderate", "regime": "trending"},
            decision={"action": "buy", "confidence": 0.8},
            risk=risk_ctx.risk,
            iteration=11,
        )
        execution_agent.run(execution_ctx)

        self.assertEqual(execution_ctx.execution["status"], "skipped_risk_guard")


if __name__ == "__main__":
    unittest.main()