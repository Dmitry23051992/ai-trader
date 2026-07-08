"""
AI Adaptive Strategy v5 — Risk-controlled growth.
Максимальный доход с разумным риском.
Фикс: ROI даёт прибыли расти, exit_signal не паникует.
"""

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
from pandas import DataFrame
import talib.abstract as ta
import json
from pathlib import Path


class AI_AdaptiveStrategy(IStrategy):
    """
    AI-управляемая стратегия v5.

    Главное изменение: ROI настроен так, чтобы прибыль МОГЛА перевешивать убытки.
    При winrate 55% и соотношении avg_win / avg_loss > 1 система выходит в плюс.
    """

    INTERFACE_VERSION = 3
    timeframe = "15m"

    # ── ROI: 5% → 4% → 2% — берём прибыль ──────────────────
    # Главное: прибыль должна БЫТЬ зафиксирована, пока она есть.
    # 5% — быстрый выход на сильных движениях.
    # 1-4ч — постепенно снижаем планку.
    minimal_roi = {
        "0": 0.05,      # 5% — сразу фиксируем
        "60": 0.04,     # 4% через 1 час
        "240": 0.02,    # 2% через 4 часа
    }

    # ── Стоп-лосс: -15% — мемкоины волатильны ──────────────
    # -8% оказалось слишком мало: ADA -8.22%, TURBO -7.11%.
    # Теперь -15% — сработает только при реальном обвале.
    # custom_stoploss сужает стоп со временем.
    stoploss = -0.15

    # ── Трейлинг: фиксируем 3% прибыли ─────────────────────
    # Было 1% — выбивало из прибыли. Теперь 3% — даём рост,
    # но фиксируем при падении с 4%+.
    trailing_stop = True
    trailing_stop_positive = 0.03
    trailing_stop_positive_offset = 0.04
    trailing_only_offset_is_reached = True

    process_only_new_candles = True
    startup_candle_count = 200
    use_exit_signal = True
    exit_profit_only = False
    use_custom_stoploss = True

    # ── Hyperopt-параметры ────────────────────────────────────
    buy_rsi = IntParameter(35, 65, default=45, space="buy")
    buy_adx = IntParameter(18, 32, default=20, space="buy")
    sell_rsi = IntParameter(70, 88, default=80, space="sell")
    base_stoploss = DecimalParameter(-0.18, -0.05, default=-0.15, decimals=3, space="sell")

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
            # === Неопределённость — мягкий вход без моментума ===
            # В bearish рынке mom_bull редко выполняется, поэтому не блокируем вход.
            # Достаточно: score + тренд (или цена выше EMA50).
            entry = (
                score_ok &
                trend_ok
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
    # AI НЕ управляет выходами.
    # Выходы управляются (в порядке приоритета):
    #   1. custom_stoploss — подтягивает при профите 2%/4%/6%+
    #   2. trailing_stop — фиксирует прибыль при падении с 4%+
    #   3. populate_exit_trend — RSI > 80 (перекупленность)
    #   4. custom_exit — stale trade >3 дней без движения
    #   5. stoploss = -8% — только реальный обвал
    # ROY отключён — больше не режет прибыль раньше времени.
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
        """Стоп-лосс: -15% первые 12ч, затем сужается.
        
        Meme-coin'ы волатильны: -8..-12% это нормальный шум.
        Даём сделке пространство в первый день. Если за 12ч
        не восстановилась — начинаем сужать, чтобы не терять 
        капитал в безнадёжных сделках.
        
        При прибыли — подтягиваем, фиксируем достигнутое.
        """
        # ── Защита прибыли (приоритет 1) ──────────────────
        if current_profit > 0.08:
            return 0.005    # 8%+ → стоп в 0.5%
        if current_profit > 0.06:
            return 0.01     # 6%+ → стоп в 1%
        if current_profit > 0.04:
            return 0.02     # 4%+ → стоп в 2%
        if current_profit > 0.02:
            return 0.025    # 2%+ → стоп в 2.5%

        # ── Время: чем дольше сделка, тем жёстче стоп ────
        if trade.open_date_utc:
            hours_open = (current_time - trade.open_date_utc).total_seconds() / 3600
            if hours_open > 48:
                return -0.03    # 2 дня → -3% (хватит ждать)
            if hours_open > 24:
                return -0.05    # 1 день → -5%
            if hours_open > 12:
                return -0.10    # 12ч → -10%

        # ── Первые 12ч: широкий стоп ─────────────────────
        return -0.15    # -15% — только реальный обвал

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
        """Выход застаревших сделок — освобождаем капитал.
        
        custom_stoploss уже сужает стоп до -3% к 48ч.
        Этот exit — последняя страховка: если стоп-лосс не сработал
        (например из-за гэпа), форсируем выход.
        """
        if trade.open_date_utc:
            days_open = (current_time - trade.open_date_utc).days
            # 5 дней — любые сделки закрываем
            if days_open >= 5 and current_profit < 0.02:
                return "stale_trade"
        return None

    def adjust_entry_price(self, trade, order, pair, current_time, proposed_rate, current_order_rate, entry_tag=None):
        return proposed_rate

    def leverage(self, pair: str, current_time, current_rate,
                 proposed_leverage, max_leverage, entry_tag, side, **kwargs) -> float:
        return 1.0
