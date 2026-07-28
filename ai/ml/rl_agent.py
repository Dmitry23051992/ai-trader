"""
RL Agent — Deep Q-Network для торговых решений.

Обучается на реальных данных рынка, учится на наградах/штрафах
за правильные/неправильные решения.

Архитектура:
- State: 10 рыночных фичей + 3 фичи позиции = 13 входов
- Actions: 3 (hold=0, buy=1, sell=2)
- 2 скрытых слоя по 64 нейрона
- Numpy inference (без PyTorch на Pi)
- PyTorch training (только на PC)

Обучение:
1. Накапливаем experience из реальных сделок
2. Training на PC: replay buffer → Q-learning
3. Экспорт весов в .npz для Pi
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

import numpy as np

# ── Пути ────────────────────────────────────────────────────
MODEL_DIR = Path(__file__).parent / "models"
RL_MODEL_PATH = MODEL_DIR / "rl_dqn_v1.npz"
EXPERIENCE_DB = Path(__file__).parent / "data" / "experience.db"

# ── Константы ───────────────────────────────────────────────
STATE_SIZE = 13      # 10 market features + 3 position features
HIDDEN_SIZE = 64
ACTION_SIZE = 3      # hold, buy, sell
GAMMA = 0.95         # discount factor
EPSILON_MIN = 0.05   # минимальный epsilon (5% случайных действий)
EPSILON_DECAY = 0.995


# ═══════════════════════════════════════════════════════════
# NUMPY INFERENCE (для Raspberry Pi)
# ═══════════════════════════════════════════════════════════

class NumpyDQN:
    """DQN inference на чистом numpy — без PyTorch."""

    def __init__(self, weights: dict = None):
        if weights is None:
            weights = self._init_weights()
        self.W1 = weights["W1"]   # (STATE_SIZE, HIDDEN)
        self.b1 = weights["b1"]   # (HIDDEN,)
        self.W2 = weights["W2"]   # (HIDDEN, HIDDEN)
        self.b2 = weights["b2"]   # (HIDDEN,)
        self.W3 = weights["W3"]   # (HIDDEN, ACTION_SIZE)
        self.b3 = weights["b3"]   # (ACTION_SIZE,)

    def _init_weights(self):
        """Инициализация Xavier."""
        np.random.seed(42)
        scale1 = np.sqrt(2.0 / STATE_SIZE)
        scale2 = np.sqrt(2.0 / HIDDEN_SIZE)
        return {
            "W1": np.random.randn(STATE_SIZE, HIDDEN_SIZE).astype(np.float32) * scale1,
            "b1": np.zeros(HIDDEN_SIZE, dtype=np.float32),
            "W2": np.random.randn(HIDDEN_SIZE, HIDDEN_SIZE).astype(np.float32) * scale2,
            "b2": np.zeros(HIDDEN_SIZE, dtype=np.float32),
            "W3": np.random.randn(HIDDEN_SIZE, ACTION_SIZE).astype(np.float32) * np.sqrt(2.0 / HIDDEN_SIZE),
            "b3": np.zeros(ACTION_SIZE, dtype=np.float32),
        }

    def _relu(self, x):
        return np.maximum(0, x)

    def _softmax(self, x):
        e = np.exp(x - np.max(x))
        return e / e.sum()

    def predict(self, state: np.ndarray) -> np.ndarray:
        """Forward pass → Q-values для 3 действий."""
        h1 = self._relu(state @ self.W1 + self.b1)
        h2 = self._relu(h1 @ self.W2 + self.b2)
        q_values = h2 @ self.W3 + self.b3
        return q_values

    def get_action(self, state: np.ndarray, epsilon: float = 0.0) -> int:
        """epsilon-greedy: с вероятностью epsilon — случайное действие."""
        if np.random.random() < epsilon:
            return np.random.randint(ACTION_SIZE)
        q = self.predict(state)
        return int(np.argmax(q))

    def get_action_probs(self, state: np.ndarray) -> dict:
        """Q-values → вероятности (нормализованные)."""
        q = self.predict(state)
        probs = self._softmax(q / 0.5)  # temperature=0.5
        return {"hold": float(probs[0]), "buy": float(probs[1]), "sell": float(probs[2])}


def load_rl_model(path: str = None) -> Optional[NumpyDQN]:
    """Загрузить RL модель из .npz."""
    path = Path(path) if path else RL_MODEL_PATH
    if not path.exists():
        return None
    try:
        data = np.load(str(path))
        weights = {k: data[k] for k in ["W1", "b1", "W2", "b2", "W3", "b3"]}
        agent = NumpyDQN(weights)
        return agent
    except Exception as e:
        print(f"⚠️  RL model load error: {e}")
        return None


# ═══════════════════════════════════════════════════════════
# EXPERIENCE BUFFER (SQLite)
# ═══════════════════════════════════════════════════════════

def _init_experience_db():
    EXPERIENCE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(EXPERIENCE_DB), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS experiences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            pair TEXT NOT NULL,
            state_json TEXT NOT NULL,
            action INTEGER NOT NULL,
            reward REAL NOT NULL,
            next_state_json TEXT NOT NULL,
            done INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_ts ON experiences(timestamp)")
    conn.commit()
    conn.close()


class ExperienceBuffer:
    """Буфер опыта для обучения DQN."""

    def __init__(self, max_size: int = 10000):
        self.max_size = max_size
        _init_experience_db()
        self.conn = sqlite3.connect(str(EXPERIENCE_DB), timeout=10)
        self.conn.execute("PRAGMA journal_mode=WAL")

    def add(self, pair: str, state: np.ndarray, action: int,
            reward: float, next_state: np.ndarray, done: bool = False):
        """Добавить опыт."""
        self.conn.execute(
            "INSERT INTO experiences (timestamp, pair, state_json, action, "
            "reward, next_state_json, done) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (time.time(), pair,
             json.dumps(state.tolist()), action, reward,
             json.dumps(next_state.tolist()), int(done))
        )
        self.conn.commit()
        self._trim()

    def sample(self, batch_size: int = 32) -> list:
        """Случайная выборка для обучения."""
        cursor = self.conn.execute(
            "SELECT state_json, action, reward, next_state_json, done "
            "FROM experiences ORDER BY RANDOM() LIMIT ?",
            (batch_size,)
        )
        batch = []
        for row in cursor.fetchall():
            state = np.array(json.loads(row[0]), dtype=np.float32)
            action = row[1]
            reward = row[2]
            next_state = np.array(json.loads(row[3]), dtype=np.float32)
            done = bool(row[4])
            batch.append((state, action, reward, next_state, done))
        return batch

    def size(self) -> int:
        cursor = self.conn.execute("SELECT COUNT(*) FROM experiences")
        return cursor.fetchone()[0]

    def get_all_for_pair(self, pair: str) -> list:
        """Все опыт для конкретной пары."""
        cursor = self.conn.execute(
            "SELECT state_json, action, reward, next_state_json, done "
            "FROM experiences WHERE pair = ? ORDER BY timestamp",
            (pair,)
        )
        batch = []
        for row in cursor.fetchall():
            state = np.array(json.loads(row[0]), dtype=np.float32)
            action = row[1]
            reward = row[2]
            next_state = np.array(json.loads(row[3]), dtype=np.float32)
            done = bool(row[4])
            batch.append((state, action, reward, next_state, done))
        return batch

    def _trim(self):
        """Ограничить размер буфера."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM experiences")
        count = cursor.fetchone()[0]
        if count > self.max_size:
            self.conn.execute(
                "DELETE FROM experiences WHERE id IN "
                "(SELECT id FROM experiences ORDER BY timestamp ASC LIMIT ?)",
                (count - self.max_size,)
            )
            self.conn.commit()

    def close(self):
        self.conn.close()


