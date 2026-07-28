"""
Extract 23 features for XGBoost model — pure numpy, no external dependencies.

Синхронизировано с train_xgboost.py extract_features_v2().
"""

import numpy as np


def ema(data: np.ndarray, period: int) -> np.ndarray:
    """Exponential Moving Average."""
    result = np.full_like(data, np.nan, dtype=np.float64)
    alpha = 2.0 / (period + 1)
    result[period - 1] = np.mean(data[:period])
    for i in range(period, len(data)):
        result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
    return result


def rsi(data: np.ndarray, period: int = 14) -> np.ndarray:
    """Relative Strength Index. Returns 0-100."""
    deltas = np.diff(data, prepend=data[0])
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = ema(gains, period)
    avg_loss = ema(losses, period)
    rs = np.where(avg_loss > 0, avg_gain / avg_loss, 100.0)
    return 100.0 - (100.0 / (1.0 + rs))


def macd(data: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD line, signal line."""
    ema_fast = ema(data, fast)
    ema_slow = ema(data, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    return macd_line, signal_line


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """Average True Range."""
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr1 = high - low
    tr2 = np.abs(high - prev_close)
    tr3 = np.abs(low - prev_close)
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    return ema(tr, period)


def adx(candles: list, period: int = 14) -> np.ndarray:
    """Average Directional Index (simplified)."""
    n = len(candles)
    result = np.full(n, 20.0, dtype=np.float64)
    
    for i in range(period, n):
        plus_dm = []
        minus_dm = []
        tr_list = []
        
        for j in range(i - period, i + 1):
            if j == 0:
                continue
            high = candles[j]["high"]
            low = candles[j]["low"]
            prev_close = candles[j - 1]["close"]
            
            up = high - candles[j - 1]["high"]
            down = candles[j - 1]["low"] - low
            
            plus_dm.append(max(up, 0) if up > down else 0)
            minus_dm.append(max(down, 0) if down > up else 0)
            tr_list.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        
        if not tr_list:
            continue
        
        atr_val = np.mean(tr_list)
        if atr_val == 0:
            continue
        
        plus_di = (np.mean(plus_dm) / atr_val) * 100
        minus_di = (np.mean(minus_dm) / atr_val) * 100
        
        di_sum = plus_di + minus_di
        if di_sum == 0:
            continue
        
        dx = abs(plus_di - minus_di) / di_sum * 100
        result[i] = dx
    
    return result


def extract_features_v2(candles: list) -> np.ndarray:
    """
    Extract 23 features for XGBoost model.
    
    Returns:
        np.ndarray of shape (N, 23)
    """
    n = len(candles)
    opens = np.array([c["open"] for c in candles], dtype=np.float64)
    highs = np.array([c["high"] for c in candles], dtype=np.float64)
    lows = np.array([c["low"] for c in candles], dtype=np.float64)
    closes = np.array([c["close"] for c in candles], dtype=np.float64)
    volumes = np.array([c["volume"] for c in candles], dtype=np.float64)
    
    # Safe division helper
    def safe_div(a, b):
        return a / np.where(np.abs(b) < 1e-10, 1e-10, b)
    
    # ── 0-3: Basic candle features ──────────────────────
    hl_range = highs - lows
    hl_range = np.where(hl_range < 1e-10, 1e-10, hl_range)
    
    body = safe_div(closes - opens, hl_range)
    upper_shadow = safe_div(highs - np.maximum(opens, closes), hl_range)
    lower_shadow = safe_div(np.minimum(opens, closes) - lows, hl_range)
    range_pct = safe_div(hl_range, closes) * 100.0
    change_pct = safe_div(closes - opens, opens) * 100.0
    
    # ── 5-9: EMA distances ──────────────────────────────
    ema12 = ema(closes, 12)
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    
    ema12_dist = safe_div(closes - ema12, ema12) * 100.0
    ema20_dist = safe_div(closes - ema20, ema20) * 100.0
    ema50_dist = safe_div(closes - ema50, ema50) * 100.0
    ema12_20_cross = np.where(ema12 > ema20, 1.0, 0.0)
    ema20_50_cross = np.where(ema20 > ema50, 1.0, 0.0)
    
    # ── 10: RSI ─────────────────────────────────────────
    rsi_val = rsi(closes, 14)
    
    # ── 11-12: MACD ─────────────────────────────────────
    macd_line, signal_line = macd(closes)
    macd_norm = safe_div(macd_line, closes) * 100.0
    macd_signal_diff = safe_div(macd_line - signal_line, closes) * 100.0
    
    # ── 13-14: Bollinger Bands ──────────────────────────
    bb_mid = np.full(n, np.nan, dtype=np.float64)
    bb_std = np.full(n, np.nan, dtype=np.float64)
    for i in range(19, n):
        window = closes[i - 19:i + 1]
        bb_mid[i] = np.mean(window)
        bb_std[i] = np.std(window)
    
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    
    bb_position = safe_div(closes - bb_lower, bb_upper - bb_lower)
    bb_width = safe_div(bb_upper - bb_lower, bb_mid) * 100.0
    
    # ── 15: Volume ratio ────────────────────────────────
    vol_sma20 = np.full(n, np.nan, dtype=np.float64)
    for i in range(19, n):
        vol_sma20[i] = np.mean(volumes[i - 19:i + 1])
    vol_ratio = safe_div(volumes, vol_sma20)
    
    # ── 16: ATR ─────────────────────────────────────────
    atr_val = atr(highs, lows, closes, 14)
    atr_pct = safe_div(atr_val, closes) * 100.0
    
    # ── 17: ADX ─────────────────────────────────────────
    adx_val = adx(candles, 14)
    
    # ── 18-20: Momentum ─────────────────────────────────
    momentum_5 = np.full(n, 0.0, dtype=np.float64)
    momentum_10 = np.full(n, 0.0, dtype=np.float64)
    momentum_20 = np.full(n, 0.0, dtype=np.float64)
    
    for i in range(5, n):
        momentum_5[i] = safe_div(closes[i] - closes[i - 5], closes[i - 5]) * 100.0
    for i in range(10, n):
        momentum_10[i] = safe_div(closes[i] - closes[i - 10], closes[i - 10]) * 100.0
    for i in range(20, n):
        momentum_20[i] = safe_div(closes[i] - closes[i - 20], closes[i - 20]) * 100.0
    
    # ── 21: Volatility ──────────────────────────────────
    volatility_20 = np.full(n, 0.0, dtype=np.float64)
    for i in range(20, n):
        window = closes[i - 19:i + 1]
        returns = np.diff(window) / (window[:-1] + 1e-10)
        volatility_20[i] = np.std(returns) * 100.0
    
    # ── 22: Trend strength ──────────────────────────────
    trend_strength = momentum_5 * vol_ratio
    
    # Stack all features
    features = np.column_stack([
        body, upper_shadow, lower_shadow, range_pct, change_pct,
        ema12_dist, ema20_dist, ema50_dist, ema12_20_cross, ema20_50_cross,
        rsi_val,
        macd_norm, macd_signal_diff,
        bb_position, bb_width,
        vol_ratio,
        atr_pct,
        adx_val,
        momentum_5, momentum_10, momentum_20,
        volatility_20,
        trend_strength,
    ])
    
    # Replace NaN/Inf with 0
    features = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)
    
    return features


FEATURE_NAMES_V2 = [
    "body", "upper_shadow", "lower_shadow", "range_pct", "change_pct",
    "ema12_dist", "ema20_dist", "ema50_dist", "ema12_20_cross", "ema20_50_cross",
    "rsi",
    "macd", "macd_signal_diff",
    "bb_position", "bb_width",
    "vol_ratio",
    "atr_pct",
    "adx",
    "momentum_5", "momentum_10", "momentum_20",
    "volatility_20",
    "trend_strength",
]
