"""Tests for agents.strategy.generator.StrategyGenerator."""

from pathlib import Path

import pytest

from agents.strategy.generator import StrategyGenerator


class TestStrategyGenerator:
    def test_generate_creates_file(self, tmp_path: Path, mock_llm):
        """StrategyGenerator should write a strategy file to disk."""
        generator = StrategyGenerator()
        # Override paths to use temp directory
        original_template = Path("templates/freqtrade_template.py")
        if not original_template.exists():
            pytest.skip("Template file not found (run from project root)")

        strategy_path = generator.generate(
            strategy_name="TestStrategy",
            previous_report="",
        )
        assert strategy_path.exists()
        content = strategy_path.read_text(encoding="utf-8")
        assert "TestStrategy" in content
        assert "populate_indicators" in content

    def test_generate_cleans_markdown_fences(self, tmp_path: Path, mock_llm):
        """Code fences should be stripped from LLM output."""
        generator = StrategyGenerator()
        strategy_path = generator.generate(
            strategy_name="CleanTest",
            previous_report="",
        )
        content = strategy_path.read_text(encoding="utf-8")
        assert "```" not in content

    def test_prompt_file_default_exists(self):
        """Default prompt file should exist."""
        prompt_path = Path("prompts/generate_strategy.txt")
        assert prompt_path.exists(), (
            f"Prompt file not found at {prompt_path.resolve()}"
        )
