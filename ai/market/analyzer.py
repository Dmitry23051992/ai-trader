from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from configs.settings import (
    DB_PATH,
    EXCHANGE,
    MARKET_ANALYSIS_SYMBOLS,
    MARKET_ANALYSIS_TIMEFRAMES,
    MARKET_LOOKBACK_BARS,
    MARKET_TREND_ADX_THRESHOLD,
)

from .state import MarketState


@dataclass
class MarketSnapshot:
    state: MarketState
    candles: pd.DataFrame


class MarketAnalyzer:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)

    def load_candles(
        self,
        symbol: str,
        timeframe: str,
        lookback: int = MARKET_LOOKBACK_BARS,
    ) -> pd.DataFrame:
        if not self.db_path.exists():
            return pd.DataFrame()

        with duckdb.connect(str(self.db_path), read_only=True) as db:
            try:
                df = db.execute(
                    """
                    SELECT timestamp, datetime, open, high, low, close, volume
                    FROM candles
                    WHERE symbol = ? AND timeframe = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    [symbol, timeframe, lookback],
                ).df()
            except Exception:
                return pd.DataFrame()

        if df.empty:
            return df

        return df.sort_values("timestamp").reset_index(drop=True)

    def analyze_symbol(
        self,
        symbol: str,
        timeframe: str,
    ) -> MarketSnapshot | None:
        df = self.load_candles(symbol, timeframe)
        if df.empty or len(df) < 60:
            return None

        df = df.copy()
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["high"] = pd.to_numeric(df["high"], errors="coerce")
        df["low"] = pd.to_numeric(df["low"], errors="coerce")
        df = df.dropna(subset=["close", "high", "low"])

        if len(df) < 60:
            return None

        df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
        df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
        df["returns"] = df["close"].pct_change()
        df["atr"] = (df["high"] - df["low"]).rolling(14).mean()
        df["atr_pct"] = (df["atr"] / df["close"]) * 100.0
        df["volatility_rolling"] = df["returns"].rolling(20).std() * 100.0
        df["price_slope"] = df["ema20"].diff(5)

        last = df.iloc[-1]
        prev = df.iloc[-5] if len(df) >= 5 else last

        last_price = float(last["close"])
        ema20 = float(last["ema20"])
        ema50 = float(last["ema50"])
        adx = self._adx_proxy(df)
        rsi = self._rsi_proxy(df)
        atr_pct = float(last.get("atr_pct", 0.0) or 0.0)
        vol_pct = float(last.get("volatility_rolling", 0.0) or 0.0)

        trend = self._classify_trend(last_price, ema20, ema50, float(last["price_slope"]))
        volatility = self._classify_volatility(atr_pct, vol_pct)
        regime = self._classify_regime(trend, volatility, adx)
        recommendation, confidence, notes = self._recommendation(
            trend=trend,
            volatility=volatility,
            regime=regime,
            adx=adx,
            rsi=rsi,
            last_price=last_price,
            ema20=ema20,
            ema50=ema50,
            slope=float(last["price_slope"]),
            prev_price=float(prev["close"]),
        )

        state = MarketState(
            exchange=EXCHANGE,
            symbol=symbol,
            timeframe=timeframe,
            trend=trend,
            volatility=volatility,
            regime=regime,
            recommendation=recommendation,
            confidence=confidence,
            last_price=last_price,
            adx=adx,
            rsi=rsi,
            atr_pct=atr_pct,
            ema20=ema20,
            ema50=ema50,
            notes=notes,
        )

        return MarketSnapshot(state=state, candles=df)

    def analyze_universe(self) -> list[MarketSnapshot]:
        snapshots: list[MarketSnapshot] = []

        for symbol in MARKET_ANALYSIS_SYMBOLS:
            for timeframe in MARKET_ANALYSIS_TIMEFRAMES:
                snapshot = self.analyze_symbol(symbol, timeframe)
                if snapshot is not None:
                    snapshots.append(snapshot)

        return snapshots

    def summarize(self, snapshots: list[MarketSnapshot]) -> dict:
        if not snapshots:
            return {
                "trade_mode": "wait",
                "bias": "neutral",
                "confidence": 0.0,
                "reason": "No candle data available for analysis.",
                "counts": {
                    "bullish": 0,
                    "bearish": 0,
                    "neutral": 0,
                    "buy": 0,
                    "sell": 0,
                    "wait": 0,
                },
                "states": [],
            }

        bullish = sum(1 for item in snapshots if item.state.trend == "bullish")
        bearish = sum(1 for item in snapshots if item.state.trend == "bearish")
        neutral = len(snapshots) - bullish - bearish

        buy_votes = sum(
            1 for item in snapshots if item.state.recommendation == "buy"
        )
        sell_votes = sum(
            1 for item in snapshots if item.state.recommendation == "sell"
        )
        wait_votes = len(snapshots) - buy_votes - sell_votes

        if buy_votes > sell_votes and buy_votes >= wait_votes:
            trade_mode = "trade"
            bias = "bullish"
            reason = "Majority of markets show entry conditions."
        elif sell_votes > buy_votes:
            trade_mode = "protect"
            bias = "bearish"
            reason = "Markets are weak or risky; prefer exit or no new entries."
        else:
            trade_mode = "wait"
            bias = "neutral"
            reason = "No strong edge across monitored timeframes."

        confidence = max(
            item.state.confidence for item in snapshots
        ) if snapshots else 0.0

        return {
            "trade_mode": trade_mode,
            "bias": bias,
            "confidence": round(confidence, 3),
            "reason": reason,
            "counts": {
                "bullish": bullish,
                "bearish": bearish,
                "neutral": neutral,
                "buy": buy_votes,
                "sell": sell_votes,
                "wait": wait_votes,
            },
            "states": [snapshot.state.as_dict() for snapshot in snapshots],
        }

    def _classify_trend(
        self,
        last_price: float,
        ema20: float,
        ema50: float,
        slope: float,
    ) -> str:
        if last_price > ema20 > ema50 and slope > 0:
            return "bullish"
        if last_price < ema20 < ema50 and slope < 0:
            return "bearish"
        return "neutral"

    def _classify_volatility(self, atr_pct: float, vol_pct: float) -> str:
        score = max(atr_pct, vol_pct)
        if score < 1.0:
            return "low"
        if score < 2.5:
            return "moderate"
        return "high"

    def _classify_regime(self, trend: str, volatility: str, adx: float) -> str:
        if adx >= MARKET_TREND_ADX_THRESHOLD and trend != "neutral":
            return "trending"
        if volatility == "high" and trend == "neutral":
            return "choppy"
        return "ranging"

    def _recommendation(
        self,
        trend: str,
        volatility: str,
        regime: str,
        adx: float,
        rsi: float,
        last_price: float,
        ema20: float,
        ema50: float,
        slope: float,
        prev_price: float,
    ) -> tuple[str, float, list[str]]:
        notes: list[str] = []
        confidence = 0.5

        if trend == "bullish":
            confidence += 0.18
            notes.append("Price above short and medium EMAs.")
        elif trend == "bearish":
            confidence += 0.18
            notes.append("Price below short and medium EMAs.")
        else:
            notes.append("Trend is not aligned.")

        if regime == "trending":
            confidence += 0.12
            notes.append("ADX supports a directional market.")
        elif regime == "choppy":
            confidence -= 0.12
            notes.append("Volatility is high without direction.")

        if volatility == "high":
            confidence -= 0.08
            notes.append("Volatility is elevated.")
        elif volatility == "low":
            confidence += 0.04
            notes.append("Volatility is controlled.")

        if rsi > 70:
            notes.append("RSI is extended upward.")
            if trend == "bullish":
                confidence -= 0.08
        elif rsi < 30:
            notes.append("RSI is extended downward.")
            if trend == "bearish":
                confidence -= 0.08

        if trend == "bullish" and regime == "trending" and volatility != "high" and rsi < 70:
            recommendation = "buy"
        elif trend == "bearish" and regime == "trending":
            recommendation = "sell"
        else:
            recommendation = "wait"

        if slope < 0 and last_price < prev_price:
            notes.append("Momentum is weakening.")
            confidence -= 0.05

        if last_price > ema20 > ema50:
            confidence += 0.05
        elif last_price < ema20 < ema50:
            confidence += 0.05

        confidence = max(0.05, min(confidence, 0.95))
        return recommendation, confidence, notes

    def _adx_proxy(self, df: pd.DataFrame) -> float:
        change = df["close"].pct_change().abs().rolling(14).mean().iloc[-1]
        return float((change or 0.0) * 1000.0)

    def _rsi_proxy(self, df: pd.DataFrame) -> float:
        delta = df["close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean().iloc[-1]
        loss = (-delta.clip(upper=0)).rolling(14).mean().iloc[-1]

        gain = float(gain or 0.0)
        loss = float(loss or 0.0)

        if loss == 0:
            return 100.0 if gain > 0 else 50.0

        rs = gain / loss
        return float(100.0 - (100.0 / (1.0 + rs)))