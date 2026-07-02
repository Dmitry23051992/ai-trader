#!/usr/bin/env python3
"""
AI Agent for Freqtrade — анализирует рынок через локальную LLM (Ollama)
и управляет параметрами AI_AdaptiveStrategy.

Запуск: python3 ai_agent.py
Режимы:
  --once       → один цикл анализа и выход
  --daemon     → бесконечный цикл (каждые N минут)
  --chat       → интерактивный диалог с LLM о рынке (по умолчанию)
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# ── Конфигурация ─────────────────────────────────────────────
FREQTRADE_API = os.getenv("FREQTRADE_API", "http://localhost:8080")
FREQTRADE_USER = os.getenv("FREQTRADE_USER", "admin")
FREQTRADE_PASS = os.getenv("FREQTRADE_PASS", "changeme")

OLLAMA_API = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:3b"

AI_PARAMS_PATH = Path("/home/user/ai-trader/freqtrade/user_data/ai_params.json")
STRATEGY_PATH = Path("/home/user/ai-trader/freqtrade/user_data/strategies/AI_AdaptiveStrategy.py")
LOG_PATH = Path("/home/user/ai-trader/freqtrade/user_data/logs/ai_agent.log")

CHECK_INTERVAL = 60 * 15  # 15 минут между анализами
MAX_DAYS_DATA = 7          # сколько дней данных учитывать

BASE64_CRED = base64_creds = __import__("base64").b64encode(
    f"{FREQTRADE_USER}:{FREQTRADE_PASS}".encode()
).decode()


# ── Утилиты ──────────────────────────────────────────────────

def log(msg: str):
    """Логирование с timestamp."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def api_get(path: str) -> dict:
    """GET-запрос к Freqtrade API."""
    url = f"{FREQTRADE_API}{path}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Basic {BASE64_CRED}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log(f"API Error {url}: {e}")
        return {}


def ollama_chat(prompt: str, system: str = "") -> str:
    """Отправить промпт в Ollama, вернуть текст ответа."""
    import urllib.request as req
    import json as j

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": 384,
            "top_k": 30,
            "top_p": 0.85,
        }
    }
    data = j.dumps(payload).encode()
    try:
        r = req.Request(
            f"{OLLAMA_API}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with req.urlopen(r, timeout=180) as resp:
            result = j.loads(resp.read())
            return result.get("response", "").strip()
    except Exception as e:
        log(f"Ollama Error: {e}")
        return ""


# ── Свечные данные с Binance ──────────────────────────────

BINANCE_API = "https://api.binance.com"
TIMEFRAME_MINUTES = 15  # совпадает с настройкой стратегии
CANDLE_LIMIT = 24       # последние 24 свечи = 6 часов (достаточно для тренда)


def fetch_ohlcv(symbol: str, interval: str = f"{TIMEFRAME_MINUTES}m", limit: int = CANDLE_LIMIT) -> list:
    """Получить OHLCV свечи с Binance.

    Возвращает список свечей: [timestamp, open, high, low, close, volume, ...]
    """
    url = f"{BINANCE_API}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return [
                {
                    "time": int(c[0]),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5]),
                }
                for c in data
            ]
    except Exception as e:
        log(f"Binance OHLCV Error [{symbol}]: {e}")
        return []


