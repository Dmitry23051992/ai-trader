"""Tests for agents.risk.agent.RiskAgent."""

from unittest.mock import MagicMock

import pytest

from agents.risk.agent import RiskAgent
from core.context import Context


class TestRiskAgent:
    def test_wait_action_skips_risk(self, ctx):
        """When decision is 'wait', risk should be disabled."""
        ctx.decision = {"action": "wait", "confidence": 0.4}
        ctx.market = {"volatility": "moderate", "regime": "ranging"}
        agent = RiskAgent()
        ctx = agent.run(ctx)
        assert ctx.risk["enabled"] is False
        assert ctx.risk["action"] == "wait"
        assert ctx.risk["position_size_pct"] == 0.0

    def test_buy_action_creates_risk_params(self, sample_decision_buy):
        """When decision is 'buy', risk params should be calculated."""
        agent = RiskAgent()
        ctx = agent.run(sample_decision_buy)
        assert ctx.risk["enabled"] is True
        assert ctx.risk["action"] == "buy"
        assert ctx.risk["position_size_pct"] > 0
        assert ctx.risk["stop_loss_pct"] > 0
        assert ctx.risk["take_profit_pct"] > 0

    def test_risk_guard_blocks_trading(self, ctx):
        """When risk guard blocks, risk should be disabled with reason."""
        journal = MagicMock()
        journal.get_adaptive_params.return_value = {}
        journal.risk_guard.return_value = {
            "blocked": True,
            "reason": "Max daily loss exceeded.",
        }
        ctx.decision = {"action": "buy", "confidence": 0.8}
        ctx.market = {"volatility": "moderate", "regime": "trending"}
        agent = RiskAgent(journal=journal)
        ctx = agent.run(ctx)
        assert ctx.risk["enabled"] is False
        assert ctx.risk["blocked"] is True
        assert "Max daily loss" in ctx.risk["reason"]

    def test_adaptive_params_applied(self, sample_decision_buy):
        """Adaptive position size multiplier should affect final size."""
        journal = MagicMock()
        journal.get_adaptive_params.return_value = {
            "position_size_multiplier": 0.5,
            "stop_loss_multiplier": 1.0,
            "take_profit_multiplier": 1.0,
        }
        journal.risk_guard.return_value = {"blocked": False}

        # First with default multiplier (1.0)
        agent_default = RiskAgent()
        ctx_default = agent_default.run(sample_decision_buy)
        default_size = ctx_default.risk["position_size_pct"]

        # Then with reduced multiplier (0.5)
        agent_adaptive = RiskAgent(journal=journal)
        ctx_adaptive = agent_adaptive.run(sample_decision_buy)
        adaptive_size = ctx_adaptive.risk["position_size_pct"]

        assert adaptive_size < default_size
