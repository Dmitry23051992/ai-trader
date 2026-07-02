import tempfile
import unittest
from pathlib import Path

from agents.execution.backtester import BacktestAgent
from core.context import Context


class BacktestAgentTest(unittest.TestCase):
    def test_missing_freqtrade_environment_fails_fast(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            agent = BacktestAgent(project_root=project_root)
            ctx = Context(strategy={"valid": True, "name": "DemoStrategy"})

            result = agent.run(ctx)

            self.assertEqual(result.backtest["returncode"], 4)
            self.assertIn("Freqtrade directory is missing", result.backtest["stderr"])
            self.assertFalse(result.backtest["report_found"])


if __name__ == "__main__":
    unittest.main()