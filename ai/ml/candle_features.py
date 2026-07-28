"""Extract 10 normalized features from OHLCV candles using pure numpy.

Features:
  0. body_ratio       — (close - open) / high_low_range
  1. upper_shadow     — (high - max(open,close)) / range
  2. lower_shadow     — (min(open,close) - low) / range
  3. range_pct        — (high - low) / close * 100
  4. vol_relative     — volume / sma(volume, 20)
  5. change_pct       — (close - prev_close) / prev_close * 100
  6. sma20_dist       — (close - sma20) / sma20 * 100
  7. rsi_norm         — RSI(14) / 100
  8. macd_norm        — (macd - signal) / close * 1000
  9. atr_norm         — ATR(14) / close * 100
"""

import numpy as np


def sma(data: np.ndarray, period: int) -> np.ndarray:
    """Simple Moving Average. Returns array same length, NaN for initial window."""
    result = np.full_like(data, np.nan, dtype=np.float64)
    for i in range(period - 1, len(data)):
        result[i] = np.mean(data[i - period + 1: i + 1])
    return result


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
    """MACD line, signal line, histogram."""
    ema_fast = ema(data, fast)
    ema_slow = ema(data, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """Average True Range."""
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr1 = high - low
    tr2 = np.abs(high - prev_close)
    tr3 = np.abs(low - prev_close)
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    return ema(tr, period)


def extract_features(candles: list[dict]) -> np.ndarray:
    """Extract 10 features from a list of OHLCV candle dicts.
    
    Args:
        candles: List of dicts with keys: open, high, low, close, volume
        
    Returns:
        np.ndarray of shape (N, 10) with features
    """
    n = len(candles)
    opens = np.array([c["open"] for c in candles], dtype=np.float64)
    highs = np.array([c["high"] for c in candles], dtype=np.float64)
    lows = np.array([c["low"] for c in candles], dtype=np.float64)
    closes = np.array([c["close"] for c in candles], dtype=np.float64)
    volumes = np.array([c["volume"] for c in candles], dtype=np.float64)

    # Feature 0: body_ratio
    ranges = highs - lows
    ranges = np.where(ranges == 0, 1e-10, ranges)
    body_ratio = (closes - opens) / ranges

    # Feature 1: upper_shadow
    upper_shadow = (highs - np.maximum(opens, closes)) / ranges

    # Feature 2: lower_shadow
    lower_shadow = (np.minimum(opens, closes) - lows) / ranges

    # Feature 3: range_pct
    range_pct = ranges / np.where(closes == 0, 1e-10, closes) * 100.0

    # Feature 4: vol_relative
    vol_sma20 = sma(volumes, 20)
    vol_relative = volumes / np.where(vol_sma20 == 0, 1e-10, vol_sma20)

    # Feature 5: change_pct
    prev_close = np.roll(closes, 1)
    prev_close[0] = closes[0]
    change_pct = (closes - prev_close) / np.where(prev_close == 0, 1e-10, prev_close) * 100.0

    # Feature 6: sma20_dist
    sma20 = sma(closes, 20)
    sma20_dist = (closes - sma20) / np.where(sma20 == 0, 1e-10, sma20) * 100.0

    # Feature 7: rsi_norm (RSI / 100)
    rsi_val = rsi(closes, 14)
    rsi_norm = rsi_val / 100.0

    # Feature 8: macd_norm
    macd_line, signal_line, _ = macd(closes)
    macd_norm = np.where(closes == 0, 0.0, (macd_line - signal_line) / closes * 1000.0)

    # Feature 9: atr_norm
    atr_val = atr(highs, lows, closes, 14)
    atr_norm = np.where(closes == 0, 0.0, atr_val / closes * 100.0)

    # Stack features
    features = np.column_stack([
        body_ratio, upper_shadow, lower_shadow, range_pct,
        vol_relative, change_pct, sma20_dist, rsi_norm,
        macd_norm, atr_norm
    ])

    return features


def normalize_features(features: np.ndarray) -> np.ndarray:
    """Min-max normalize features to [0, 1] range."""
    mins = np.nanmin(features, axis=0)
    maxs = np.nanmax(features, axis=0)
    ranges = maxs - mins
    ranges = np.where(ranges == 0, 1e-10, ranges)
    normalized = (features - mins) / ranges
    # Replace NaN with 0
    normalized = np.nan_to_num(normalized, nan=0.0)
    return normalized


def create_sequence(features: np.ndarray, seq_len: int = 20) -> np.ndarray:
    """Create a sequence of the last seq_len feature vectors.
    
    Returns:
        np.ndarray of shape (1, seq_len, num_features)
    """
    n = len(features)
    if n >= seq_len:
        seq = features[n - seq_len:]
    else:
        # Pad with zeros if not enough data
        pad = np.zeros((seq_len - n, features.shape[1]))
        seq = np.vstack([pad, features])
    return seq[np.newaxis, :]  # shape (1, seq_len, num_features)