def analyze_candles(candles: list) -> dict:
    """Проанализировать свечи: тренд, волатильность, объём, паттерны."""
    if not candles or len(candles) < 10:
        return {}

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c["volume"] for c in candles]
    n = len(closes)
    current_price = closes[-1]

    # Изменение цены за весь период
    change_pct = (closes[-1] - closes[0]) / closes[0] * 100
    # Изменение за последние 3 свечи
    change_short = (closes[-1] - closes[-4]) / closes[-4] * 100 if n >= 4 else 0

    # Волатильность (средний диапазон свечи в %)
    avg_range = sum((highs[i] - lows[i]) / closes[i] * 100 for i in range(n)) / n

    # Объём
    avg_volume = sum(volumes) / n
    volume_ratio = volumes[-1] / avg_volume if avg_volume > 0 else 1.0
    vol_trend = "growing" if n >= 3 and volumes[-1] > volumes[-2] > volumes[-3] else \
                "falling" if n >= 3 and volumes[-1] < volumes[-2] < volumes[-3] else "mixed"

    # Тренд через простые скользящие средние
    ema_short = sum(closes[-5:]) / 5
    ema_long = sum(closes[-20:]) / 20 if n >= 20 else sum(closes) / n
    trend = "up" if ema_short > ema_long else "down"

    # Соотношение бычьих/медвежьих свечей
    up = sum(1 for i in range(1, n) if closes[i] > closes[i - 1])
    down = n - 1 - up
    trend_strength = (up - down) / (n - 1) * 100  # -100..+100

    # Максимальное проседание за период
    max_drop = 0.0
    for i in range(1, n):
        peak = max(highs[max(0, i - 5):i + 1])
        drop = (closes[i] - peak) / peak * 100
        max_drop = min(max_drop, drop)

    return {
        "price": round(current_price, 8),
        "change_pct": round(change_pct, 2),
        "change_3candle_pct": round(change_short, 2),
        "trend": trend,
        "trend_strength": round(trend_strength, 1),
        "volatility_pct": round(avg_range, 2),
        "volume_ratio": round(volume_ratio, 2),
        "volume_trend": vol_trend,
        "max_drop_pct": round(max_drop, 2),
    }


def collect_candle_data(pairs: list[str]) -> dict:
    """Собрать свечной анализ для всех пар."""
    log(f"Fetching OHLCV for {len(pairs)} pairs...")
    result = {}
    for pair in pairs:
        symbol = pair.replace("/", "")
        candles = fetch_ohlcv(symbol)
        if candles:
            analysis = analyze_candles(candles)
            if analysis:
                result[pair] = analysis
    return result


# ── Сбор данных с Freqtrade ─────────────────────────────────

def collect_market_data() -> dict:
    """Собрать все данные о состоянии бота и рынка."""
    log("Collecting market data...")

    status = api_get("/api/v1/status") or []
    balance = api_get("/api/v1/balance") or {}
    trades = api_get("/api/v1/trades?limit=15") or {"trades": []}
    whitelist = api_get("/api/v1/whitelist") or {}
    performance = api_get("/api/v1/performance") or []
    locks = api_get("/api/v1/locks") or {}
    config = api_get("/api/v1/show_config") or {}

    # Текущие открытые сделки
    open_trades = []
    for t in status:
        if isinstance(t, dict) and t.get("is_open"):
            open_trades.append({
                "pair": t["pair"],
                "profit_pct": round(t.get("profit_pct", 0), 2),
                "duration_min": t.get("trade_duration", 0),
                "stake": round(t.get("stake_amount", 0), 2),
            })

    # Последние закрытые сделки
    closed_trades = []
    for t in (trades.get("trades") or []):
        if not t.get("is_open", True):
            closed_trades.append({
                "pair": t["pair"],
                "profit_pct": round(t.get("profit_pct", 0), 2),
                "profit_abs": round(t.get("profit_abs", 0), 2),
                "exit_reason": t.get("exit_reason", "?"),
                "duration_min": t.get("trade_duration", 0),
            })

    # Производительность по парам
    pair_stats = {}
    for p in (performance or []):
        pair_stats[p["pair"]] = {
            "profit_pct": round(p.get("profit_pct", 0), 2),
            "count": p.get("count", 0),
        }

    # Баланс
    currencies = balance.get("currencies", [])
    usdt_info = {}
    for c in currencies:
        if c.get("currency") == "USDT":
            usdt_info = {
                "free": round(float(c.get("free", 0)), 2),
                "balance": round(float(c.get("balance", 0)), 2),
            }
            break

    total_balance = round(balance.get("total", 0), 2)
    starting_capital = round(balance.get("starting_capital", 0), 2)

    return {
        "timestamp": datetime.now().isoformat(),
        "balance": {
            "total_usdt": total_balance,
            "free_usdt": usdt_info.get("free", 0),
            "starting_capital": starting_capital,
            "profit_pct": round((total_balance - starting_capital) / starting_capital * 100, 2) if starting_capital else 0,
        },
        "whitelist": whitelist.get("whitelist", []),
        "open_trades": open_trades,
        "closed_trades": closed_trades[:10],  # последние 10
        "pair_performance": pair_stats,
        "locked_pairs": locks.get("locks", []),
        "config": {
            "max_open_trades": config.get("max_open_trades", 0),
            "minimal_roi": config.get("minimal_roi", {}),
            "stoploss": config.get("stoploss", 0),
        },
    }


