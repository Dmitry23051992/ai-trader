"""Tests for core.context.Context."""

from core.context import Context


class TestContext:
    def test_defaults(self):
        ctx = Context()
        assert ctx.iteration == 0
        assert ctx.market == {}
        assert ctx.errors == []
        assert ctx.logs == []
        assert ctx.report == ""

    def test_has_errors_false_initially(self):
        ctx = Context()
        assert ctx.has_errors is False

    def test_has_errors_true_when_errors_present(self):
        ctx = Context()
        ctx.errors.append({"agent": "Test", "error": "fail"})
        assert ctx.has_errors is True

    def test_summary_format(self):
        ctx = Context(iteration=3)
        ctx.decision = {"action": "buy"}
        ctx.backtest = {"returncode": 0}
        summary = ctx.summary()
        assert "iter=3" in summary
        assert "decision=buy" in summary
        assert "backtest_code=0" in summary
        assert "errors=0" in summary

    def test_log_appends_message(self, ctx):
        ctx.log("hello")
        assert len(ctx.logs) == 1
        assert "hello" in ctx.logs[0]
