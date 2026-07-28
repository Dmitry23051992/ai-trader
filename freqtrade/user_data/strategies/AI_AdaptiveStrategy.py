"""AI Adaptive Strategy v8 — profit-max and drawdown control."""

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, stoploss_from_open
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

    # ROI под 15m: берём достижимую прибыль, а не редкие импульсы 4-5%.
    minimal_roi = {
        "0": 0.018,
        "60": 0.012,
        "240": 0.008,
        "720": 0.004,
    }

    # ── Стоп-лосс: -15% — мемкоины волатильны ──────────────
    # -8% оказалось слишком мало: ADA -8.22%, TURBO -7.11%.
    # Теперь -15% — сработает только при реальном обвале.
    # custom_stoploss сужает стоп со временем.
    stoploss = -0.12

    # ── Трейлинг отключён ───────────────────────────────────
    # В реальной торговле trailing_stop_loss часто фиксировал убыточные выходы
    # на локальном шуме. Защиту прибыли берёт на себя custom_stoploss.
    trailing_stop = False
    # trailing_stop_positive отключен, т.к. конкурирует с custom_stoploss
    trailing_stop_positive = None
    trailing_stop_positive_offset = None
    trailing_only_offset_is_reached = False

    process_only_new_candles = True
    startup_candle_count = 200
    use_exit_signal = True
    # Ключевой фикс: закрытие по exit_signal только если сделка уже в прибыли.
    exit_profit_only = True
    # Компенсация комиссии/проскальзывания для выхода по сигналу.
    exit_profit_offset = 0.004
    use_custom_stoploss = True

    @property
    def protections(self):
        return [
            {
                "method": "CooldownPeriod",
                "stop_duration_candles": 4,
            },
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 48,
                "trade_limit": 3,
                "stop_duration_candles": 12,
                "only_per_pair": True,
            },
            {
                "method": "LowProfitPairs",
                "lookback_period_candles": 96,
                "trade_limit": 4,
                "stop_duration_candles": 24,
                "required_profit": 0.01,
                "only_per_pair": True,
            },
        ]

    # ── Hyperopt-параметры ────────────────────────────────────
    buy_rsi = IntParameter(38, 60, default=48, space="buy")
    buy_adx = IntParameter(18, 32, default=22, space="buy")
    sell_rsi = IntParameter(65, 85, default=75, space="sell")
    base_stoploss = DecimalParameter(-0.18, -0.05, default=-0.15, decimals=3, space="sell")

    # ── AI-параметры ──────────────────────────────────────────
    _ai_params: dict = {}
    _params_path: Path = Path("/freqtrade/user_data/ai_params.json")
    _ai_params_ts: float = 0.0
    hard_avoid_pairs = {"DOGE/USDT", "PEPE/USDT", "SHIB/USDT"}
    preferred_pairs = {"FLOKI/USDT", "TURBO/USDT", "PEOPLE/USDT"}
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
        dataframe["atr_ok"] = ((dataframe["atr_pct"] < 6.0) & (dataframe["atr_pct"] > 0.3)).astype(int)
        score += dataframe["atr_ok"] * 2

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
        if pair in self.hard_avoid_pairs:
            return dataframe

        params = self.ai_params
        ai_signal = params.get("ai_signal", "hold")
        rec_pairs = params.get("recommended_pairs", [])
        avoid_pairs = params.get("avoid_pairs", [])
        # Минимальный порог уверенности ограничивает переторговку в шуме.
        conf = max(float(params.get("confidence_threshold", 0.5)), 0.55)
        regime_mult = self._get_regime_multiplier()

        # Если AI сказал "sell" — не входим (кроме режима паники)
        if ai_signal == "sell":
            return dataframe

        # Если пара в avoid_pairs — не входим
        if pair in avoid_pairs:
            return dataframe

        # Бонус для AI-рекомендованных пар
        rec_bonus = 1 if pair in rec_pairs else 0
        if pair in self.preferred_pairs:
            rec_bonus += 1

        # Минимальный score: при conf=0.2→2, 0.4→3, 0.6→4
        min_score = max(1, min(6, int(1 + conf * 5)))
        score_ok = dataframe["buy_score"] >= (min_score - rec_bonus)

        # Базовая трендовая проверка
        trend_ok = (
            (dataframe["trend_bull"] == 1) |
            (dataframe["close"] > dataframe["ema50"])
        )
        strong_score_ok = dataframe["buy_score"] >= (min_score + 1 - rec_bonus)

        if ai_signal == "buy":
            # === AI командует "покупать" — но проверяем качество ===
            # Нужен: score + тренд + моментум + объём + RSI не перепродан
            entry = (
                score_ok &
                trend_ok &
                (dataframe["mom_bull"] == 1) &
                (dataframe["vol_ok"] == 1) &
                (dataframe["rsi"] >= 35) &
                (dataframe["atr_ok"] == 1)
            )

        elif ai_signal == "hold" or regime_mult < 0.6:
            # === Неопределённость — входим только при явном продолжении импульса ===
            # В нейтральном рынке режем слабые сетапы: нужен запас по score и улучшение моментума.
            entry = (
                strong_score_ok &
                trend_ok &
                (dataframe["macd_rising"] == 1) &
                (dataframe["rsi_mom"] == 1) &
                (dataframe["vol_ok"] == 1) &
                (dataframe["atr_ok"] == 1)
            )
        else:
            # === Без сигнала — стандартная логика ===
            entry = (
                score_ok &
                trend_ok &
                (dataframe["mom_bull"] == 1) &
                (dataframe["atr_ok"] == 1) &
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

        # Выходим при перекупленности только если импульс уже слабеет.
        overbought = (
            (dataframe["rsi"] > self.sell_rsi.value) &
            (dataframe["rsi"] < dataframe["rsi"].shift(1))
        )

        dataframe.loc[overbought, "exit_long"] = 1
        return dataframe

    # ── AI-УПРАВЛЯЕМЫЕ ФУНКЦИИ ─────────────────────────────────

    def custom_stoploss(self, pair: str, trade, current_time, current_rate,
                        current_profit, **kwargs) -> float:
        """Адаптивный стоп: режем убытки быстрее, победителям даём расти.

        Для прибыльных сделок используем stoploss_from_open, чтобы:
        - фиксировать часть профита,
        - не отдавать весь импульс назад,
        - не выходить в минус после достигнутой прибыли.
        """
        # Защита прибыли: по мере роста профита подтягиваем floor от цены входа.
        if current_profit >= 0.08:
            return stoploss_from_open(0.045, current_profit)
        if current_profit >= 0.05:
            return stoploss_from_open(0.025, current_profit)
        if current_profit >= 0.03:
            return stoploss_from_open(0.015, current_profit)
        if current_profit >= 0.015:
            return stoploss_from_open(0.003, current_profit)

        # AI может только расширить базовый стоп, но не ужесточать его раньше времени.
        # Иначе внешнее значение вроде -3.5% начинает выбивать сделки обычным шумом.
        base_stop = -0.08
        ai_stop = self.ai_params.get("stoploss")
        if isinstance(ai_stop, (int, float)) and ai_stop < 0:
            base_stop = max(-0.12, min(base_stop, float(ai_stop)))

        # Чем дольше нет результата, тем быстрее освобождаем капитал.
        is_preferred = pair in self.preferred_pairs

        if trade.open_date_utc:
            hours_open = (current_time - trade.open_date_utc).total_seconds() / 3600
            # Неприоритетные пары не держим глубоко в минусе слишком долго.
            if not is_preferred:
                if hours_open > 30:
                    return max(base_stop, -0.025)
                if hours_open > 18:
                    return max(base_stop, -0.032)
                if hours_open > 12:
                    return max(base_stop, -0.038)
                if hours_open > 6:
                    return max(base_stop, -0.05)

            if hours_open > 48:
                return max(base_stop, -0.03)
            if hours_open > 24:
                return max(base_stop, -0.04)
            if hours_open > 12:
                return max(base_stop, -0.055)
            if hours_open > 6:
                return max(base_stop, -0.07)

        return base_stop

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

        stake = proposed_stake * ai_size * regime_factor

        # Второстепенные пары ограничиваем по размеру,
        # чтобы одиночный убыток не съедал серию мелких профитов.
        if pair not in self.preferred_pairs:
            stake = min(stake, proposed_stake * 0.4)

        return stake

    def custom_exit(self, pair: str, trade, current_time, current_rate,
                    current_profit, **kwargs) -> str | None:
        """Выход застаревших сделок — освобождаем капитал.
        
        custom_stoploss уже сужает стоп, но может не хватить в слабом рынке.
        Этот exit — страховка от долгих убыточных позиций, особенно в нейтральных/панических режимах.
        
        Проблема: ETH -4.72% держали 18 часов → нужно выходить быстрее в нейтрале.
        """
        if not trade.open_date_utc:
            return None

        hours_open = (current_time - trade.open_date_utc).total_seconds() / 3600
        days_open = hours_open / 24
        
        # Адаптируем порог выхода к режиму рынка
        regime_mult = self._get_regime_multiplier()
        
        # === АГРЕССИВНЫЙ ВЫХОД В НЕЙТРАЛЬНОМ/ПАНИЧ РЕЖИМЕ ===
        if regime_mult < 0.6:
            # В нейтральности/панике не держим минусовые сделки
            if hours_open >= 12 and current_profit < 0.003:
                return "stale_trade_neutral"
            if hours_open >= 18 and current_profit < 0.006:
                return "stale_trade_neutral"
            if hours_open >= 24 and current_profit < 0.01:
                return "stale_trade_neutral"
            # Убыток → выходим в 2x раза быстрее
            if hours_open >= 12 and current_profit <= -0.01:
                return "stale_trade_loss"
            if hours_open >= 8 and current_profit < -0.02:
                return "stale_trade_loss"
        
        # === СТАНДАРТНЫЙ ВЫХОД В БЫЧЬЕМ/НЕЙТРАЛЬНОМ РЕЖИМЕ ===
        # Не режем умеренный минус слишком рано: сначала даём сделке
        # шанс восстановиться при наличии потенциала.
        if days_open >= 3 and current_profit <= -0.015:
            return "stale_trade"
        # После длительного удержания (4+ дня) закрываем слабые сделки
        if days_open >= 4 and current_profit < 0.005:
            return "stale_trade"
        # После 5+ дней даже лёгкий минус недопустим
        if days_open >= 5 and current_profit < 0.0:
            return "stale_trade_timeout"
        
        return None

    def adjust_entry_price(self, trade, order, pair, current_time, proposed_rate, current_order_rate, entry_tag=None):
        return proposed_rate

    def leverage(self, pair: str, current_time, current_rate,
                 proposed_leverage, max_leverage, entry_tag, side, **kwargs) -> float:
        return 1.0
