from pathlib import Path

from core.llm import LLM


class StrategyGenerator:

    def __init__(self):
        self.llm = LLM()

    def generate(self, strategy_name: str, previous_report: str = ""):

        template = Path(
            "templates/freqtrade_template.py"
        ).read_text(encoding="utf-8")

        prompt = f"""
You are an expert quantitative trader and Python developer.

Below is a VALID Freqtrade strategy.

Keep the Freqtrade API exactly as in the template.

Do not invent new methods.

Do not remove required methods.

Modify ONLY the trading logic.

================ TEMPLATE ================

{template}

==========================================

Previous strategy report:

{previous_report}

Create a NEW strategy.

Requirements:

- Rename class TEMPLATE to {strategy_name}
- Keep timeframe 15m
- Improve profitability
- Reduce drawdown
- Improve winrate

Return ONLY valid Python code.

No markdown.

No explanations.
"""

        code = self.llm.ask(prompt)

        code = code.replace("```python", "")
        code = code.replace("```", "")
        code = code.replace("TEMPLATE", strategy_name)
        code = code.strip()

        strategy_path = (
            Path("freqtrade/user_data/strategies")
            / f"{strategy_name}.py"
        )

        strategy_path.write_text(
            code,
            encoding="utf-8"
        )

        return strategy_path
