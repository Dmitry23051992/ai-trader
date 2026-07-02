"""Tests for agents.decision.agent.DecisionAgent."""

from unittest.mock import MagicMock

import pytest

from agents.decision.agent import DecisionAgent
from core.context import Context


class TestDecisionAgent:
    def test_buy_when_high_confidence(self, sample_decision_buy):
        """Should return 'buy' when confidence >= threshold."""
        agent = DecisionAgent()
        ctx = agent.run(sample_decision_buy)
        assert ctx.decision["action"] == "buy"

    def test_sell_when_protect_mode(self, ctx):
        """Should return 'sell' when trade_mode is 'protect'."""
        ctx.market = {
            "trade_mode": "protect",
            "bias": "bearish",
            "confidence": 0.5,
        }
        agent = DecisionAgent()
        ctx = agent.run(ctx)
        assert ctx.decision["action"] == "sell"

    def test_wait_when_low_confidence(self, ctx):
        """Should return 'wait' when confidence is below threshold."""
        ctx.market = {
            "trade_mode": "trade",
            "bias": "bullish",
            "confidence": 0.3,
        }
        agent = DecisionAgent()
        ctx = agent.run(ctx)
        assert ctx.decision["action"] == "wait"

    def test_wait_when_no_market_data(self, ctx):
        """Should return 'wait' when market data is empty."""
        agent = DecisionAgent()
        ctx = agent.run(ctx)
        assert ctx.decision["action"] == "wait"

    def test_adaptive_threshold_used(self, ctx):
        """Should use adaptive threshold from trade journal."""
        journal = MagicMock()
        journal.get_adaptive_params.return_value = {
            "decision_confidence_threshold": 0.8,
            "reason": "Adaptive test",
        }
        ctx.market = {
            "trade_mode": "trade",
            "bias": "bullish",
            "confidence": 0.75,
        }
        agent = DecisionAgent(journal=journal)
        ctx = agent.run(ctx)
        # 0.75 < 0.8 adaptive threshold => wait
        assert ctx.decision["action"] == "wait"
        assert ctx.decision["confidence_threshold"] == 0.8
