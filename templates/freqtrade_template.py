from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
from pandas import DataFrame
import talib.abstract as ta
import numpy as np


class TEMPLATE(IStrategy):
    """
    Шаблон стратегии для генерации AI (v3 — качественный трендовый подход).

    ВАЖНО:
    - Используй сигнальные компоненты (trend_bull, mom_bull, adx_ok, vol_ok, rsi_ok, price_near_ema20).
    - Вход — только когда ВСЕ ключевые условия истинны (не по порогу суммы).
    - Выход — по развороту тренда/моментума или перекупленности.
    - Не менее 50 сделок, но не более 150 за 6 мес.

    Целевые метрики:
    - Win Rate 45-60%
    - Profit Factor > 1.3
    - Avg Profit > 0.3%
    - Max Drawdown < 15%
    """

    INTERFACE_VERSION = 3
    timeframe = "15m"

    # ROI — даём тренду время
    minimal_roi = {
        "0": 0.04,
        "90": 0.02,
        "180": 0.01,
    }

    stoploss = -0.04
    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True

    process_only_new_candles = True
    startup_candle_count = 200
    use_exit_signal = True
    exit_profit_only = False

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # ── Обязательные индикаторы ──────────────────────────
        dataframe["ema12"] = ta.EMA(dataframe, timeperiod=12)
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema100"] = ta.EMA(dataframe, timeperiod=100)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)

        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd"] = macd["macd"]
        dataframe["macd_signal"] = macd["macdsignal"]
        dataframe["macd_hist"] = macd["macdhist"]

        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        bbands = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        dataframe["bb_upper"] = bbands["upperband"]
        dataframe["bb_middle"] = bbands["middleband"]
        dataframe["bb_lower"] = bbands["lowerband"]

        dataframe["volume_ma20"] = dataframe["volume"].rolling(20).mean()
        dataframe["volume_ratio"] = dataframe["volume"] / dataframe["volume_ma20"]
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"] * 100

        # ── Добавь СВОИ индикаторы здесь ─────────────────────
        # Например: дополнительный осциллятор, свечной паттерн,
        #           уровни поддержки/сопротивления, и т.д.

        # ============= СИГНАЛЬНЫЕ КОМПОНЕНТЫ =============
        # Тренд (цена > EMA200 и золотой крест)
        dataframe["trend_bull"] = (
            (dataframe["close"] > dataframe["ema200"]) &
            (dataframe["ema50"] > dataframe["ema200"])
        ).astype(int)

        # Моментум (быстрые EMA + MACD)
        dataframe["mom_bull"] = (
            (dataframe["ema12"] > dataframe["ema20"]) &
            (dataframe["macd"] > dataframe["macd_signal"])
        ).astype(int)

        # Сила тренда (ADX)
        dataframe["adx_ok"] = (dataframe["adx"] > 22).astype(int)

        # Объём
        dataframe["vol_ok"] = (dataframe["volume_ratio"] >= 0.9).astype(int)

        # RSI в рабочей зоне
        dataframe["rsi_ok"] = (
            (dataframe["rsi"] >= 40) & (dataframe["rsi"] <= 65)
        ).astype(int)

        # Цена у EMA20 (подтверждение момента)
        dataframe["price_near_ema20"] = (
            (dataframe["close"] >= dataframe["ema20"] * 0.98) &
            (dataframe["close"] <= dataframe["ema20"] * 1.03)
        ).astype(int)

        # ============= СКОРОВАЯ СИСТЕМА (0-10) =============
        score = 0
        score += dataframe["trend_bull"] * 3
        score += dataframe["mom_bull"] * 2
        score += dataframe["adx_ok"] * 2
        score += dataframe["vol_ok"] * 1
        score += dataframe["rsi_ok"] * 1
        score += dataframe["price_near_ema20"] * 1
        dataframe["buy_score"] = score

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0

        # Вход: ВСЕ ключевые условия должны быть истинны
        entry = (
            (dataframe["trend_bull"] == 1) &
            (dataframe["mom_bull"] == 1) &
            (dataframe["adx_ok"] == 1) &
            (dataframe["vol_ok"] == 1) &
            (dataframe["rsi_ok"] == 1) &
            (dataframe["price_near_ema20"] == 1)
        )

        dataframe.loc[entry, "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0

        # 1. Тренд развернулся
        trend_fail = (
            (dataframe["ema12"] < dataframe["ema50"]) &
            (dataframe["ema20"] < dataframe["ema50"])
        )

        # 2. Моментум сломался
        mom_fail = (
            (dataframe["macd"] < dataframe["macd_signal"]) &
            (dataframe["macd_hist"] < 0) &
            (dataframe["rsi"] < 50)
        )

        # 3. Перекуплен
        overbought = (dataframe["rsi"] > 82)

        # 4. Пробой EMA100
        breakdown = (
            (dataframe["close"] < dataframe["ema100"]) &
            (dataframe["macd_hist"] < 0) &
            (dataframe["rsi"] < 50)
        )

        dataframe.loc[
            trend_fail | mom_fail | overbought | breakdown,
            "exit_long"
        ] = 1

        return dataframe
