"""
Outcome Tracker — логирование предсказаний LSTM и сравнение с реальностью.

Каждое предсказание сохраняется в SQLite. Через N свечей проверяем:
совпало ли предсказание с реальным движением цены.

Данные используются для:
1. Оценки точности модели
2. Автоматического ретрейнинга
3. Обучения RL-агента (награда за правильные предсказания)
"""

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DB_PATH = Path(__file__).parent / "data" / "outcomes.db"


def _ensure_db():
    """Создать таблицы если нет."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            pair TEXT NOT NULL,
            prediction TEXT NOT NULL,
            confidence REAL NOT NULL,
            features_json TEXT,
            current_price REAL,
            seq_len INTEGER DEFAULT 20,
            -- Actual outcome (filled later)
            outcome_checked INTEGER DEFAULT 0,
            outcome_timestamp REAL,
            price_at_check REAL,
            price_change_pct REAL,
            correct INTEGER,
            reward REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS training_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            model_path TEXT,
            pairs_used INTEGER,
            candles_used INTEGER,
            train_accuracy REAL,
            val_accuracy REAL,
            old_accuracy REAL,
            improvement REAL,
            deployed INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_pred_pair ON predictions(pair)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_pred_unchecked ON predictions(outcome_checked)
    """)
    conn.commit()
    conn.close()


