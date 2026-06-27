import pandas as pd
import talib


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:

    df["ema20"] = talib.EMA(df["close"], 20)
    df["ema50"] = talib.EMA(df["close"], 50)
    df["ema100"] = talib.EMA(df["close"], 100)
    df["ema200"] = talib.EMA(df["close"], 200)

    df["rsi"] = talib.RSI(df["close"], 14)

    macd, signal, hist = talib.MACD(df["close"])

    df["macd"] = macd
    df["macd_signal"] = signal
    df["macd_hist"] = hist

    upper, middle, lower = talib.BBANDS(df["close"])

    df["bb_upper"] = upper
    df["bb_middle"] = middle
    df["bb_lower"] = lower

    df["atr"] = talib.ATR(
        df["high"],
        df["low"],
        df["close"]
    )

    df["adx"] = talib.ADX(
        df["high"],
        df["low"],
        df["close"]
    )

    return df