# ── Формирование промпта ────────────────────────────────────

def build_market_prompt(data: dict, candle_data: dict = None) -> tuple[str, str]:
    """Сформировать system-промпт и user-запрос для LLM."""

    system = """Ты — AI-трейдер-аналитик. Твоя задача — анализировать рынок криптовалют и давать рекомендации для торгового бота Freqtrade.

Отвечай ТОЛЬКО в JSON-формате, без пояснений:
{
  "market_regime": "bullish" | "neutral" | "bearish" | "panic",
  "reasoning": "кратко почему такой режим (1-2 предложения)",
  "stoploss_recommendation": -0.035,
  "position_size_pct": 0.0-1.0,
  "confidence_threshold": 0.0-1.0,
  "recommended_pairs": ["BTC/USDT", ...],
  "avoid_pairs": [],
  "action": "increase" | "reduce" | "hold",
  "ai_signal": "buy" | "sell" | "hold"
}

ВАЖНО: Ты должен рекомендовать АКТИВНУЮ торговлю. Если рынок нейтральный или бычий — ставь position_size_pct = 0.8-1.0 и confidence_threshold = 0.3-0.5.
Не будь слишком консервативным! Торговля должна идти.

Правила:
- ai_signal="buy": рынок располагает к покупкам, стратегия должна входить
- ai_signal="sell": ТОЛЬКО при экстремальном кризисе, стратегия перестаёт входить и затягивает стопы
- ai_signal="hold": неопределённость или слабый рынок — стратегия использует свои фильтры

ВАЖНО: "sell" — это сигнал ТОЛЬКО для КАТАСТРОФЫ. Не используй его при обычных просадках!
Обычные убытки и красные свечи — это нормально, это не повод для "sell".

Правила определения режима:
- bullish: баланс растёт, больше прибыльных сделок → ai_signal="buy"
- neutral: смешанные результаты или небольшие убытки → ai_signal="hold"
- bearish: баланс снижается >5% от пика → ai_signal="hold" (не sell! только снижаем активность)
- panic: резкие убытки >10% за 24ч ИЛИ total P&L < -15% → ai_signal="sell"

ЗАПОМНИ: Паниковать и продавать — самая частая причина потери денег.
Если рынок идёт вниз — лучше hold (не входить), чем sell (выходить в минус).

stoploss_recommendation: от -0.02 до -0.05
position_size_pct: от 0.5 до 1.0 (НЕ ставь меньше 0.5!)
confidence_threshold: от 0.2 до 0.6 (ниже = больше входов, НЕ ставь выше 0.6!)

Теперь у тебя есть СВЕЧНЫЕ ДАННЫЕ (OHLCV) с Binance за последние 12 часов.
Анализируй их:
- trend=up/down + trend_strength (-100..+100) — насколько сильный тренд
- change_pct — изменение цены за 12ч
- change_3candle_pct — изменение за последние 45 мин
- volatility_pct — средняя волатильность свечи
- volume_ratio — текущий объём к среднему (>1.5 = аномальный)
- volume_trend — growing/falling/mixed
- max_drop_pct — максимальное проседание
Используй свечные данные чтобы выбирать recommended_pairs (пары с сильным трендом и объёмом).
"""

    # Формируем сводку рынка
    bal = data["balance"]
    summary = f"""=== СВОДКА РЫНКА ===
Баланс: {bal['total_usdt']} USDT (стартовый: {bal['starting_capital']})
Общий P&L: {bal['profit_pct']:+.2f}%
Свободно: {bal['free_usdt']} USDT

=== ОТКРЫТЫЕ СДЕЛКИ ({len(data['open_trades'])}) ===
"""
    for t in data["open_trades"]:
        summary += f"  {t['pair']}: {t['profit_pct']:+.2f}% | {t['duration_min']} мин | стейк: {t['stake']} USDT\n"

    summary += f"\n=== ПОСЛЕДНИЕ ЗАКРЫТЫЕ СДЕЛКИ ===\n"
    for t in data["closed_trades"][:8]:
        summary += f"  {t['pair']}: {t['profit_pct']:+.2f}% ({t['profit_abs']:+.2f}) | {t['exit_reason']}\n"

    summary += f"\n=== ПРОИЗВОДИТЕЛЬНОСТЬ ПО ПАРАМ ===\n"
    for pair, stats in sorted(data["pair_performance"].items(), key=lambda x: x[1]["profit_pct"]):
        summary += f"  {pair}: {stats['profit_pct']:+.2f}% ({stats['count']} сделок)\n"

    summary += f"\n=== ПАРЫ В WHITELIST ({len(data['whitelist'])}) ===\n"
    summary += ", ".join(data["whitelist"][:8])
    if len(data["whitelist"]) > 8:
        summary += f" ... и ещё {len(data['whitelist'])-8}"

    # ── Свечной анализ ────────────────────────────────────
    if candle_data:
        summary += "\n\n=== СВЕЧНОЙ АНАЛИЗ (OHLCV, 15m, 12 часов) ===\n"
        # Сортируем пары по силе тренда
        sorted_pairs = sorted(
            candle_data.items(),
            key=lambda x: abs(x[1].get("trend_strength", 0)),
            reverse=True
        )
        # Показываем топ-6 пар по силе тренда
        num_shown = min(6, len(sorted_pairs))
        for pair, cdl in sorted_pairs[:num_shown]:
            trend_icon = "🟢" if cdl.get("trend") == "up" else "🔴"
            vol_mark = "📊" if cdl.get("volume_ratio", 0) > 1.3 else ""
            summary += (
                f"  {trend_icon} {pair}: "
                f"изм={cdl['change_pct']:+.1f}% "
                f"(3св={cdl['change_3candle_pct']:+.1f}%) | "
                f"тренд={cdl['trend_strength']:+.0f} | "
                f"вол=±{cdl['volatility_pct']:.1f}% | "
                f"объём={cdl['volume_ratio']:.1f}×{vol_mark}\n"
            )
        # Краткая сводка по остальным
        if len(sorted_pairs) > num_shown:
            up_count = sum(1 for _, c in sorted_pairs[num_shown:] if c.get("trend") == "up")
            down_count = len(sorted_pairs) - num_shown - up_count
            summary += f"  ... и ещё {len(sorted_pairs) - num_shown} пар: {up_count}↑ {down_count}↓\n"

    summary += f"\nНа основе этих данных дай рекомендации в JSON-формате."

    return system, summary


