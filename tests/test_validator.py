"""Tests for agents.strategy.validator.StrategyValidator."""

from core.context import Context
from agents.strategy.validator import StrategyValidator


class TestStrategyValidator:
    def test_skipped_strategy_passes(self, ctx):
        """Validator should skip if strategy generation was skipped."""
        ctx.strategy = {"skipped": True, "valid": False}
        agent = StrategyValidator()
        ctx = agent.run(ctx)
        assert ctx.strategy["valid"] is False

    def test_missing_path_fails(self, ctx):
        """Validator should fail if strategy path is missing."""
        ctx.strategy = {"skipped": False, "path": "", "valid": False}
        agent = StrategyValidator()
        ctx = agent.run(ctx)
        assert ctx.strategy["valid"] is False

    def test_invalid_python_fails(self, ctx, tmp_path):
        """Validator should fail for invalid Python syntax."""
        bad_file = tmp_path / "bad_strategy.py"
        bad_file.write_text("this is not valid python @@@")
        ctx.strategy = {"skipped": False, "path": str(bad_file), "valid": False}
        agent = StrategyValidator()
        ctx = agent.run(ctx)
        assert ctx.strategy["valid"] is False
