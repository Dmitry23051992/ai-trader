from __future__ import annotations

from pathlib import Path

from core.llm import LLM
from core.logger import log


class StrategyGenerator:

    def __init__(self, prompt_path: Path | str | None = None):
        self.llm = LLM()
        self.prompt_path = Path(prompt_path or "prompts/generate_strategy.txt")

    def generate(self, strategy_name: str, previous_report: str = "") -> Path:
        """Generate a Freqtrade strategy using the LLM.

        Args:
            strategy_name: Name for the new strategy (used as class name + filename).
            previous_report: Previous iteration's learning report for context.

        Returns:
            Path to the saved strategy file.
        """
        template = Path("templates/freqtrade_template.py").read_text(encoding="utf-8")
        prompt_template = self.prompt_path.read_text(encoding="utf-8")

        prompt = (
            prompt_template.replace("{template}", template)
            .replace("{previous_report}", previous_report)
            .replace("{strategy_name}", strategy_name)
        )

        log.debug("Generating strategy '{}' via LLM (prompt len={})", strategy_name, len(prompt))

        code = self.llm.ask(prompt)

        # Strip markdown code fences if present
        code = code.replace("```python", "").replace("```", "").strip()

        # Ensure class name matches filename
        code = code.replace("TEMPLATE", strategy_name)

        strategy_path = Path("freqtrade/user_data/strategies") / f"{strategy_name}.py"
        strategy_path.parent.mkdir(parents=True, exist_ok=True)
        strategy_path.write_text(code, encoding="utf-8")

        log.info("Strategy saved: {} ({:.1f} KB)", strategy_path, len(code) / 1024)
        return strategy_path
