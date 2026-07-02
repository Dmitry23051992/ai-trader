import subprocess
from pathlib import Path

from core.context import Context


class BacktestAgent:

    def __init__(self, project_root: Path | None = None):
        self.project_root = project_root

    def run(self, ctx: Context) -> Context:

        if ctx.strategy.get("skipped", False):
            ctx.log("[Backtest] Skipped: no strategy was generated.")
            ctx.backtest = {
                "returncode": 3,
                "stdout": "",
                "stderr": "Strategy generation skipped by decision engine.",
                "report": "",
            }
            return ctx

        if not ctx.strategy.get("valid", False):
            ctx.log("[Backtest] Skipped: strategy is not valid.")

            ctx.backtest = {
                "returncode": 2,
                "stdout": "",
                "stderr": "Strategy validation failed.",
                "report": "",
            }

            return ctx

        strategy = ctx.strategy["name"]

        ctx.log(f"[Backtest] Starting {strategy}")

        project_root = self.project_root or Path(__file__).resolve().parents[2]
        freqtrade_dir = project_root / "freqtrade"
        report_dir = freqtrade_dir / "user_data" / "backtest_results"
        validation_error = self._validate_environment(freqtrade_dir)
        if validation_error:
            ctx.log(f"[Backtest] {validation_error}")
            ctx.backtest = {
                "returncode": 4,
                "stdout": "",
                "stderr": validation_error,
                "report": "",
                "report_found": False,
            }
            return ctx

        known_artifacts = self._known_artifacts(report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            "docker",
            "compose",
            "run",
            "--rm",
            "freqtrade",
            "backtesting",
            "--config",
            "user_data/config_backtest.json",
            "--strategy",
            strategy,
            "--export",
            "trades",
            "--backtest-directory",
            "user_data/backtest_results",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=freqtrade_dir,
        )

        report = self._resolve_report_artifact(report_dir, known_artifacts)

        ctx.backtest = {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "report": str(report),
            "report_found": bool(report),
        }

        if result.returncode == 0:
            ctx.log("[Backtest] Finished successfully.")
        else:
            ctx.log("[Backtest] Failed.")

        return ctx

    def _validate_environment(self, freqtrade_dir: Path) -> str:
        if not freqtrade_dir.exists() or not freqtrade_dir.is_dir():
            return "Freqtrade directory is missing. Expected ./freqtrade with a working docker setup."

        config_path = freqtrade_dir / "user_data" / "config_backtest.json"
        if not config_path.exists():
            return "Freqtrade backtest config is missing: freqtrade/user_data/config_backtest.json"

        compose_files = [
            freqtrade_dir / "docker-compose.yml",
            freqtrade_dir / "docker-compose.yaml",
            freqtrade_dir / "compose.yml",
            freqtrade_dir / "compose.yaml",
        ]
        if not any(path.exists() for path in compose_files):
            return "Docker compose file is missing in ./freqtrade."

        return ""

    def _known_artifacts(self, report_dir: Path) -> set[str]:
        if not report_dir.exists():
            return set()
        return {
            str(path)
            for path in report_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".zip", ".json"}
        }

    def _resolve_report_artifact(self, report_dir: Path, known_artifacts: set[str]) -> Path | None:
        if not report_dir.exists():
            return None

        candidates = [
            path
            for path in report_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".zip", ".json"}
        ]
        if not candidates:
            return None

        new_candidates = [path for path in candidates if str(path) not in known_artifacts]
        selection = new_candidates or candidates
        return max(selection, key=lambda path: path.stat().st_mtime)