# ── Обновление ai_params.json ────────────────────────────────

def update_ai_params(llm_response: str, market_data: dict) -> bool:
    """Распарсить ответ LLM и обновить ai_params.json."""
    try:
        # Извлекаем JSON из ответа
        text = llm_response.strip()
        # Ищем JSON в ответе (между { и })
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]
        else:
            log(f"No JSON found in LLM response: {text[:200]}")
            return False

        rec = json.loads(text)

        # Текущие параметры
        if AI_PARAMS_PATH.exists():
            with open(AI_PARAMS_PATH) as f:
                params = json.load(f)
        else:
            params = {
                "stoploss": -0.035,
                "position_size_pct": 1.0,
                "market_regime": "neutral",
                "confidence_threshold": 0.65,
                "_version": 2,
            }

        # Обновляем из рекомендации (с защитой от консервативных значений)
        if "market_regime" in rec:
            params["market_regime"] = rec["market_regime"]
        if "stoploss_recommendation" in rec:
            params["stoploss"] = max(-0.08, min(-0.01, float(rec["stoploss_recommendation"])))
        if "position_size_pct" in rec:
            # Не даём ставить меньше 50% — иначе смысла нет
            params["position_size_pct"] = max(0.5, min(1.0, float(rec["position_size_pct"])))
        if "confidence_threshold" in rec:
            # Не даём ставить выше 0.6 — иначе входов не будет
            params["confidence_threshold"] = max(0.2, min(0.6, float(rec["confidence_threshold"])))
        if "reasoning" in rec:
            params["reasoning"] = rec["reasoning"]

        # AI-сигнал для прямого управления стратегией
        if "ai_signal" in rec:
            allowed_signals = {"buy", "sell", "hold"}
            if rec["ai_signal"] in allowed_signals:
                params["ai_signal"] = rec["ai_signal"]
        if "recommended_pairs" in rec and isinstance(rec["recommended_pairs"], list):
            params["recommended_pairs"] = rec["recommended_pairs"]
        if "avoid_pairs" in rec and isinstance(rec["avoid_pairs"], list):
            params["avoid_pairs"] = rec["avoid_pairs"]
        if "action" in rec:
            params["action"] = rec["action"]

        params["_updated_at"] = datetime.now().isoformat()
        params["_version"] = 4

        with open(AI_PARAMS_PATH, "w") as f:
            json.dump(params, f, indent=2)

        log(f"✅ AI params updated: regime={params.get('market_regime')}, "
            f"sl={params.get('stoploss')}, size={params.get('position_size_pct')}")
        return True

    except json.JSONDecodeError as e:
        log(f"JSON parse error: {e}")
        log(f"Raw response: {llm_response[:300]}")
        return False
    except Exception as e:
        log(f"Update error: {e}")
        return False


