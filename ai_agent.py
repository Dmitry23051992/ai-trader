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
from datetime import datetime, timedelta
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

# ── Журнал решений AI ────────────────────────────────────────
DECISION_LOG_PATH = Path("/home/user/ai-trader/freqtrade/user_data/ai_decision_log.jsonl")
MAX_HISTORY_DAYS = 14  # сколько дней хранить историю решений

# ── Multi-LLM совет ─────────────────────────────────────────
# Включить/выключить совет директоров (3 голоса: бык, медведь, стратег)
USE_COUNCIL = os.getenv("AI_USE_COUNCIL", "true").lower() in ("true", "1", "yes")


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


# ── Журнал решений AI ──────────────────────────────────────

def log_decision(params: dict, market_data: dict) -> str:
    """Записать решение AI в лог для последующей оценки.

    Сохраняет: timestamp, принятые параметры, снапшот рынка (баланс, открытые сделки).
    Возвращает decision_id для отслеживания.
    """
    import uuid
    decision_id = str(uuid.uuid4())[:8]
    entry = {
        "_decision_id": decision_id,
        "timestamp": datetime.now().isoformat(),
        "params": {
            "market_regime": params.get("market_regime"),
            "ai_signal": params.get("ai_signal"),
            "stoploss": params.get("stoploss"),
            "position_size_pct": params.get("position_size_pct"),
            "confidence_threshold": params.get("confidence_threshold"),
            "recommended_pairs": params.get("recommended_pairs", []),
            "avoid_pairs": params.get("avoid_pairs", []),
            "action": params.get("action"),
        },
        "market_snapshot": {
            "total_usdt": market_data.get("balance", {}).get("total_usdt", 0),
            "free_usdt": market_data.get("balance", {}).get("free_usdt", 0),
            "profit_pct": market_data.get("balance", {}).get("profit_pct", 0),
            "open_trades_count": len(market_data.get("open_trades", [])),
            "open_trades_pairs": [t["pair"] for t in market_data.get("open_trades", [])],
        },
        "outcome": None,  # будет заполнен позже evaluate_decision_log
    }

    try:
        DECISION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DECISION_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
        log(f"📝 Decision {decision_id} logged")
    except Exception as e:
        log(f"⚠️  Could not write decision log: {e}")

    return decision_id


