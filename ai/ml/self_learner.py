"""
Self-Learning Orchestrator — координирует весь цикл самообучения.

Запускается как daemon на Raspberry Pi.
Цикл:
1. Каждые 15 минут: собирает предсказания LSTM + RL
2. Каждый час: проверяет результаты предсказаний
3. Каждые 3 дня: запускает ретрейнинг на PC (через SSH)
4. Непрерывно: обновляет RL модель на основе наград

Запуск:
    python -m ai.ml.self_learner --daemon
    python -m ai.ml.self_learner --status
    python -m ai.ml.self_learner --check-outcomes
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

# ── Imports ────────────────────────────────────────────────
try:
    from ai.ml.outcome_tracker import get_tracker
    from ai.ml.rl_agent import get_rl_trader, load_rl_model
    from ai.ml.predictor import get_predictor, reset_predictor
    from ai.ml.candle_features import extract_features, normalize_features
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from ai.ml.outcome_tracker import get_tracker
    from ai.ml.rl_agent import get_rl_trader, load_rl_model
    from ai.ml.predictor import get_predictor, reset_predictor
    from ai.ml.candle_features import extract_features, normalize_features

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ── Config ─────────────────────────────────────────────────
CONFIG_PATH = Path("/freqtrade/user_data/ai_params.json")
PI_HOST = os.environ.get("PI_HOST", "user@100.109.236.50")
PC_HOST = os.environ.get("PC_HOST", "dima@100.109.236.1")  # Tailscale IP
LOG_PATH = Path(__file__).parent / "data" / "self_learner.log"
INTERVAL_CHECK_OUTCOMES = 3600      # 1 час
INTERVAL_RETRAIN = 3 * 86400        # 3 дня
INTERVAL_LOG_STATUS = 300            # 5 минут


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
# PRICE FETCHER
# ═══════════════════════════════════════════════════════════

def get_current_price(pair: str) -> float:
    """Получить текущую цену пары через Binance API."""
    if not HAS_REQUESTS:
        raise RuntimeError("requests not installed")
    
    url = f"https://api.binance.com/api/v3/ticker/price"
    resp = requests.get(url, params={"symbol": pair.replace("/", "")}, timeout=10)
    resp.raise_for_status()
    return float(resp.json()["price"])


def get_current_prices(pairs: list) -> dict:
    """Получить цены для всех пар."""
    result = {}
    for pair in pairs:
        try:
            result[pair] = get_current_price(pair)
        except Exception as e:
            log(f"⚠️  Price fetch failed for {pair}: {e}")
    return result


# ═══════════════════════════════════════════════════════════
# SELF-LEARNING CYCLE
# ═══════════════════════════════════════════════════════════

class SelfLearner:
    """Оркестратор цикла самообучения."""

    def __init__(self):
        self.tracker = get_tracker()
        self.rl_trader = get_rl_trader()
        self.predictor = get_predictor()
        
        self._last_outcome_check = 0.0
        self._last_retrain_check = 0.0
        self._last_status_log = 0.0
        self._running = True
        
        # Pair list from ai_params
        self.pairs = self._load_pairs()
        
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        log(f"🛑 Signal {signum} received, shutting down...")
        self._running = False
    
    def _load_pairs(self) -> list:
        """Загрузить список пар из конфига."""
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH) as f:
                    params = json.load(f)
                pairs = params.get("recommended_pairs", [])
                if pairs:
                    return pairs
        except Exception:
            pass
        # Fallback: основные пары
        return ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT",
                "DOGE/USDT", "PEPE/USDT", "SHIB/USDT", "ADA/USDT"]

    # ── Phase 1: Outcome Tracking ──────────────────────────

    def check_outcomes(self):
        """Проверить результаты предсказаний."""
        log("🔍 Checking prediction outcomes...")
        
        try:
            checked = self.tracker.check_outcomes(get_current_price)
            if checked:
                correct = sum(1 for c in checked if c["correct"])
                total = len(checked)
                log(f"  📊 Checked {total} predictions: {correct}/{total} "
                    f"correct ({correct/total*100:.0f}%)")
                
                # Записываем награды в RL буфер
                for c in checked:
                    try:
                        self.rl_trader.record_reward(
                            c["pair"], c["reward"], done=True
                        )
                    except Exception:
                        pass
            else:
                log("  No outcomes ready to check yet")
        except Exception as e:
            log(f"  ❌ Error checking outcomes: {e}")
        
        self._last_outcome_check = time.time()

    # ── Phase 2: RL Learning ───────────────────────────────

    def update_rl(self):
        """Обновить RL модель на основе накопленных наград."""
        if not self.rl_trader.available:
            return
        
        status = self.rl_trader.get_status()
        if status["experiences"] < 100:
            return
        
        log(f"🧠 RL update: {status['experiences']} experiences, "
            f"epsilon={status['epsilon']:.3f}")
        
        # Уменьшаем epsilon со временем
        if self.rl_trader.epsilon > 0.05:
            self.rl_trader.epsilon *= 0.995

    # ── Phase 3: Auto-Retraining ───────────────────────────

    def check_retrain_needed(self):
        """Проверить, пора ли переобучать модель."""
        if time.time() - self._last_retrain_check < INTERVAL_RETRAIN:
            return
        
        self._last_retrain_check = time.time()
        
        # Проверяем точность текущей модели
        accuracy = self.tracker.get_accuracy(days=7)
        if accuracy["total"] < 50:
            log(f"  Not enough data for retrain: {accuracy['total']} predictions")
            return
        
        if accuracy["accuracy"] > 0.6:
            log(f"  Model accuracy OK ({accuracy['accuracy']:.1%}), no retrain needed")
            return
        
        log(f"📉 Model accuracy low ({accuracy['accuracy']:.1%}), "
            f"scheduling retrain...")
        self._trigger_retrain()

    def _trigger_retrain(self):
        """Запустить ретрейнинг через SSH на PC."""
        log("🚀 Triggering remote retrain on PC...")
        try:
            # SSH command to PC
            cmd = (
                f"ssh {PC_HOST} "
                f"'cd /home/dima/Документы/PlatformIO/Projects/ai-trader && "
                f"python -m ai.ml.retrain "
                f"--pairs BTC/USDT,ETH/USDT,SOL/USDT,XRP/USDT "
                f"--epochs 50 --auto'"
            )
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=600
            )
            if result.returncode == 0:
                log(f"  ✅ Retrain completed")
                # Перезагрузить модель
                reset_predictor()
                log("  🔄 Model reloaded")
            else:
                log(f"  ❌ Retrain failed: {result.stderr[:200]}")
        except Exception as e:
            log(f"  ❌ Retrain error: {e}")

    # ── Status & Monitoring ────────────────────────────────

    def log_status(self):
        """Логировать текущий статус."""
        try:
            # Prediction accuracy
            acc = self.tracker.get_accuracy(days=7)
            pending = self.tracker.get_pending_predictions_count()
            total = self.tracker.get_total_predictions()
            
            # RL status
            rl_status = self.rl_trader.get_status()
            
            log(f"📊 Status: {total} predictions ({pending} pending), "
                f"accuracy={acc.get('accuracy', 0):.1%}, "
                f"avg_reward={acc.get('avg_reward', 0):+.3f}, "
                f"RL_experiences={rl_status['experiences']}, "
                f"epsilon={rl_status['epsilon']:.3f}")
        except Exception as e:
            log(f"  Status error: {e}")
        
        self._last_status_log = time.time()

    # ── Main Loop ──────────────────────────────────────────

    def run(self):
        """Главный цикл."""
        log("🚀 Self-Learner started")
        log(f"  Pairs: {self.pairs}")
        log(f"  RL model: {'loaded' if self.rl_trader.available else 'not loaded'}")
        log(f"  Retrain interval: {INTERVAL_RETRAIN/86400:.0f} days")
        
        while self._running:
            now = time.time()
            
            # Check outcomes (каждый час)
            if now - self._last_outcome_check >= INTERVAL_CHECK_OUTCOMES:
                self.check_outcomes()
            
            # RL update (каждые 15 минут)
            self.update_rl()
            
            # Retrain check (каждые 3 дня)
            self.check_retrain_needed()
            
            # Status log (каждые 5 минут)
            if now - self._last_status_log >= INTERVAL_LOG_STATUS:
                self.log_status()
            
            # Sleep
            time.sleep(60)
        
        log("👋 Self-Learner stopped")
        self.rl_trader.close()
        self.tracker.close()


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Self-Learning Orchestrator")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon")
    parser.add_argument("--status", action="store_true", help="Show status")
    parser.add_argument("--check-outcomes", action="store_true",
                        help="Check outcomes now")
    parser.add_argument("--retrain", action="store_true",
                        help="Force retrain now")
    args = parser.parse_args()
    
    if args.status:
        tracker = get_tracker()
        acc = tracker.get_accuracy(days=7)
        pending = tracker.get_pending_predictions_count()
        total = tracker.get_total_predictions()
        
        rl = get_rl_trader()
        rl_status = rl.get_status()
        
        print(f"📊 Self-Learning Status")
        print(f"  Predictions: {total} total, {pending} pending")
        print(f"  Accuracy (7d): {acc.get('accuracy', 0):.1%}")
        print(f"  Avg Reward (7d): {acc.get('avg_reward', 0):+.3f}")
        print(f"  By type:")
        for pred_type, stats in acc.get("by_type", {}).items():
            print(f"    {pred_type}: {stats['accuracy']:.1%} "
                  f"({stats['correct']}/{stats['total']})")
        print(f"  RL Agent: loaded={rl_status['model_loaded']}, "
              f"experiences={rl_status['experiences']}, "
              f"epsilon={rl_status['epsilon']:.3f}")
        return
    
    if args.check_outcomes:
        tracker = get_tracker()
        checked = tracker.check_outcomes(get_current_price)
        print(f"Checked {len(checked)} outcomes")
        for c in checked:
            print(f"  {c['pair']}: {c['prediction']} → "
                  f"{'✅' if c['correct'] else '❌'} "
                  f"({c['change_pct']:+.2%}, reward={c['reward']:+.3f})")
        return
    
    if args.retrain:
        learner = SelfLearner()
        learner._trigger_retrain()
        return
    
    if args.daemon:
        learner = SelfLearner()
        learner.run()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
