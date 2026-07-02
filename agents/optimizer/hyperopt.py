"""
HyperoptAgent — запускает Freqtrade hyperopt через Docker и парсит результаты.

Используется после BacktestAgent для оптимизации параметров стратегии.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from core.context import Context
from core.logger import log


class HyperoptAgent:
    """Run Freqtrade hyperopt and return the best discovered parameters."""

    def __init__(self, project_root: Path | None = None):
        self.project_root = project_root

    def run(self, ctx: Context) -> Context:
        if ctx.strategy.get("skipped", False):
            ctx.log("[Hyperopt] Skipped: no strategy was generated.")
            ctx.learning["hyperopt"] = {"status": "skipped", "reason": "No strategy"}
            return ctx

        strategy = ctx.strategy["name"]
        ctx.log(f"[Hyperopt] Starting hyperopt for {strategy}")

        project_root = self.project_root or Path(__file__).resolve().parents[2]
        freqtrade_dir = project_root / "freqtrade"
        hyperopt_results_dir = freqtrade_dir / "user_data" / "hyperopt_results"

        # Validate environment
        if not freqtrade_dir.exists():
            ctx.log("[Hyperopt] Freqtrade directory missing.")
            return ctx

        hyperopt_results_dir.mkdir(parents=True, exist_ok=True)

        known_results = self._known_results(hyperopt_results_dir)

        cmd: list[str] = [
            "docker",
            "compose",
            "run",
            "--rm",
            "freqtrade",
            "hyperopt",
            "--config",
            "user_data/config_backtest.json",
            "--strategy",
            strategy,
            "--hyperopt-loss",
            "SharpeHyperOptLoss",
            "--epochs",
            "50",
            "--spaces",
            "buy",
            "sell",
            "roi",
            "stoploss",
            "--print-all",
            "--export-filename",
            "user_data/hyperopt_results/",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=freqtrade_dir,
                timeout=1800,  # 30 min max
            )

            stdout = result.stdout
            stderr = result.stderr

            # Try to find the best result in stdout
            best_params = self._parse_best_params(stdout)
            best_result_artifact = self._resolve_artifact(
                hyperopt_results_dir, known_results
            )

            hyperopt_result: dict[str, Any] = {
                "returncode": result.returncode,
                "strategy": strategy,
                "best_params": best_params,
                "result_file": str(best_result_artifact) if best_result_artifact else "",
                "stdout_truncated": stdout[:2000],
                "stderr_truncated": stderr[:1000],
            }

            if best_params:
                ctx.log(
                    f"[Hyperopt] Best params found: "
                    f"buy_space={best_params.get('buy_space')}, "
                    f"stoploss={best_params.get('stoploss')}"
                )
                hyperopt_result["status"] = "completed"

                # Apply best params to strategy generation context for next iteration
                ctx.learning["hyperopt_best_params"] = best_params
            else:
                ctx.log("[Hyperopt] Completed but could not parse best params from output.")
                hyperopt_result["status"] = "completed_no_parse"

            ctx.learning["hyperopt"] = hyperopt_result

        except subprocess.TimeoutExpired:
            ctx.log("[Hyperopt] Timed out after 30 minutes.")
            ctx.learning["hyperopt"] = {"status": "timeout", "strategy": strategy}

        except FileNotFoundError:
            ctx.log("[Hyperopt] Docker not found. Is Docker installed?")
            ctx.learning["hyperopt"] = {"status": "docker_missing", "strategy": strategy}

        except Exception as exc:
            ctx.log(f"[Hyperopt] Error: {exc}")
            ctx.learning["hyperopt"] = {"status": "error", "error": str(exc)}

        return ctx

    def _parse_best_params(self, stdout: str) -> dict[str, Any]:
        """Extract best hyperopt parameters from Docker output."""
        params: dict[str, Any] = {}

        # Try JSON-like result block
        json_match = re.search(
            r'"buy_space"\s*:\s*({.*?}),\s*"sell_space"', stdout, re.DOTALL
        )
        if json_match:
            try:
                buy_space = json_match.group(1)
                params["buy_space"] = json.loads("{" + buy_space + "}")
            except json.JSONDecodeError:
                pass

        # Stop loss
        sl_match = re.search(r'"stoploss"\s*:\s*(-?\d+\.\d+)', stdout)
        if sl_match:
            params["stoploss"] = float(sl_match.group(1))

        # ROI table
        roi_match = re.search(r'"minimal_roi"\s*:\s*({.*?}})', stdout, re.DOTALL)
        if roi_match:
            try:
                params["minimal_roi"] = json.loads(roi_match.group(1))
            except json.JSONDecodeError:
                pass

        # Key result metrics line like:
        # "Best result:  42 trades  ...  profit 5.12%  ...  Sharpe 1.42"
        metrics_match = re.search(
            r"Best\s+result.*?profit\s+([\d.]+)%.*?Sharpe\s+([\d.]+)",
            stdout,
            re.IGNORECASE,
        )
        if metrics_match:
            params["best_profit_pct"] = float(metrics_match.group(1))
            params["best_sharpe"] = float(metrics_match.group(2))

        return params

    def _known_results(self, results_dir: Path) -> set[str]:
        """Return set of known result filenames before hyperopt runs."""
        if not results_dir.exists():
            return set()
        return {str(p) for p in results_dir.iterdir() if p.suffix in (".json", ".pickle", ".pkl")}

    def _resolve_artifact(
        self, results_dir: Path, known: set[str]
    ) -> Path | None:
        """Find the newest artifact created by this hyperopt run."""
        if not results_dir.exists():
            return None
        candidates = [
            p for p in results_dir.iterdir()
            if p.suffix in (".json", ".pickle", ".pkl") and str(p) not in known
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime)