# ═══════════════════════════════════════════════════════════
# STATE BUILDER — формирование состояния для RL
# ═══════════════════════════════════════════════════════════

def build_state(market_features: np.ndarray, is_holding: bool = False,
                unrealized_pnl: float = 0.0, time_in_trade: float = 0.0) -> np.ndarray:
    """
    Построить вектор состояния [13] из рыночных фичей + позиции.
    
    Args:
        market_features: [10] — body_ratio, upper_shadow, lower_shadow, 
            range_pct, vol_relative, change_pct, sma20_dist, rsi_norm, 
            macd_norm, atr_norm
        is_holding: держим ли позицию
        unrealized_pnl: нереализованный PnL в %
        time_in_trade: время в сделке (часы)
    """
    position_features = np.array([
        float(is_holding),
        np.clip(unrealized_pnl, -0.5, 0.5),  # clamp PnL
        np.clip(time_in_trade / 120.0, 0.0, 1.0),  # нормализуем 120ч → 1.0
    ], dtype=np.float32)

    state = np.concatenate([market_features[:10], position_features])
    return state


# ═══════════════════════════════════════════════════════════
# HIGH-LEVEL API
# ═══════════════════════════════════════════════════════════

class RLTrader:
    """Высокоуровневый API для RL-агента."""

    def __init__(self):
        self.agent = load_rl_model()
        self.buffer = ExperienceBuffer()
        # Higher epsilon for exploration — especially important when
        # the model hasn't learned anything yet
        self.epsilon = 0.30  # 30% случайных действий при старте
        self._last_states = {}  # pair → (state, action)

    @property
    def available(self) -> bool:
        return self.agent is not None

    def decide(self, pair: str, market_features: np.ndarray,
               is_holding: bool = False, unrealized_pnl: float = 0.0,
               time_in_trade: float = 0.0) -> dict:
        """
        Принять решение на основе состояния.
        
        Returns:
            {"action": "hold"|"buy"|"sell", "confidence": float, "q_values": dict}
        """
        if not self.available:
            return {"action": "hold", "confidence": 0.0, "q_values": {}}

        state = build_state(market_features, is_holding, unrealized_pnl, time_in_trade)
        
        # Epsilon-greedy
        action_idx = self.agent.get_action(state, self.epsilon)
        action_names = {0: "hold", 1: "buy", 2: "sell"}
        
        # Q-values для информации
        q_vals = self.agent.predict(state)
        probs = self.agent.get_action_probs(state)
        
        # Confidence = max probability
        confidence = max(probs.values())
        
        # Сохраняем для будущего experience
        self._last_states[pair] = (state, action_idx)

        return {
            "action": action_names[action_idx],
            "confidence": confidence,
            "q_values": probs,
            "state": state,
        }

    def record_reward(self, pair: str, reward: float, done: bool = False,
                      market_features: np.ndarray = None):
        """Записать награду за действие."""
        if pair not in self._last_states:
            return
        
        state, action = self._last_states[pair]
        
        if market_features is not None:
            next_state = build_state(market_features, done)
        else:
            next_state = state  # если нет новых фичей
        
        self.buffer.add(pair, state, action, reward, next_state, done)
        del self._last_states[pair]

    def get_status(self) -> dict:
        """Статус RL-агента."""
        stats = self.buffer.size()
        return {
            "model_loaded": self.available,
            "experiences": stats,
            "epsilon": self.epsilon,
            "model_path": str(RL_MODEL_PATH),
        }

    def close(self):
        self.buffer.close()


# Singleton
_rl_instance = None


def get_rl_trader() -> RLTrader:
    global _rl_instance
    if _rl_instance is None:
        _rl_instance = RLTrader()
    return _rl_instance


def reset_rl_trader():
    global _rl_instance
    if _rl_instance:
        _rl_instance.close()
    _rl_instance = None
