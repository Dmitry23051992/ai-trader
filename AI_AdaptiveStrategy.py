"""
AI Adaptive Strategy v4 — Adaptive to market regime.
Максимальный доход с разумным риском.
Адаптируется к режиму рынка через AI-параметры.
"""

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
from pandas import DataFrame
import talib.abstract as ta
import json
from pathlib import Path


class AI_AdaptiveStrategy(IStrategy):
    """
    AI-управляемая стратегия.
    Адаптирует входы, выходы, стоп-лосс и размер позиции
    к режиму рынка (bullish/neutral/bearish/panic).
    """

    INTERFACE_VERSION = 3
    timeframe = "15m"

    # ── ROI ───────────────────────────────────────────────────
    minimal_roi = {
        "0": 0.01,      # 1% — сразу выходим при малейшем плюсе
        "40": 0.008,    # 0.8% через 40 мин
        "80": 0.005,    # 0.5% через 80 мин
        "160": 0.002,   # 0.2% через 160 мин
    }

    # ── Стоп-лосс ─────────────────────────────────────────────
    stoploss = -0.035

    # ── Трейлинг ──────────────────────────────────────────────
    trailing_stop = True
    trailing_stop_positive = 0.008
    trailing_stop_positive_offset = 0.025
    trailing_only_offset_is_reached = True

    process_only_new_candles = True
    startup_candle_count = 200
    use_exit_signal = True
    exit_profit_only = False

    # ── Hyperopt-параметры ────────────────────────────────────
    buy_rsi = IntParameter(35, 65, default=45, space="buy")
    buy_adx = IntParameter(18, 32, default=20, space="buy")
    sell_rsi = IntParameter(70, 88, default=80, space="sell")
    base_stoploss = DecimalParameter(-0.055, -0.02, default=-0.035, decimals=3, space="sell")

    # ── AI-параметры ──────────────────────────────────────────
    _ai_params: dict = {}
    _params_path: Path = Path("/freqtrade/user_data/ai_params.json")
    _ai_params_ts: float = 0.0
    # Запоминаем ai_signal на момент входа, чтобы выход не менялся
    # если AI передумает mid-trade
    @property
    def ai_params(self) -> dict:
        import time
        now = time.time()
        if now - self._ai_params_ts > 60:
            try:
                if self._params_path.exists():
                    with open(self._params_path) as f:
                        self._ai_params = json.load(f)
                else:
                    self._ai_params = {}
            except Exception:
                self._ai_params = {}
            self._ai_params_ts = now
        return self._ai_params

    def _get_regime_multiplier(self) -> float:
        """Возвращает множитель агрессивности от 0.0 до 1.0."""
        regime = self.ai_params.get("market_regime", "neutral")
        multipliers = {
            "panic": 0.0,
            "bearish": 0.3,
            "neutral": 0.6,
            "bullish": 1.0,
        }
        return multipliers.get(regime, 0.6)

    # ── Индикаторы ────────────────────────────────────────────

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # — EMA —
        dataframe["ema12"] = ta.EMA(dataframe, timeperiod=12)
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema100"] = ta.EMA(dataframe, timeperiod=100)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)

        # — MACD —
        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd"] = macd["macd"]
        dataframe["macd_signal"] = macd["macdsignal"]
        dataframe["macd_hist"] = macd["macdhist"]

        # — RSI —
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["rsi_fast"] = ta.RSI(dataframe, timeperiod=7)

        # — Bollinger Bands —
        bbands = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        dataframe["bb_upper"] = bbands["upperband"]
        dataframe["bb_middle"] = bbands["middleband"]
        dataframe["bb_lower"] = bbands["lowerband"]
        dataframe["bb_position"] = (
            (dataframe["close"] - dataframe["bb_lower"]) /
            (dataframe["bb_upper"] - dataframe["bb_lower"] + 1e-9)
        )

        # — Volume —
        dataframe["volume_ma20"] = dataframe["volume"].rolling(20).mean()
        dataframe["volume_ratio"] = dataframe["volume"] / (dataframe["volume_ma20"] + 1e-9)

        # — ATR & ADX —
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / (dataframe["close"] + 1e-9) * 100
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)

        # — CCI —
        dataframe["cci"] = ta.CCI(dataframe, timeperiod=20)
        dataframe["willr"] = ta.WILLR(dataframe, timeperiod=14)

        # ============= СИГНАЛЬНЫЕ КОМПОНЕНТЫ =============

        # Тренд: цена > EMA200 И EMA50 > EMA200
        dataframe["trend_bull"] = (
            (dataframe["close"] > dataframe["ema200"]) &
            (dataframe["ema50"] > dataframe["ema200"])
        ).astype(int)

        # Моментум: EMA12 > EMA20 + MACD бычий
        dataframe["mom_bull"] = (
            (dataframe["ema12"] > dataframe["ema20"]) &
            (dataframe["macd"] > dataframe["macd_signal"])
        ).astype(int)

        # MACD усиление: гистограмма растёт
        dataframe["macd_rising"] = (
            dataframe["macd_hist"] > dataframe["macd_hist"].shift(1)
        ).astype(int)

        # ADX
        dataframe["adx_ok"] = (dataframe["adx"] >= self.buy_adx.value).astype(int)

        # Объём
        dataframe["vol_ok"] = (dataframe["volume_ratio"] >= 0.8).astype(int)

        # RSI в рабочей зоне
        dataframe["rsi_ok"] = (
            (dataframe["rsi"] >= 38) & (dataframe["rsi"] <= 65)
        ).astype(int)

        # Цена у EMA20 (подтверждение)
        dataframe["near_ema20"] = (
            (dataframe["close"] >= dataframe["ema20"] * 0.98) &
            (dataframe["close"] <= dataframe["ema20"] * 1.04)
        ).astype(int)

        # RSI fast momentum
        dataframe["rsi_mom"] = (
            dataframe["rsi_fast"] > dataframe["rsi_fast"].shift(1)
        ).astype(int)

        # ============= СКОРОВАЯ СИСТЕМА (0–12) =============
        score = 0
        score += dataframe["trend_bull"] * 3
        score += dataframe["mom_bull"] * 2
        score += dataframe["adx_ok"] * 2
        score += dataframe["vol_ok"] * 1
        score += dataframe["rsi_ok"] * 1
        score += dataframe["near_ema20"] * 1
        score += dataframe["macd_rising"] * 1
        score += dataframe["rsi_mom"] * 1
        dataframe["buy_score"] = score

        return dataframe

    # ── ВХОД ──────────────────────────────────────────────────
    #
    # AI-управляемый вход:
    #   ai_signal = "buy"  → доверяем AI, минимальные тех-фильтры
    #   ai_signal = "hold" → умеренные условия (scoring)
    #   ai_signal = "sell" → не входим
    #
    # recommended_pairs получают бонус к score.
    # confidence_threshold контролирует строгость фильтров.
    # ──────────────────────────────────────────────────────────

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0

        pair = metadata.get("pair", "")
        params = self.ai_params
        ai_signal = params.get("ai_signal", "hold")
        rec_pairs = params.get("recommended_pairs", [])
        avoid_pairs = params.get("avoid_pairs", [])
        conf = params.get("confidence_threshold", 0.5)
        regime_mult = self._get_regime_multiplier()

        # Если AI сказал "sell" — не входим (кроме режима паники)
        if ai_signal == "sell":
            return dataframe

        # Если пара в avoid_pairs — не входим
        if pair in avoid_pairs:
            return dataframe

        # Бонус для AI-рекомендованных пар
        rec_bonus = 1 if pair in rec_pairs else 0

        # Минимальный score: при conf=0.2→2, 0.4→3, 0.6→4
        min_score = max(1, min(6, int(1 + conf * 5)))
        score_ok = dataframe["buy_score"] >= (min_score - rec_bonus)

        # Базовая трендовая проверка
        trend_ok = (
            (dataframe["trend_bull"] == 1) |
            (dataframe["close"] > dataframe["ema50"])
        )

        if ai_signal == "buy":
            # === AI командует "покупать" — но проверяем качество ===
            # Нужен: score + тренд + моментум + объём + RSI не перепродан
            entry = (
                score_ok &
                trend_ok &
                (dataframe["mom_bull"] == 1) &
                (dataframe["vol_ok"] == 1) &
                (dataframe["rsi"] >= 35)
            )

        elif ai_signal == "hold" or regime_mult < 0.6:
            # === Неопределённость — умеренные условия ===
            entry = (
                score_ok &
                trend_ok &
                (dataframe["mom_bull"] == 1)
            )
        else:
            # === Без сигнала — стандартная логика ===
            entry = (
                score_ok &
                trend_ok &
                (dataframe["mom_bull"] == 1) &
                (dataframe["vol_ok"] == 1)
            )

        dataframe.loc[entry, "enter_long"] = 1
        return dataframe

    # ── ВЫХОД ──────────────────────────────────────────────────
    #
    # AI НЕ управляет выходами. Только ROI, стоп-лосс и трейлинг.
    # exit_signal используется только для перекупленности (RSI > 80).
    # Это предотвращает панические продажи всех позиций разом.
    # ──────────────────────────────────────────────────────────

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0

        # Единственный тех-выход — перекупленность (редко для мемкоинов)
        overbought = (dataframe["rsi"] > self.sell_rsi.value)

        dataframe.loc[overbought, "exit_long"] = 1
        return dataframe

    # ── AI-УПРАВЛЯЕМЫЕ ФУНКЦИИ ─────────────────────────────────

    def custom_stoploss(self, pair: str, trade, current_time, current_rate,
                        current_profit, **kwargs) -> float:
        """Стоп-лосс адаптируется к режиму рынка, но без паники.
        AI управляет только входом — выходы по стоп-лоссу, ROI и трейлингу."""
        params = self.ai_params
        regime_mult = self._get_regime_multiplier()

        # AI-стоплосс (базовое значение)
        ai_sl = params.get("stoploss")
        if ai_sl is not None and isinstance(ai_sl, (int, float)):
            base_sl = float(ai_sl)
        else:
            base_sl = float(self.base_stoploss.value)

        # Подтягиваем при профите (трейлинг)
        if current_profit > 0.05:
            return 0.005
        if current_profit > 0.03:
            return 0.01
        if current_profit > 0.015:
            return 0.02

        # В плохом рынке — чуть жёстче, но не панический
        if regime_mult < 0.4:
            return max(base_sl, -0.025)  # не жёстче -2.5%
        if regime_mult < 0.7:
            return base_sl * 0.8

        return base_sl

    def custom_stake_amount(self, pair: str, current_time, current_rate,
                            proposed_stake, min_stake, max_stake, leverage,
                            entry_tag, side, **kwargs) -> float:
        """AI управляет размером позиции с учётом режима."""
        params = self.ai_params
        regime_mult = self._get_regime_multiplier()
        ai_signal = params.get("ai_signal", "hold")

        # В панике / sell-сигнале не торгуем
        if regime_mult <= 0.0 or ai_signal == "sell":
            return 0.0

        # AI-размер позиции
        ai_pct = params.get("position_size_pct")
        if ai_pct is not None and isinstance(ai_pct, (int, float)):
            ai_size = min(float(ai_pct), 1.0)
        else:
            ai_size = 1.0

        # Адаптируем размер к режиму
        regime_factor = max(regime_mult, 0.2)

        # Бонус для рекомендованных пар
        rec_pairs = params.get("recommended_pairs", [])
        if pair in rec_pairs:
            regime_factor = min(regime_factor * 1.5, 1.0)

        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is not None and not dataframe.empty:
                last_adx = dataframe["adx"].iloc[-1]
                last_atr_pct = dataframe["atr_pct"].iloc[-1]

                # Высокая волатильность → уменьшаем
                if last_atr_pct > 4.0:
                    regime_factor *= 0.5
                if last_atr_pct > 6.0:
                    regime_factor *= 0.5

                # Сильный тренд → увеличиваем
                if last_adx > 30 and regime_mult > 0.6:
                    regime_factor = min(regime_factor * 1.3, 1.0)
        except Exception:
            pass

        return proposed_stake * ai_size * regime_factor

    def custom_exit(self, pair: str, trade, current_time, current_rate,
                    current_profit, **kwargs) -> str | None:
        """Не используется. AI управляет только входами."""
        return None

    def adjust_entry_price(self, trade, order, pair, current_time, proposed_rate, current_order_rate):
        return proposed_rate

    def leverage(self, pair: str, current_time, current_rate,
                 proposed_leverage, max_leverage, entry_tag, side, **kwargs) -> float:
        return 1.0