# ── Основной цикл ────────────────────────────────────────────

def run_analysis():
    """Один полный цикл анализа."""
    log("=" * 50)
    log("Starting market analysis...")

    data = collect_market_data()

    if not data["whitelist"]:
        log("⚠️  No whitelist data — Freqtrade API may be down")
        return False

    # Собираем свечные данные с Binance
    candle_data = collect_candle_data(data["whitelist"])

    system_prompt, market_summary = build_market_prompt(data, candle_data)

    log("Sending to Ollama for analysis...")
    response = ollama_chat(market_summary, system=system_prompt)

    if not response:
        log("⚠️  No response from Ollama")
        return False

    log(f"LLM response received ({len(response)} chars)")

    success = update_ai_params(response, data)
    return success


def sleep_until_next_candle():
    """Синхронизация со свечами: просыпаемся через 2 мин после закрытия свечи.

    Таймфрейм 15m → свечи закрываются в :00/:15/:30/:45.
    Запускаем анализ в :02/:17/:32/:47 — даём время данным обновиться.
    """
    now = time.time()
    local = time.localtime(now)
    minutes = local.tm_min
    seconds = local.tm_sec

    # Следующее время запуска: (:02, :17, :32, :47)
    next_slot = ((minutes // 15) * 15 + 2) % 60
    if minutes % 15 >= 2:
        next_slot = ((minutes // 15 + 1) * 15 + 2) % 60

    # Секунд до следующего слота
    delay = (next_slot - minutes) * 60 - seconds
    if delay <= 0:
        delay += 15 * 60  # +1 период если уже прошли

    log(f"Next analysis at :{next_slot:02d}:00 (in {delay // 60}m {delay % 60}s)")
    time.sleep(delay)


def run_daemon():
    """Бесконечный цикл, синхронизированный с закрытием свечей (15m)."""
    log(f"🚀 AI Agent daemon started, synced to {TIMEFRAME_MINUTES}m candles")
    while True:
        try:
            run_analysis()
        except Exception as e:
            log(f"Error in analysis cycle: {e}")

        sleep_until_next_candle()


def run_chat():
    """Интерактивный режим — задаём вопросы Qwen про рынок."""
    log("💬 AI Chat mode — задавай вопросы про рынок (exit/q для выхода)")
    log("  Примеры: 'какой сейчас рынок?', 'что делать с SYN?', 'оцени риск'")
    print()

    # Сначала собираем данные
    data = collect_market_data()
    _, market_summary = build_market_prompt(data)
    context = f"Вот текущие данные рынка:\n{market_summary}\n\n"

    while True:
        try:
            question = input("You: ").strip()
            if question.lower() in ("exit", "q", "quit"):
                break

            prompt = context + f"Вопрос: {question}\n\nОтветь кратко, по делу."
            response = ollama_chat(prompt)

            print(f"\n🤖 Qwen: {response}\n")

        except KeyboardInterrupt:
            break
        except EOFError:
            break


# ── Точка входа ──────────────────────────────────────────────

if __name__ == "__main__":
    log("🤖 AI Agent for Freqtrade starting...")

    if "--once" in sys.argv:
        run_analysis()
    elif "--daemon" in sys.argv:
        run_daemon()
    else:
        # По умолчанию: один анализ + показать результат
        run_analysis()
        print(f"\n📄 ai_params.json updated. Check logs: {LOG_PATH}")
        if AI_PARAMS_PATH.exists():
            print(f"\nCurrent AI params:")
            with open(AI_PARAMS_PATH) as f:
                print(f.read())
