import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from ai.trading.backtest_parser import BacktestReportParser


class BacktestReportParserTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.parser = BacktestReportParser()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parses_strategy_summary_json(self):
        report_path = self.base_path / "backtest-result.json"
        payload = {
            "strategy": {
                "MyStrategy": {
                    "total_trades": 77,
                    "wins": 67,
                    "losses": 10,
                    "draws": 0,
                    "profit_total_abs": 57.157,
                    "profit_total": 0.0572,
                    "profit_mean": 0.0023,
                    "profit_factor": 1.3,
                    "sharpe": 3.89,
                    "sortino": 2.57,
                    "cagr": 0.9241,
                    "max_drawdown_account": 0.0819,
                    "starting_balance": 1000,
                    "final_balance": 1057.157,
                    "rejected_signals": 258,
                    "max_consecutive_losses": 3,
                }
            }
        }
        report_path.write_text(json.dumps(payload), encoding="utf-8")

        summary = self.parser.parse(report_path, strategy_name="MyStrategy")

        self.assertEqual(summary["status"], "parsed")
        self.assertEqual(summary["total_trades"], 77)
        self.assertEqual(summary["wins"], 67)
        self.assertAlmostEqual(summary["profit_factor"], 1.3)
        self.assertAlmostEqual(summary["max_drawdown_pct"], 8.19)
        self.assertAlmostEqual(summary["cagr"], 92.41)

    def test_parses_zip_and_falls_back_to_trades(self):
        archive_path = self.base_path / "backtest-result.zip"
        trades_payload = {
            "strategy": {
                "ZipStrategy": {
                    "trades": [
                        {"profit_abs": 10.0, "profit_ratio": 0.02, "exit_reason": "roi"},
                        {"profit_abs": -5.0, "profit_ratio": -0.01, "exit_reason": "stop_loss"},
                        {"profit_abs": 0.0, "profit_ratio": 0.0, "exit_reason": "force_exit"},
                    ]
                }
            }
        }
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("backtest-result.json", json.dumps(trades_payload))

        summary = self.parser.parse(archive_path, strategy_name="ZipStrategy")

        self.assertEqual(summary["status"], "parsed")
        self.assertEqual(summary["total_trades"], 3)
        self.assertEqual(summary["wins"], 1)
        self.assertEqual(summary["losses"], 1)
        self.assertAlmostEqual(summary["absolute_profit"], 5.0)
        self.assertIn("stop_loss", summary["top_exit_reasons"])


if __name__ == "__main__":
    unittest.main()