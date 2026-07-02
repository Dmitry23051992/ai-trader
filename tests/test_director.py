"""Tests for core.director.Director."""

from unittest.mock import MagicMock

import pytest

from core.context import Context
from core.director import Director


class TestDirector:
    def test_register_and_run(self):
        """Happy path: all agents succeed."""
        director = Director(iterations=2)

        # Agents must return a context — Director passes its own ctx to the agent
        # and the agent returns it (possibly modified). We use a side_effect that
        # simply returns the first argument (the ctx passed by Director).
        agent_a = MagicMock()
        agent_a.run.side_effect = lambda ctx: ctx

        agent_b = MagicMock()
        agent_b.run.side_effect = lambda ctx: ctx

        director.register(agent_a)
        director.register(agent_b)
        ctx = director.run()

        assert agent_a.run.call_count == 2  # 2 iterations
        assert agent_b.run.call_count == 2
        assert ctx.iteration == 2  # Director sets this

    def test_agent_failure_continues_by_default(self):
        """Pipeline continues after an agent failure when fail_fast=False."""
        director = Director(iterations=1, fail_fast=False)

        agent_ok = MagicMock()
        agent_ok.run.return_value = Context(iteration=1)

        agent_fail = MagicMock()
        agent_fail.run.side_effect = ValueError("boom")

        director.register(agent_ok)
        director.register(agent_fail)
        ctx = director.run()

        assert len(ctx.errors) == 1
        assert ctx.errors[0]["agent"] == agent_fail.__class__.__name__

    def test_fail_fast_raises(self):
        """Pipeline stops immediately when fail_fast=True."""
        director = Director(iterations=1, fail_fast=True)

        agent_fail = MagicMock()
        agent_fail.__class__.__name__ = "FailingAgent"
        agent_fail.run.side_effect = ValueError("boom")

        director.register(agent_fail)

        with pytest.raises(RuntimeError, match="FailingAgent"):
            director.run()
