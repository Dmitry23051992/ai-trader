"""pytest fixtures for the ai-trader test suite."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.context import Context


@pytest.fixture
def ctx() -> Context:
    """Return a fresh Context instance with iteration=1."""
    return Context(iteration=1)


@pytest.fixture
def sample_market_state() -> dict[str, Any]:
    """A typical bullish market state returned by MarketAgent."""
    return {
        "exchange": "binance",
        "trade_mode": "trade",
        "bias": "bullish",
        "confidence": 0.72,
        "reason": "Majority of markets show entry conditions.",
        "counts": {"bullish": 6, "bearish": 2, "neutral": 2, "buy": 5, "sell": 2, "wait": 3},
        "states": [
            {
                "exchange": "binance",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "trend": "bullish",
                "volatility": "moderate",
                "regime": "trending",
                "recommendation": "buy",
                "confidence": 0.72,
                "last_price": 67500.0,
                "adx": 28.0,
                "rsi": 62.0,
                "atr_pct": 1.2,
                "ema20": 67000.0,
                "ema50": 65000.0,
                "notes": "",
            },
            {
                "exchange": "binance",
                "symbol": "ETH/USDT",
                "timeframe": "1h",
                "trend": "bullish",
                "volatility": "moderate",
                "regime": "ranging",
                "recommendation": "buy",
                "confidence": 0.68,
                "last_price": 3450.0,
                "adx": 22.0,
                "rsi": 58.0,
                "atr_pct": 1.0,
                "ema20": 3400.0,
                "ema50": 3350.0,
                "notes": "",
            },
        ],
    }


@pytest.fixture
def sample_decision_buy(ctx: Context, sample_market_state: dict[str, Any]) -> Context:
    """Context with a bullish decision."""
    ctx.market = sample_market_state
    ctx.decision = {
        "action": "buy",
        "trade_mode": "trade",
        "bias": "bullish",
        "confidence": 0.72,
        "confidence_threshold": 0.65,
        "adaptive_reason": "",
        "reason": "Market conditions support an entry.",
    }
    return ctx


@pytest.fixture
def sample_decision_wait(ctx: Context) -> Context:
    """Context with a wait decision."""
    ctx.decision = {
        "action": "wait",
        "trade_mode": "wait",
        "bias": "neutral",
        "confidence": 0.4,
        "confidence_threshold": 0.65,
        "adaptive_reason": "",
        "reason": "No strong edge detected.",
    }
    return ctx


@pytest.fixture
def mock_llm(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Mock the LLM.ask() method to return predefined code."""
    mock = MagicMock()
    mock.ask.return_value = (
        "from freqtrade.strategy import IStrategy\n"
        "class TestStrategy(IStrategy):\n"
        "    timeframe = '15m'\n"
        "    def populate_indicators(self, dataframe, metadata):\n"
        "        return dataframe\n"
        "    def populate_entry_trend(self, dataframe, metadata):\n"
        "        dataframe['enter_long'] = 0\n"
        "        return dataframe\n"
        "    def populate_exit_trend(self, dataframe, metadata):\n"
        "        dataframe['exit_long'] = 0\n"
        "        return dataframe\n"
    )
    monkeypatch.setattr("agents.strategy.generator.LLM.ask", mock.ask)
    return mock
