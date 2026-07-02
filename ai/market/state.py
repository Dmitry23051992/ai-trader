from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MarketState:
    exchange: str
    symbol: str
    timeframe: str
    trend: str
    volatility: str
    regime: str
    recommendation: str
    confidence: float
    last_price: float = 0.0
    adx: float = 0.0
    rsi: float = 0.0
    atr_pct: float = 0.0
    ema20: float = 0.0
    ema50: float = 0.0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "exchange": self.exchange,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "trend": self.trend,
            "volatility": self.volatility,
            "regime": self.regime,
            "recommendation": self.recommendation,
            "confidence": round(self.confidence, 3),
            "last_price": round(self.last_price, 8),
            "adx": round(self.adx, 3),
            "rsi": round(self.rsi, 3),
            "atr_pct": round(self.atr_pct, 3),
            "ema20": round(self.ema20, 8),
            "ema50": round(self.ema50, 8),
            "notes": self.notes,
        }