def evaluate_decision_log() -> dict:
    """Анализировать историю решений AI: какие рекомендации дали профит, какие — убыток.

    Читает лог решений и закрытые сделки из Freqtrade API,
    сопоставляет их по времени и вычисляет метрики качества.
    """
    import json as j

    if not DECISION_LOG_PATH.exists():
        return {}

    # Читаем лог решений
    decisions = []
    with open(DECISION_LOG_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    decisions.append(j.loads(line))
                except Exception:
                    continue

    if not decisions:
        return {}

    # Фильтруем последние MAX_HISTORY_DAYS
    cutoff = time.time() - MAX_HISTORY_DAYS * 86400
    recent = []
    for d in decisions:
        try:
            ts = datetime.fromisoformat(d["timestamp"]).timestamp()
            if ts >= cutoff:
                recent.append(d)
        except Exception:
            continue

    if not recent:
        return {}

    # Получаем закрытые сделки
    trades_data = api_get("/api/v1/trades?limit=100") or {"trades": []}
    closed_trades = [t for t in trades_data.get("trades", []) if not t.get("is_open", True)]

    # Сопоставляем: для каждой закрытой сделки находим решение AI,
    # которое было активно на момент входа
    matched_trades = []
    for trade in closed_trades:
        try:
            open_timestamp = datetime.fromisoformat(trade["open_date"].replace("Z", "+00:00")).timestamp()
        except Exception:
            continue

        # Ищем решение, принятое незадолго до входа в сделку (в пределах 6 часов)
        best_decision = None
        best_diff = float("inf")
        for d in recent:
            try:
                dt = datetime.fromisoformat(d["timestamp"]).timestamp()
                diff = open_timestamp - dt
                if 0 <= diff <= 6 * 3600 and diff < best_diff:
                    best_decision = d
                    best_diff = diff
            except Exception:
                continue

        if best_decision:
            matched_trades.append({
                "pair": trade.get("pair", ""),
                "profit_pct": trade.get("profit_pct", 0),
                "profit_abs": trade.get("profit_abs", 0),
                "exit_reason": trade.get("exit_reason", "?"),
                "open_date": trade.get("open_date", ""),
                "decision_params": best_decision.get("params", {}),
                "decision_timestamp": best_decision.get("timestamp", ""),
            })

    # Вычисляем метрики
    metrics = {}

    # 1. Winrate по ai_signal
    for signal in ["buy", "hold", "sell"]:
        trades_with_signal = [t for t in matched_trades if t["decision_params"].get("ai_signal") == signal]
        if trades_with_signal:
            wins = sum(1 for t in trades_with_signal if t["profit_pct"] > 0)
            avg_profit = sum(t["profit_pct"] for t in trades_with_signal) / len(trades_with_signal)
            metrics[f"winrate_signal_{signal}"] = {
                "trades": len(trades_with_signal),
                "wins": wins,
                "winrate_pct": round(wins / len(trades_with_signal) * 100, 1),
                "avg_profit_pct": round(avg_profit, 2),
                "total_profit_pct": round(sum(t["profit_pct"] for t in trades_with_signal), 2),
            }

    # 2. Winrate по regime
    for regime in ["bullish", "neutral", "bearish", "panic"]:
        trades_with_regime = [t for t in matched_trades if t["decision_params"].get("market_regime") == regime]
        if trades_with_regime:
            wins = sum(1 for t in trades_with_regime if t["profit_pct"] > 0)
            avg_profit = sum(t["profit_pct"] for t in trades_with_regime) / len(trades_with_regime)
            metrics[f"winrate_regime_{regime}"] = {
                "trades": len(trades_with_regime),
                "wins": wins,
                "winrate_pct": round(wins / len(trades_with_regime) * 100, 1),
                "avg_profit_pct": round(avg_profit, 2),
            }

    # 3. Эффективность recommended_pairs
    rec_pair_outcomes = {}
    for t in matched_trades:
        rec_pairs = t["decision_params"].get("recommended_pairs", [])
        pair = t["pair"]
        if pair not in rec_pair_outcomes:
            rec_pair_outcomes[pair] = {"recommended_as_top": 0, "not_recommended": 0, "profit_sum": 0.0, "trades": 0}
        rec_pair_outcomes[pair]["trades"] += 1
        rec_pair_outcomes[pair]["profit_sum"] += t["profit_pct"]
        if pair in rec_pairs:
            rec_pair_outcomes[pair]["recommended_as_top"] += 1
        else:
            rec_pair_outcomes[pair]["not_recommended"] += 1

    metrics["pair_recommendation_effectiveness"] = rec_pair_outcomes

    # 4. Общие метрики
    if matched_trades:
        all_wins = sum(1 for t in matched_trades if t["profit_pct"] > 0)
        metrics["overall"] = {
            "total_trades_evaluated": len(matched_trades),
            "total_wins": all_wins,
            "overall_winrate_pct": round(all_wins / len(matched_trades) * 100, 1),
            "total_profit_pct": round(sum(t["profit_pct"] for t in matched_trades), 2),
            "avg_profit_pct": round(sum(t["profit_pct"] for t in matched_trades) / len(matched_trades), 2),
            "best_trade_pct": round(max(t["profit_pct"] for t in matched_trades), 2),
            "worst_trade_pct": round(min(t["profit_pct"] for t in matched_trades), 2),
        }

    # Обновляем лог: помечаем у каких решений есть outcome
    _update_decision_outcomes(matched_trades, recent)

    log(f"📊 Decision evaluation: {metrics.get('overall', {}).get('total_trades_evaluated', 0)} trades matched "
        f"to {len(recent)} decisions. "
        f"Winrate: {metrics.get('overall', {}).get('overall_winrate_pct', '?')}%")

    return metrics


def _update_decision_outcomes(matched_trades: list, decisions: list):
    """Обновить лог решений: добавить outcome для решений, по которым были сделки."""
    try:
        lines = []
        updated_count = 0
        with open(DECISION_LOG_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    # Ищем сделки, соответствующие этому решению
                    dec_ts = entry.get("timestamp", "")
                    matching_trades = [
                        t for t in matched_trades
                        if t.get("decision_timestamp") == dec_ts
                    ]
                    if matching_trades:
                        profits = [t["profit_pct"] for t in matching_trades]
                        entry["outcome"] = {
                            "trades_count": len(matching_trades),
                            "avg_profit_pct": round(sum(profits) / len(profits), 2),
                            "total_profit_pct": round(sum(profits), 2),
                            "wins": sum(1 for p in profits if p > 0),
                            "pairs": [t["pair"] for t in matching_trades],
                        }
                        updated_count += 1
                    lines.append(json.dumps(entry))
                except Exception:
                    lines.append(line)

        with open(DECISION_LOG_PATH, "w") as f:
            f.write("\n".join(lines) + "\n")

        if updated_count:
            log(f"📝 Updated {updated_count} decisions with outcomes")
    except Exception as e:
        log(f"⚠️  Could not update outcomes: {e}")


def build_feedback_section(evaluation: dict) -> str:
    """Сформировать секцию feedback для промпта — как сработали прошлые рекомендации AI."""
    if not evaluation:
        return ""

    parts = ["=== ОЦЕНКА ПРЕДЫДУЩИХ РЕШЕНИЙ AI ==="]

    overall = evaluation.get("overall", {})
    if overall:
        parts.append(
            f"Всего оценено сделок: {overall.get('total_trades_evaluated', 0)} | "
            f"Winrate: {overall.get('overall_winrate_pct', '?')}% | "
            f"Общий P&L: {overall.get('total_profit_pct', 0):+.2f}% | "
            f"Средняя сделка: {overall.get('avg_profit_pct', 0):+.2f}%"
        )
        parts.append(
            f"Лучшая: {overall.get('best_trade_pct', 0):+.2f}% | "
            f"Худшая: {overall.get('worst_trade_pct', 0):+.2f}%"
        )

    # Winrate по сигналам
    signal_lines = []
    for signal in ["buy", "hold", "sell"]:
        key = f"winrate_signal_{signal}"
        if key in evaluation:
            s = evaluation[key]
            signal_lines.append(
                f"  ai_signal={signal}: {s['trades']} сделок, "
                f"winrate={s['winrate_pct']}%, "
                f"средняя={s['avg_profit_pct']:+.2f}%"
            )
    if signal_lines:
        parts.append("По сигналам:")
        parts.extend(signal_lines)

    # Winrate по режиму
    regime_lines = []
    for regime in ["bullish", "neutral", "bearish", "panic"]:
        key = f"winrate_regime_{regime}"
        if key in evaluation:
            r = evaluation[key]
            regime_lines.append(
                f"  regime={regime}: {r['trades']} сделок, "
                f"winrate={r['winrate_pct']}%, "
                f"средняя={r['avg_profit_pct']:+.2f}%"
            )
    if regime_lines:
        parts.append("По режимам рынка:")
        parts.extend(regime_lines)

    # Эффективность рекомендованных пар
    pair_eff = evaluation.get("pair_recommendation_effectiveness", {})
    if pair_eff:
        best_rec = []
        worst_missed = []
        for pair, stats in pair_eff.items():
            total = stats["trades"]
            if total >= 2:
                if stats["recommended_as_top"] > 0 and stats["profit_sum"] > 0:
                    best_rec.append((pair, stats["profit_sum"] / total))
                elif stats["not_recommended"] > 0 and stats["profit_sum"] > 5:
                    worst_missed.append((pair, stats["profit_sum"] / total))

        if best_rec:
            best_rec.sort(key=lambda x: x[1], reverse=True)
            parts.append("Лучшие рекомендованные пары: " +
                         ", ".join(f"{p} ({v:+.2f}%/сд)" for p, v in best_rec[:3]))
        if worst_missed:
            worst_missed.sort(key=lambda x: x[1], reverse=True)
            parts.append("⚠️ Пропущенный профит (не рекомендовал, но пара выросла): " +
                         ", ".join(f"{p} ({v:+.2f}%/сд)" for p, v in worst_missed[:3]))

    parts.append("")
    return "\n".join(parts)


# ── Multi-LLM Совет Директоров ─────────────────────────────

def _council_persona(name: str, instruction: str) -> str:
    """Сформировать system prompt для одного советника."""
    return f"""Ты — {name} в совете AI-трейдеров. Твоя задача — анализировать рынок с точки зрения {name.lower()}.

{instruction}

Отвечай ТОЛЬКО в JSON-формате:
{{
  "market_regime": "bullish" | "neutral" | "bearish" | "panic",
  "ai_signal": "buy" | "sell" | "hold",
  "confidence_threshold": 0.0-1.0,
  "position_size_pct": 0.0-1.0,
  "stoploss_recommendation": -0.01 to -0.08,
  "reasoning": "твоё обоснование (1 предложение)"
}}"""


def _aggregate_council_votes(responses: list[dict]) -> dict:
    """Усреднить голоса совета в единую рекомендацию.

    Использует взвешенное голосование:
    - buy = +1, hold = 0, sell = -1
    - regime: числовое представление + усреднение
    - position_size, confidence, stoploss: медианное значение
    """
    if not responses:
        return {}

    # Голосование по ai_signal
    signal_map = {"buy": 1, "hold": 0, "sell": -1}
    inv_signal = {1: "buy", 0: "hold", -1: "sell"}

    votes = []
    regime_scores = {"bullish": 2, "neutral": 1, "bearish": -1, "panic": -2}
    inv_regime = {2: "bullish", 1: "neutral", -1: "bearish", -2: "panic"}

    for r in responses:
        sig = r.get("ai_signal", "hold")
        votes.append(signal_map.get(sig, 0))

        reg = r.get("market_regime", "neutral")
        regime_scores.setdefault(reg, 0)

    avg_vote = sum(votes) / len(votes)
    final_signal = inv_signal.get(1 if avg_vote > 0.3 else (-1 if avg_vote < -0.3 else 0), "hold")

    # Режим — тоже голосование
    reg_votes = []
    for r in responses:
        reg = r.get("market_regime", "neutral")
        reg_votes.append(regime_scores.get(reg, 0))
    avg_reg = sum(reg_votes) / len(reg_votes) if reg_votes else 1
    # Ищем ближайший режим
    final_regime = min(inv_regime.keys(), key=lambda k: abs(k - avg_reg))
    final_regime = inv_regime[final_regime]

    # Медианные/средние значения
    sizes = [float(r.get("position_size_pct", 0.5)) for r in responses if r.get("position_size_pct") is not None]
    confs = [float(r.get("confidence_threshold", 0.5)) for r in responses if r.get("confidence_threshold") is not None]
    sls = [float(r.get("stoploss_recommendation", -0.035)) for r in responses if r.get("stoploss_recommendation") is not None]

    def median(arr):
        s = sorted(arr)
        return s[len(s) // 2] if s else 0.5

    # Собираем аргументы для отчёта
    all_reasoning = []
    for i, r in enumerate(responses):
        reason = r.get("reasoning", "")
        if reason:
            all_reasoning.append(f"Советник {i+1}: {reason}")

    return {
        "market_regime": final_regime,
        "ai_signal": final_signal,
        "position_size_pct": max(0.5, min(1.0, median(sizes))),
        "confidence_threshold": max(0.2, min(0.6, median(confs))),
        "stoploss_recommendation": max(-0.08, min(-0.01, median(sls))),
        "reasoning": " | ".join(all_reasoning) if all_reasoning else "Консенсус совета директоров",
        "_votes": {
            "buy": sum(1 for v in votes if v == 1),
            "hold": sum(1 for v in votes if v == 0),
            "sell": sum(1 for v in votes if v == -1),
            "avg_vote": round(avg_vote, 2),
        },
    }


def ollama_council(market_summary: str, full_context: str, feedback: str = "") -> dict:
    """Запустить совет директоров: несколько LLM-запросов с разными ролями.

    Args:
        market_summary: сводка рынка (user prompt)
        full_context: полный system prompt (уже содержит feedback если есть)
        feedback: отдельно feedback для логирования

    Возвращает агрегированную рекомендацию.
    """
    personas = [
        {
            "name": "Бычий аналитик",
            "instruction": "Твоя специализация — находить возможности для покупки. "
                          "Ты ищешь сильные тренды, растущий объём, бычьи паттерны. "
                          "Ты склонен рекомендовать buy, если нет явных признаков катастрофы. "
                          "Твой девиз: «Растущий рынок приносит деньги». "
                          "Если рынок падает — ты ищешь точки разворота."
        },
        {
            "name": "Медвежий аналитик",
            "instruction": "Твоя специализация — управление рисками и защита капитала. "
                          "Ты ищешь признаки перегрева, падающий объём, медвежьи дивергенции. "
                          "Ты склонен рекомендовать hold или sell. "
                          "Твой девиз: «Сохранить капитал важнее, чем заработать». "
                          "Даже на растущем рынке ты ищешь подтверждения."
        },
        {
            "name": "Главный стратег",
            "instruction": "Твоя задача — сбалансировать риск и доходность. "
                          "Ты анализируешь общую картину: баланс бота, P&L, количество открытых сделок. "
                          "Ты принимаешь решение на основе фактов, а не эмоций. "
                          "Ты — голос разума между быками и медведями."
        },
    ]

    log(f"🏛️  Council of {len(personas)} advisors convening...")
    responses = []

    for i, persona in enumerate(personas):
        persona_system = _council_persona(persona["name"], persona["instruction"])
        # Объединяем роль советника с полным контекстом (уже включает feedback)
        full_system = persona_system + "\n\n" + full_context

        log(f"  Consulting {persona['name']}...")
        response = ollama_chat(market_summary, system=full_system)

        if response:
            parsed = _parse_llm_json(response)
            if parsed:
                parsed["_persona"] = persona["name"]
                responses.append(parsed)
                log(f"    → {persona['name']}: signal={parsed.get('ai_signal')}, "
                    f"regime={parsed.get('market_regime')}")
            else:
                log(f"    ⚠️  {persona['name']}: could not parse JSON response")
        else:
            log(f"    ⚠️  {persona['name']}: no response")

    if not responses:
        log("⚠️  Council returned no valid responses — falling back to single LLM")
        response = ollama_chat(market_summary, system=full_context)
        return _parse_llm_json(response) or {}

    aggregated = _aggregate_council_votes(responses)
    log(f"🏛️  Council consensus: signal={aggregated.get('ai_signal')}, "
        f"regime={aggregated.get('market_regime')}, "
        f"votes={aggregated.get('_votes', {})}")
    return aggregated


def _parse_llm_json(text: str) -> dict | None:
    """Извлечь JSON из ответа LLM."""
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except Exception:
        return None
    return None


# ── Формирование промпта ────────────────────────────────────

def build_market_prompt(data: dict, candle_data: dict = None, feedback: str = "") -> tuple[str, str]:
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

        # Сохраняем результаты голосования совета (если есть)
        if "_votes" in rec:
            params["_council_votes"] = rec["_votes"]
        if "_persona" in rec:
            params["_council_persona"] = rec["_persona"]

        params["_updated_at"] = datetime.now().isoformat()
        params["_version"] = 5

        with open(AI_PARAMS_PATH, "w") as f:
            json.dump(params, f, indent=2)

        # Логируем решение для последующей оценки
        decision_id = log_decision(params, market_data)
        params["_decision_id"] = decision_id

        log(f"✅ AI params updated: regime={params.get('market_regime')}, "
            f"signal={params.get('ai_signal')}, "
            f"sl={params.get('stoploss')}, size={params.get('position_size_pct')}, "
            f"decision={decision_id}")
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
    """Один полный цикл анализа с оценкой прошлых решений и советом директоров."""
    log("=" * 50)
    log("Starting market analysis...")

    data = collect_market_data()

    if not data["whitelist"]:
        log("⚠️  No whitelist data — Freqtrade API may be down")
        return False

    # Собираем свечные данные с Binance
    candle_data = collect_candle_data(data["whitelist"])

    # ── Оценка предыдущих решений ──────────────────────────
    log("📊 Evaluating past AI decisions...")
    evaluation = evaluate_decision_log()
    feedback = build_feedback_section(evaluation)
    if feedback:
        log(f"📋 Feedback built ({len(feedback)} chars):")
        for line in feedback.split("\n")[:5]:
            if line.strip():
                log(f"  {line.strip()}")

    # ── Формируем промпт ───────────────────────────────────
    system_prompt, market_summary = build_market_prompt(data, candle_data)

    # Добавляем feedback в начало system prompt (если есть)
    if feedback:
        system_prompt = feedback + "\n\n" + system_prompt

    # ── Multi-LLM Совет Директоров ─────────────────────────
    if USE_COUNCIL:
        log("🏛️  Convening AI trading council...")
        council_result = ollama_council(market_summary, system_prompt, feedback)

        if council_result:
            # Сериализуем результат совета в JSON для update_ai_params
            response = json.dumps(council_result, ensure_ascii=False)
            log(f"🏛️  Council decision: signal={council_result.get('ai_signal')}, "
                f"regime={council_result.get('market_regime')}, "
                f"size={council_result.get('position_size_pct')}")
        else:
            log("⚠️  Council failed — falling back to single LLM")
            response = ollama_chat(market_summary, system=system_prompt)
            if not response:
                log("⚠️  No response from Ollama")
                return False
    else:
        # Режим одного советника (без совета)
        log("Sending to Ollama for analysis (single advisor)...")
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
    now = datetime.now()

    # Базовый слот в текущем 15-минутном окне: :02/:17/:32/:47
    slot_minute = (now.minute // 15) * 15 + 2
    next_run = now.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=slot_minute)

    # Если уже прошли слот, двигаем на следующий 15-минутный период.
    while next_run <= now:
        next_run += timedelta(minutes=15)

    delay = int((next_run - now).total_seconds())
    delay = max(delay, 1)

    log(
        f"Next analysis at {next_run.strftime('%H:%M:%S')} "
        f"(in {delay // 60}m {delay % 60}s)"
    )
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
