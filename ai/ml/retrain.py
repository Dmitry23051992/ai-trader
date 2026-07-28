"""
Auto-Retrain Pipeline — автоматическое переобучение LSTM модели.

Запускается на PC (нужен PyTorch). 
Собирает свежие данные с Binance + проверенные предсказания,
обучает новую модель, сравнивает с текущей, деплоит если лучше.

Usage:
    # Интерактивно
    python -m ai.ml.retrain --pairs BTC/USDT,ETH/USDT --epochs 50
    
    # Автоматический режим (для cron/systemd)
    python -m ai.ml.retrain --auto --threshold 0.02
    
    # Только оценка текущей модели
    python -m ai.ml.retrain --evaluate-only

Requirements:
    pip install torch requests numpy
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import Dataset, DataLoader
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

# ── Local imports ──────────────────────────────────────────
try:
    from ai.ml.candle_features import extract_features, normalize_features
except ImportError:
    # Fallback for running directly
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from ai.ml.candle_features import extract_features, normalize_features

try:
    from ai.ml.outcome_tracker import get_tracker, OutcomeTracker
except ImportError:
    get_tracker = None

try:
    from ai.ml.rl_agent import ExperienceBuffer, RL_MODEL_PATH
except ImportError:
    ExperienceBuffer = None


# ── Config ─────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent / "data"
MODEL_DIR = Path(__file__).parent / "models"
BINANCE_API = "https://api.binance.com/api/v3/klines"


# ═══════════════════════════════════════════════════════════
# DATA COLLECTION
# ═══════════════════════════════════════════════════════════

def fetch_binance_candles(pair: str, interval: str = "15m",
                          limit: int = 1000) -> list:
    """Скачать свечи с Binance."""
    import requests
    
    params = {"symbol": pair.replace("/", ""), "interval": interval, "limit": limit}
    resp = requests.get(BINANCE_API, params=params, timeout=30)
    resp.raise_for_status()
    
    data = resp.json()
    candles = []
    for c in data:
        candles.append({
            "timestamp": c[0],
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
            "volume": float(c[5]),
        })
    return candles


def fetch_multi_pair_candles(pairs: list, interval: str = "15m",
                              limit: int = 1000) -> dict:
    """Скачать свечи для нескольких пар."""
    all_data = {}
    for pair in pairs:
        try:
            candles = fetch_binance_candles(pair, interval, limit)
            all_data[pair] = candles
            print(f"  ✅ {pair}: {len(candles)} candles")
        except Exception as e:
            print(f"  ❌ {pair}: {e}")
    return all_data


# ═══════════════════════════════════════════════════════════
# LABEL GENERATION — определение ground truth
# ═══════════════════════════════════════════════════════════

def generate_labels(candles: list, forward_bars: int = 4,
                    threshold: float = 0.005) -> list:
    """
    Генерация меток для обучения.
    
    Для каждой свечи смотрим на следующие forward_bars свечей:
    - Если цена выросла > threshold → buy (1)
    - Если цена упала > threshold → sell (2)
    - Иначе → hold (0)
    
    Args:
        candles: список OHLCV свечей
        forward_bars: на сколько свечей вперёд смотрим
        threshold: минимальное изменение цены для сигнала
    """
    labels = []
    for i in range(len(candles) - forward_bars):
        entry_price = candles[i]["close"]
        
        # Смотрим на максимальное движение вперёд
        max_up = 0.0
        max_down = 0.0
        for j in range(1, forward_bars + 1):
            future_close = candles[i + j]["close"]
            change = (future_close - entry_price) / entry_price
            max_up = max(max_up, change)
            max_down = min(max_down, change)
        
        # Определяем метку
        if max_up > threshold:
            label = 1  # buy
        elif max_down < -threshold:
            label = 2  # sell
        else:
            label = 0  # hold
        
        labels.append(label)
    
    return labels


# ═══════════════════════════════════════════════════════════
# PYTORCH MODEL (same architecture as candle LSTM)
# ═══════════════════════════════════════════════════════════

if HAS_TORCH:
    class CandleLSTM(nn.Module):
        """PyTorch LSTM — совместимый с lstm_numpy.py."""
        
        def __init__(self, input_size=10, hidden_size=64,
                     num_layers=2, num_classes=3):
            super().__init__()
            self.hidden_size = hidden_size
            self.num_layers = num_layers
            
            # LSTM — раздельные веса для i, g, f, o
            self.W_ii = nn.Linear(input_size, hidden_size)
            self.W_hi = nn.Linear(hidden_size, hidden_size)
            self.W_ig = nn.Linear(input_size, hidden_size)
            self.W_hg = nn.Linear(hidden_size, hidden_size)
            self.W_if = nn.Linear(input_size, hidden_size)
            self.W_hf = nn.Linear(hidden_size, hidden_size)
            self.W_io = nn.Linear(input_size, hidden_size)
            self.W_ho = nn.Linear(hidden_size, hidden_size)
            
            # Second layer
            self.W_ii2 = nn.Linear(hidden_size, hidden_size)
            self.W_hi2 = nn.Linear(hidden_size, hidden_size)
            self.W_ig2 = nn.Linear(hidden_size, hidden_size)
            self.W_hg2 = nn.Linear(hidden_size, hidden_size)
            self.W_if2 = nn.Linear(hidden_size, hidden_size)
            self.W_hf2 = nn.Linear(hidden_size, hidden_size)
            self.W_io2 = nn.Linear(hidden_size, hidden_size)
            self.W_ho2 = nn.Linear(hidden_size, hidden_size)
            
            # Output
            self.fc = nn.Linear(hidden_size, num_classes)
        
        def forward(self, x):
            batch_size = x.size(0)
            h1 = torch.zeros(batch_size, self.hidden_size, device=x.device)
            c1 = torch.zeros(batch_size, self.hidden_size, device=x.device)
            h2 = torch.zeros(batch_size, self.hidden_size, device=x.device)
            c2 = torch.zeros(batch_size, self.hidden_size, device=x.device)
            
            for t in range(x.size(1)):
                xt = x[:, t, :]
                
                # Layer 1
                i = torch.sigmoid(self.W_ii(xt) + self.W_hi(h1))
                g = torch.tanh(self.W_ig(xt) + self.W_hg(h1))
                f = torch.sigmoid(self.W_if(xt) + self.W_hf(h1))
                o = torch.sigmoid(self.W_io(xt) + self.W_ho(h1))
                c1 = f * c1 + i * g
                h1 = o * torch.tanh(c1)
                
                # Layer 2
                i2 = torch.sigmoid(self.W_ii2(h1) + self.W_hi2(h2))
                g2 = torch.tanh(self.W_ig2(h1) + self.W_hg2(h2))
                f2 = torch.sigmoid(self.W_if2(h1) + self.W_hf2(h2))
                o2 = torch.sigmoid(self.W_io2(h1) + self.W_ho2(h2))
                c2 = f2 * c2 + i2 * g2
                h2 = o2 * torch.tanh(c2)
            
            return self.fc(h2)
        
        def export_npz(self, path: str):
            """Экспорт весов в .npz для numpy inference."""
            state = self.state_dict()
            np.savez(str(path),
                     W_ii=state["W_ii.weight"].numpy(),
                     b_ii=state["W_ii.bias"].numpy(),
                     W_hi=state["W_hi.weight"].numpy(),
                     b_hi=state["W_hi.bias"].numpy(),
                     W_ig=state["W_ig.weight"].numpy(),
                     b_ig=state["W_ig.bias"].numpy(),
                     W_hg=state["W_hg.weight"].numpy(),
                     b_hg=state["W_hg.bias"].numpy(),
                     W_if=state["W_if.weight"].numpy(),
                     b_if=state["W_if.bias"].numpy(),
                     W_hf=state["W_hf.weight"].numpy(),
                     b_hf=state["W_hf.bias"].numpy(),
                     W_io=state["W_io.weight"].numpy(),
                     b_io=state["W_io.bias"].numpy(),
                     W_ho=state["W_ho.weight"].numpy(),
                     b_ho=state["W_ho.bias"].numpy(),
                     # Layer 2
                     W_ii2=state["W_ii2.weight"].numpy(),
                     b_ii2=state["W_ii2.bias"].numpy(),
                     W_hi2=state["W_hi2.weight"].numpy(),
                     b_hi2=state["W_hi2.bias"].numpy(),
                     W_ig2=state["W_ig2.weight"].numpy(),
                     b_ig2=state["W_ig2.bias"].numpy(),
                     W_hg2=state["W_hg2.weight"].numpy(),
                     b_hg2=state["W_hg2.bias"].numpy(),
                     W_if2=state["W_if2.weight"].numpy(),
                     b_if2=state["W_if2.bias"].numpy(),
                     W_hf2=state["W_hf2.weight"].numpy(),
                     b_hf2=state["W_hf2.bias"].numpy(),
                     W_io2=state["W_io2.weight"].numpy(),
                     b_io2=state["W_io2.bias"].numpy(),
                     W_ho2=state["W_ho2.weight"].numpy(),
                     b_ho2=state["W_ho2.bias"].numpy(),
                     # Output
                     fc_weight=state["fc.weight"].numpy(),
                     fc_bias=state["fc.bias"].numpy(),
                     )


# ═══════════════════════════════════════════════════════════
# DATASET
# ═══════════════════════════════════════════════════════════

class CandleDataset(Dataset):
    """PyTorch Dataset для candle sequences."""
    
    def __init__(self, sequences: np.ndarray, labels: np.ndarray):
        self.sequences = torch.FloatTensor(sequences)
        self.labels = torch.LongTensor(labels)
    
    def __len__(self):
        return len(self.labels)
    
    def __getitem__(self, idx):
        return self.sequences[idx], self.labels[idx]


def prepare_dataset(candles: list, seq_len: int = 20,
                    forward_bars: int = 4) -> Tuple[np.ndarray, np.ndarray]:
    """
    Подготовить dataset: извлечь фичи и создать последовательности.
    """
    features_list = []
    for c in candles:
        feat = extract_features(
            c["open"], c["high"], c["low"], c["close"], c["volume"]
        )
        features_list.append(feat)
    
    features = np.array(features_list, dtype=np.float32)
    features = normalize_features(features)
    
    labels = generate_labels(candles, forward_bars=forward_bars)
    
    # Создаём последовательности
    X, y = [], []
    for i in range(seq_len, len(features)):
        X.append(features[i - seq_len:i])
        y.append(labels[i - 1])
    
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.int64)


# ═══════════════════════════════════════════════════════════
# TRAINING
# ═══════════════════════════════════════════════════════════

def train_model(model, train_loader, val_loader, epochs: int = 50,
                lr: float = 0.001, device: str = "cpu") -> dict:
    """Обучить модель."""
    model = model.to(device)
    optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=5, factor=0.5)
    criterion = nn.CrossEntropyLoss()
    
    best_val_acc = 0.0
    best_train_acc = 0.0
    
    for epoch in range(epochs):
        # Train
        model.train()
        train_loss = 0.0
        train_correct = 0
        train_total = 0
        
        for batch_x, batch_y in train_loader:
            batch_x, batch_y = batch_x.to(device), batch_y.to(device)
            
            optimizer.zero_grad()
            output = model(batch_x)
            loss = criterion(output, batch_y)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            
            train_loss += loss.item() * batch_x.size(0)
            _, predicted = output.max(1)
            train_correct += predicted.eq(batch_y).sum().item()
            train_total += batch_y.size(0)
        
        train_acc = train_correct / train_total if train_total > 0 else 0
        
        # Validate
        model.eval()
        val_loss = 0.0
        val_correct = 0
        val_total = 0
        
        with torch.no_grad():
            for batch_x, batch_y in val_loader:
                batch_x, batch_y = batch_x.to(device), batch_y.to(device)
                output = model(batch_x)
                loss = criterion(output, batch_y)
                val_loss += loss.item() * batch_x.size(0)
                _, predicted = output.max(1)
                val_correct += predicted.eq(batch_y).sum().item()
                val_total += batch_y.size(0)
        
        val_acc = val_correct / val_total if val_total > 0 else 0
        avg_train_loss = train_loss / train_total if train_total > 0 else 0
        avg_val_loss = val_loss / val_total if val_total > 0 else 0
        
        scheduler.step(avg_val_loss)
        
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_train_acc = train_acc
        
        if (epoch + 1) % 10 == 0:
            lr_now = optimizer.param_groups[0]["lr"]
            print(f"  Epoch {epoch+1}/{epochs}: "
                  f"train_acc={train_acc:.3f} val_acc={val_acc:.3f} "
                  f"loss={avg_train_loss:.4f}/{avg_val_loss:.4f} "
                  f"lr={lr_now:.6f}")
    
    return {"train_acc": best_train_acc, "val_acc": best_val_acc}


# ═══════════════════════════════════════════════════════════
# RL TRAINING — DQN на Experience Buffer
# ═══════════════════════════════════════════════════════════

def train_rl_agent(buffer: ExperienceBuffer, epochs: int = 100,
                   batch_size: int = 32, lr: float = 0.001,
                   device: str = "cpu") -> Optional[dict]:
    """
    Обучить DQN агента на накопленном опыте.
    """
    if buffer.size() < batch_size * 2:
        print(f"⚠️  Недостаточно опыта для RL обучения: {buffer.size()} < {batch_size * 2}")
        return None
    
    from ai.ml.rl_agent import STATE_SIZE, HIDDEN_SIZE, ACTION_SIZE, GAMMA
    
    # Простой DQN для обучения
    class DQNetwork(nn.Module):
        def __init__(self):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(STATE_SIZE, HIDDEN_SIZE),
                nn.ReLU(),
                nn.Linear(HIDDEN_SIZE, HIDDEN_SIZE),
                nn.ReLU(),
                nn.Linear(HIDDEN_SIZE, ACTION_SIZE),
            )
        
        def forward(self, x):
            return self.net(x)
    
    policy_net = DQNetwork().to(device)
    target_net = DQNetwork().to(device)
    target_net.load_state_dict(policy_net.state_dict())
    
    optimizer = optim.Adam(policy_net.parameters(), lr=lr)
    criterion = nn.SmoothL1Loss()
    
    best_loss = float("inf")
    
    for epoch in range(epochs):
        batch = buffer.sample(batch_size)
        if len(batch) < batch_size:
            continue
        
        states = torch.FloatTensor(np.array([b[0] for b in batch])).to(device)
        actions = torch.LongTensor([b[1] for b in batch]).unsqueeze(1).to(device)
        rewards = torch.FloatTensor([b[2] for b in batch]).to(device)
        next_states = torch.FloatTensor(np.array([b[3] for b in batch])).to(device)
        dones = torch.FloatTensor([b[4] for b in batch]).to(device)
        
        # Current Q values
        current_q = policy_net(states).gather(1, actions).squeeze()
        
        # Target Q values
        with torch.no_grad():
            next_q = target_net(next_states).max(1)[0]
            target_q = rewards + GAMMA * next_q * (1 - dones)
        
        loss = criterion(current_q, target_q)
        
        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(policy_net.parameters(), 1.0)
        optimizer.step()
        
        if (epoch + 1) % 20 == 0:
            print(f"  RL Epoch {epoch+1}/{epochs}: loss={loss.item():.4f}")
        
        if loss.item() < best_loss:
            best_loss = loss.item()
    
    # Export weights
    state = policy_net.state_dict()
    np.savez(str(RL_MODEL_PATH),
             W1=state["net.0.weight"].cpu().numpy(),
             b1=state["net.0.bias"].cpu().numpy(),
             W2=state["net.2.weight"].cpu().numpy(),
             b2=state["net.2.bias"].cpu().numpy(),
             W3=state["net.4.weight"].cpu().numpy(),
             b3=state["net.4.bias"].cpu().numpy())
    
    return {"loss": best_loss}


# ═══════════════════════════════════════════════════════════
# EVALUATION
# ═══════════════════════════════════════════════════════════

def evaluate_current_model(model_path: str, pairs: list,
                            seq_len: int = 20) -> dict:
    """Оценить текущую модель на свежих данных."""
    from ai.ml.lstm_numpy import load_model
    
    model = load_model(model_path)
    if model is None:
        return {"error": "Cannot load model"}
    
    results = {}
    for pair in pairs:
        try:
            candles = fetch_binance_candles(pair, limit=200)
            features_list = []
            for c in candles:
                feat = extract_features(
                    c["open"], c["high"], c["low"], c["close"], c["volume"]
                )
                features_list.append(feat)
            
            features = np.array(features_list, dtype=np.float32)
            features = normalize_features(features)
            
            labels = generate_labels(candles, forward_bars=4)
            
            correct = 0
            total = 0
            for i in range(seq_len, min(len(features), len(labels))):
                seq = features[i - seq_len:i]
                pred = model.predict(seq)
                pred_label = int(np.argmax(pred))
                true_label = labels[i - 1]
                if pred_label == true_label:
                    correct += 1
                total += 1
            
            acc = correct / total if total > 0 else 0
            results[pair] = {"accuracy": acc, "total": total, "correct": correct}
        except Exception as e:
            results[pair] = {"error": str(e)}
    
    avg_acc = np.mean([r["accuracy"] for r in results.values() if "accuracy" in r])
    return {"pairs": results, "average_accuracy": float(avg_acc)}


# ═══════════════════════════════════════════════════════════
# MAIN — Auto Retrain Pipeline
# ═══════════════════════════════════════════════════════════

def run_auto_retrain(pairs: list, epochs: int = 50,
                     seq_len: int = 20, threshold: float = 0.005,
                     deploy_if_better: bool = True) -> dict:
    """
    Полный pipeline автоматического ретрейнинга.
    
    1. Скачать свежие данные
    2. Подготовить dataset
    3. Обучить новую модель
    4. Сравнить с текущей
    5. Задеплоить если лучше
    """
    if not HAS_TORCH:
        return {"error": "PyTorch required"}
    
    result = {"steps": []}
    old_model_path = MODEL_DIR / "candle_lstm_v1.npz"
    
    # 1. Скачать данные
    print("📥 Fetching candles from Binance...")
    all_candles = {}
    for pair in pairs:
        try:
            candles = fetch_binance_candles(pair, limit=1000)
            all_candles[pair] = candles
            print(f"  ✅ {pair}: {len(candles)} candles")
        except Exception as e:
            print(f"  ❌ {pair}: {e}")
    
    if not all_candles:
        return {"error": "No data fetched"}
    
    result["steps"].append({
        "name": "fetch_data",
        "pairs": len(all_candles),
        "total_candles": sum(len(c) for c in all_candles.values())
    })
    
    # 2. Подготовить dataset
    print("\n📊 Preparing dataset...")
    all_X, all_y = [], []
    for pair, candles in all_candles.items():
        X, y = prepare_dataset(candles, seq_len=seq_len, forward_bars=4)
        all_X.append(X)
        all_y.append(y)
        print(f"  {pair}: {len(X)} sequences")
    
    X = np.concatenate(all_X, axis=0)
    y = np.concatenate(all_y, axis=0)
    
    # Shuffle
    idx = np.random.permutation(len(X))
    X, y = X[idx], y[idx]
    
    # Split: 80% train, 20% val
    split = int(len(X) * 0.8)
    X_train, X_val = X[:split], X[split:]
    y_train, y_val = y[:split], y[split:]
    
    print(f"  Total: {len(X)} sequences (train={len(X_train)}, val={len(X_val)})")
    result["steps"].append({
        "name": "prepare_dataset",
        "total": len(X), "train": len(X_train), "val": len(X_val)
    })
    
    # 3. Оценить текущую модель
    old_accuracy = 0.0
    if old_model_path.exists():
        print("\n🔍 Evaluating current model...")
        eval_result = evaluate_current_model(str(old_model_path), list(all_candles.keys()), seq_len)
        old_accuracy = eval_result.get("average_accuracy", 0.0)
        print(f"  Current model accuracy: {old_accuracy:.3f}")
        result["steps"].append({"name": "evaluate_old", "accuracy": old_accuracy})
    
    # 4. Обучить новую модель
    print(f"\n🎓 Training new model ({epochs} epochs)...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"  Device: {device}")
    
    model = CandleLSTM(input_size=10, hidden_size=64, num_layers=2, num_classes=3)
    
    train_dataset = CandleDataset(X_train, y_train)
    val_dataset = CandleDataset(X_val, y_val)
    train_loader = DataLoader(train_dataset, batch_size=64, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=64, shuffle=False)
    
    train_result = train_model(model, train_loader, val_loader, epochs=epochs, device=device)
    print(f"\n  Best: train_acc={train_result['train_acc']:.3f}, val_acc={train_result['val_acc']:.3f}")
    result["steps"].append({"name": "train_new", **train_result})
    
    # 5. Сравнить и задеплоить
    improvement = train_result["val_acc"] - old_accuracy
    print(f"\n📈 Improvement: {improvement:+.3f} ({old_accuracy:.3f} → {train_result['val_acc']:.3f})")
    result["steps"].append({
        "name": "compare",
        "old_accuracy": old_accuracy,
        "new_accuracy": train_result["val_acc"],
        "improvement": improvement
    })
    
    deployed = False
    if deploy_if_better and improvement > 0.01:
        # Backup old model
        if old_model_path.exists():
            backup = MODEL_DIR / f"backup_{int(time.time())}.npz"
            import shutil
            shutil.copy2(str(old_model_path), str(backup))
            print(f"  💾 Backup: {backup}")
        
        # Export new model
        model.export_npz(str(old_model_path))
        print(f"  ✅ Deployed new model: {old_model_path}")
        deployed = True
    elif improvement <= 0.01:
        print(f"  ⏭️  New model not better enough (need >1% improvement)")
    
    result["steps"].append({"name": "deploy", "deployed": deployed})
    result["deployed"] = deployed
    
    # 6. Log training run
    if get_tracker:
        try:
            tracker = get_tracker()
            tracker.log_training_run(
                model_path=str(old_model_path),
                pairs_used=len(all_candles),
                candles_used=sum(len(c) for c in all_candles.values()),
                train_acc=train_result["train_acc"],
                val_acc=train_result["val_acc"],
                old_acc=old_accuracy
            )
        except Exception:
            pass
    
    return result


def main():
    parser = argparse.ArgumentParser(description="Auto-Retrain LSTM + RL")
    parser.add_argument("--pairs", default="BTC/USDT,ETH/USDT,SOL/USDT,XRP/USDT")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--seq-len", type=int, default=20)
    parser.add_argument("--threshold", type=float, default=0.005)
    parser.add_argument("--auto", action="store_true", help="Auto mode")
    parser.add_argument("--evaluate-only", action="store_true")
    parser.add_argument("--no-deploy", action="store_true")
    args = parser.parse_args()
    
    pairs = [p.strip() for p in args.pairs.split(",")]
    
    if args.evaluate_only:
        model_path = MODEL_DIR / "candle_lstm_v1.npz"
        if model_path.exists():
            result = evaluate_current_model(str(model_path), pairs, args.seq_len)
            print(json.dumps(result, indent=2))
        else:
            print("No model found")
        return
    
    result = run_auto_retrain(
        pairs=pairs,
        epochs=args.epochs,
        seq_len=args.seq_len,
        threshold=args.threshold,
        deploy_if_better=not args.no_deploy
    )
    
    print(f"\n{'='*50}")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