class OutcomeTracker:
    """Логирование и анализ предсказаний LSTM."""

    def __init__(self, check_delay_candles: int = 4):
        """
        Args:
            check_delay_candles: Через сколько свечей проверять результат.
                4 свечи × 15м = 1 час — достаточно для оценки направления.
        """
        self.check_delay = check_delay_candles
        _ensure_db()
        self.conn = sqlite3.connect(str(DB_PATH), timeout=10)
        # WAL mode для параллельного доступа
        self.conn.execute("PRAGMA journal_mode=WAL")

    def log_prediction(self, pair: str, prediction: str, confidence: float,
                       current_price: float, features: dict = None):
        """Сохранить предсказание LSTM."""
        features_json = json.dumps(features) if features else None
        self.conn.execute(
            "INSERT INTO predictions (timestamp, pair, prediction, confidence, "
            "features_json, current_price) VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), pair, prediction, confidence, features_json, current_price)
        )
        self.conn.commit()

    def check_outcomes(self, get_current_price_fn) -> list:
        """
        Проверить результаты предсказаний, которым «вышло время».
        
        Args:
            get_current_price_fn: callable(pair) -> float — получить текущую цену.
        
        Returns:
            list of checked outcomes
        """
        # Найти предсказания, которым пора проверять результат
        # (прошло >= check_delay свечей, но ещё не проверены)
        min_age = time.time() - (self.check_delay * 15 * 60)  # 15м = свеча
        cursor = self.conn.execute(
            "SELECT id, pair, prediction, confidence, current_price, timestamp "
            "FROM predictions WHERE outcome_checked = 0 AND timestamp < ?",
            (min_age,)
        )
        rows = cursor.fetchall()
        
        checked = []
        for row_id, pair, prediction, confidence, pred_price, pred_ts in rows:
            try:
                current_price = get_current_price_fn(pair)
            except Exception:
                continue
            
            # Вычисляем изменение цены
            if pred_price > 0:
                change_pct = (current_price - pred_price) / pred_price
            else:
                change_pct = 0.0
            
            # Определяем: предсказание верное?
            # buy → цена выросла, sell → цена упала, hold → цена не сильно изменилась
            #
            # КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: сбалансированные награды
            # Чтобы модель не выучила "всегда hold", нужно:
            # - Давать hold только если рына действительно не двигается
            # - Штрафовать hold если рынок движется в одну сторону
            # - Давать buy/sell пропорционально успеху
            
            if prediction == "buy":
                correct = 1 if change_pct > 0.005 else 0
                if change_pct > 0.02:     # >2% рост — отличный buy
                    reward = 2.0
                elif change_pct > 0.005:  # >0.5% — правильный buy
                    reward = 1.0 + change_pct * 20
                elif change_pct > -0.005: #flat — не катастрофа
                    reward = 0.0
                else:                      # падение — неправильный buy
                    reward = -1.0 + change_pct * 10
            elif prediction == "sell":
                correct = 1 if change_pct < -0.005 else 0
                if change_pct < -0.02:    # >2% падение — отличный sell
                    reward = 2.0
                elif change_pct < -0.005:  # >0.5% — правильный sell
                    reward = 1.0 + (-change_pct) * 20
                elif change_pct < 0.005:  # flat — не катастрофа
                    reward = 0.0
                else:                      # рост — неправильный sell
                    reward = -1.0 - change_pct * 10
            else:  # hold
                # Штрафуем hold если рынок сильно двигается
                # (модель должна замечать тренды!)
                if abs(change_pct) < 0.005:   # <0.5% — правильный hold
                    correct = 1
                    reward = 0.5
                elif abs(change_pct) < 0.01:  # 0.5-1% — приемлемо
                    correct = 1
                    reward = 0.2
                else:                          # >1% — неправильный hold!
                    correct = 0
                    reward = -0.5  # штраф за пропущенный тренд
            
            self.conn.execute(
                "UPDATE predictions SET outcome_checked=1, outcome_timestamp=?, "
                "price_at_check=?, price_change_pct=?, correct=?, reward=? "
                "WHERE id=?",
                (time.time(), current_price, change_pct, correct, reward, row_id)
            )
            
            checked.append({
                "pair": pair,
                "prediction": prediction,
                "confidence": confidence,
                "change_pct": change_pct,
                "correct": correct,
                "reward": reward,
            })
        
        self.conn.commit()
        return checked

    def get_accuracy(self, days: int = 7) -> dict:
        """Получить статистику точности за N дней."""
        since = time.time() - (days * 86400)
        cursor = self.conn.execute(
            "SELECT prediction, correct, reward FROM predictions "
            "WHERE outcome_checked = 1 AND timestamp > ?",
            (since,)
        )
        rows = cursor.fetchall()
        
        if not rows:
            return {"total": 0, "accuracy": 0.0, "avg_reward": 0.0}
        
        stats = {"total": len(rows), "by_type": {}}
        for pred, correct, reward in rows:
            if pred not in stats["by_type"]:
                stats["by_type"][pred] = {"total": 0, "correct": 0, "rewards": []}
            stats["by_type"][pred]["total"] += 1
            stats["by_type"][pred]["correct"] += correct
            stats["by_type"][pred]["rewards"].append(reward)
        
        total_correct = sum(s["correct"] for s in stats["by_type"].values())
        stats["accuracy"] = total_correct / len(rows) if rows else 0.0
        stats["avg_reward"] = sum(
            sum(s["rewards"]) for s in stats["by_type"].values()
        ) / len(rows) if rows else 0.0
        
        for pred_type, s in stats["by_type"].items():
            s["accuracy"] = s["correct"] / s["total"] if s["total"] > 0 else 0.0
            s["avg_reward"] = sum(s["rewards"]) / len(s["rewards"]) if s["rewards"] else 0.0
        
        return stats

    def get_training_data(self, min_days: int = 3) -> list:
        """
        Получить проверенные предсказания для обучения RL-агента.
        Возвращает данные с полными фичами и наградами.
        """
        since = time.time() - (min_days * 86400)
        cursor = self.conn.execute(
            "SELECT pair, prediction, confidence, features_json, "
            "current_price, price_at_check, price_change_pct, reward "
            "FROM predictions WHERE outcome_checked = 1 AND timestamp > ? "
            "AND features_json IS NOT NULL",
            (since,)
        )
        rows = cursor.fetchall()
        
        data = []
        for (pair, pred, conf, features_json, price_start, price_end,
             change_pct, reward) in rows:
            features = json.loads(features_json) if features_json else {}
            data.append({
                "pair": pair,
                "prediction": pred,
                "confidence": conf,
                "features": features,
                "price_start": price_start,
                "price_end": price_end,
                "change_pct": change_pct,
                "reward": reward,
            })
        
        return data

    def log_training_run(self, model_path: str, pairs_used: int,
                         candles_used: int, train_acc: float, val_acc: float,
                         old_acc: float = None):
        """Логировать результат ретрейнинга."""
        improvement = (val_acc - old_acc) if old_acc is not None else None
        self.conn.execute(
            "INSERT INTO training_runs (timestamp, model_path, pairs_used, "
            "candles_used, train_accuracy, val_accuracy, old_accuracy, improvement) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (time.time(), model_path, pairs_used, candles_used,
             train_acc, val_acc, old_acc, improvement)
        )
        self.conn.commit()

    def get_pending_predictions_count(self) -> int:
        """Количество непроверенных предсказаний."""
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM predictions WHERE outcome_checked = 0"
        )
        return cursor.fetchone()[0]

    def get_total_predictions(self) -> int:
        """Общее количество предсказаний."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM predictions")
        return cursor.fetchone()[0]

    def close(self):
        self.conn.close()


# Singleton
_tracker_instance = None


def get_tracker() -> OutcomeTracker:
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = OutcomeTracker()
    return _tracker_instance


def reset_tracker():
    global _tracker_instance
    if _tracker_instance:
        _tracker_instance.close()
    _tracker_instance = None
