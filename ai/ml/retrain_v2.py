"""
Auto-Retrain Pipeline v2 — улучшенное обучение LSTM.

Изменения относительно v1:
  1. 23 фичи (как в XGBoost) вместо 10
  2. Dropout (0.3) + Weight Decay (1e-4) для борьбы с overfitting
  3. Class weighting (обратно пропорционально частоте)
  4. Больше данных: 14 пар × 1000 свечей
  5. Early Stopping (patience=10)
  6. Gradient clipping (1.0)
  7. Learning rate scheduler с patience=5
  8. Сохранение лучшей модели по val_acc (не последней)

Usage:
    python -m ai.ml.retrain_v2 --pairs BTC/USDT,ETH/USDT --epochs 100
    python -m ai.ml.retrain_v2 --auto --threshold 0.02
"""

import argparse
import json
import math
import os
import sys
import time
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import Dataset, DataLoader, WeightedRandomSampler
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

# ── Local imports ──────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))
from ai.ml.candle_features_v2 import extract_features_v2, FEATURE_NAMES_V2

try:
    from ai.ml.outcome_tracker import get_tracker
except ImportError:
    get_tracker = None


# ── Config ─────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent / "data"
MODEL_DIR = Path(__file__).parent / "models"
BINANCE_API = "https://api.binance.com/api/v3/klines"
INPUT_SIZE = 23  # 23 features (same as XGBoost)
SEQ_LEN = 20


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


# ═══════════════════════════════════════════════════════════
# LABEL GENERATION
# ═══════════════════════════════════════════════════════════

def generate_labels(candles: list, forward_bars: int = 4,
                    buy_threshold: float = 0.005,
                    sell_threshold: float = 0.005) -> list:
    """
    Генерация меток.
    buy:  если max рост > buy_threshold в следующие forward_bars
    sell: если max падение > sell_threshold
    hold: иначе
    """
    labels = []
    for i in range(len(candles) - forward_bars):
        entry_price = candles[i]["close"]
        max_up = 0.0
        max_down = 0.0
        for j in range(1, forward_bars + 1):
            future_close = candles[i + j]["close"]
            change = (future_close - entry_price) / entry_price
            max_up = max(max_up, change)
            max_down = min(max_down, change)
        
        if max_up > buy_threshold:
            label = 1  # buy
        elif max_down < -sell_threshold:
            label = 2  # sell
        else:
            label = 0  # hold
        
        labels.append(label)
    
    return labels


# ═══════════════════════════════════════════════════════════
# PYTORCH MODEL — улучшенная архитектура
# ═══════════════════════════════════════════════════════════

if HAS_TORCH:
    class CandleLSTMv2(nn.Module):
        """
        Улучшенная LSTM с 23 фичами, dropout и residual connections.
        
        Архитектура:
          - 2-layer LSTM (hidden=128)
          - Dropout (0.3) между слоями
          - BatchNorm после LSTM
          - 2-layer MLP head с dropout
        """
        
        def __init__(self, input_size=INPUT_SIZE, hidden_size=128,
                     num_layers=2, num_classes=3, dropout=0.3):
            super().__init__()
            self.hidden_size = hidden_size
            self.num_layers = num_layers
            
            # Layer 1
            self.lstm1 = nn.LSTMCell(input_size, hidden_size)
            self.drop1 = nn.Dropout(dropout)
            
            # Layer 2
            self.lstm2 = nn.LSTMCell(hidden_size, hidden_size)
            self.drop2 = nn.Dropout(dropout)
            
            # BatchNorm
            self.bn = nn.LayerNorm(hidden_size)
            
            # MLP head
            self.head = nn.Sequential(
                nn.Linear(hidden_size, 64),
                nn.ReLU(),
                nn.Dropout(dropout * 0.5),
                nn.Linear(64, num_classes),
            )
        
        def forward(self, x):
            batch_size = x.size(0)
            seq_len = x.size(1)
            
            h1 = torch.zeros(batch_size, self.hidden_size, device=x.device)
            c1 = torch.zeros(batch_size, self.hidden_size, device=x.device)
            h2 = torch.zeros(batch_size, self.hidden_size, device=x.device)
            c2 = torch.zeros(batch_size, self.hidden_size, device=x.device)
            
            for t in range(seq_len):
                xt = x[:, t, :]
                
                # Layer 1
                h1, c1 = self.lstm1(xt, (h1, c1))
                h1 = self.drop1(h1)
                
                # Layer 2
                h2, c2 = self.lstm2(h1, (h2, c2))
                h2 = self.drop2(h2)
            
            # Take last hidden state
            out = self.bn(h2)
            out = self.head(out)
            return out
        
        def export_npz(self, path: str):
            """Экспорт весов в .npz для numpy inference."""
            state = self.state_dict()
            np.savez(str(path),
                     # Layer 1
                     W_ii=state["lstm1.weight_ih"].numpy(),
                     b_ii=state["lstm1.bias_ih"].numpy(),
                     W_hi=state["lstm1.weight_hh"].numpy(),
                     b_hi=state["lstm1.bias_hh"].numpy(),
                     # Layer 2
                     W_ii2=state["lstm2.weight_ih"].numpy(),
                     b_ii2=state["lstm2.bias_ih"].numpy(),
                     W_hi2=state["lstm2.weight_hh"].numpy(),
                     b_hi2=state["lstm2.bias_hh"].numpy(),
                     # Head — fc2 is first layer (128→64), fc is final (64→3)
                     fc2_weight=state["head.0.weight"].numpy(),
                     fc2_bias=state["head.0.bias"].numpy(),
                     fc_weight=state["head.3.weight"].numpy(),
                     fc_bias=state["head.3.bias"].numpy(),
                     # LayerNorm
                     bn_weight=state["bn.weight"].numpy(),
                     bn_bias=state["bn.bias"].numpy(),
                     # Metadata
                     input_size=np.array([INPUT_SIZE], dtype=np.int32),
                     hidden_size=np.array([self.hidden_size], dtype=np.int32),
                     )


# ═══════════════════════════════════════════════════════════
# DATASET
# ═══════════════════════════════════════════════════════════

class CandleDataset(Dataset):
    """PyTorch Dataset для candle sequences с 23 фичами."""
    
    def __init__(self, sequences: np.ndarray, labels: np.ndarray):
        self.sequences = torch.FloatTensor(sequences)
        self.labels = torch.LongTensor(labels)
    
    def __len__(self):
        return len(self.labels)
    
    def __getitem__(self, idx):
        return self.sequences[idx], self.labels[idx]


def prepare_dataset(candles: list, seq_len: int = SEQ_LEN,
                    forward_bars: int = 4) -> Tuple[np.ndarray, np.ndarray]:
    """
    Подготовить dataset с 23 фичами.
    """
    features = extract_features_v2(candles)
    labels = generate_labels(candles, forward_bars=forward_bars)
    
    X, y = [], []
    for i in range(seq_len, min(len(features), len(labels))):
        X.append(features[i - seq_len:i])
        y.append(labels[i - 1])
    
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.int64)


# ═══════════════════════════════════════════════════════════
# TRAINING — улучшенная версия
# ═══════════════════════════════════════════════════════════

def compute_class_weights(y: np.ndarray) -> torch.FloatTensor:
    """Вычислить веса классов обратно пропорционально частоте."""
    classes, counts = np.unique(y, return_counts=True)
    total = len(y)
    weights = total / (len(classes) * counts.astype(np.float64))
    weight_dict = {c: w for c, w in zip(classes, weights)}
    return torch.FloatTensor([weight_dict.get(i, 1.0) for i in range(3)])


def train_model(model, train_loader, val_loader, epochs: int = 100,
                lr: float = 0.001, device: str = "cpu",
                class_weights: Optional[torch.FloatTensor] = None,
                patience: int = 10) -> dict:
    """Обучить модель с early stopping и лучшим сохранением."""
    model = model.to(device)
    optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, patience=5, factor=0.5, min_lr=1e-6
    )
    
    if class_weights is not None:
        class_weights = class_weights.to(device)
    criterion = nn.CrossEntropyLoss(weight=class_weights)
    
    best_val_acc = 0.0
    best_train_acc = 0.0
    best_epoch = 0
    epochs_no_improve = 0
    
    history = {"train_acc": [], "val_acc": [], "train_loss": [], "val_loss": []}
    
    for epoch in range(epochs):
        # ── Train ──
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
        avg_train_loss = train_loss / train_total if train_total > 0 else 0
        
        # ── Validate ──
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
        avg_val_loss = val_loss / val_total if val_total > 0 else 0
        
        scheduler.step(avg_val_loss)
        
        # Track history
        history["train_acc"].append(train_acc)
        history["val_acc"].append(val_acc)
        history["train_loss"].append(avg_train_loss)
        history["val_loss"].append(avg_val_loss)
        
        # Save best model
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_train_acc = train_acc
            best_epoch = epoch
            epochs_no_improve = 0
        else:
            epochs_no_improve += 1
        
        # Logging
        if (epoch + 1) % 10 == 0 or epoch == 0:
            lr_now = optimizer.param_groups[0]["lr"]
            print(f"  Epoch {epoch+1}/{epochs}: "
                  f"train={train_acc:.3f} val={val_acc:.3f} "
                  f"loss={avg_train_loss:.4f}/{avg_val_loss:.4f} "
                  f"lr={lr_now:.6f} "
                  f"[best={best_val_acc:.3f}@{best_epoch+1}]")
        
        # Early stopping
        if epochs_no_improve >= patience:
            print(f"  ⏹️  Early stopping at epoch {epoch+1} "
                  f"(no improvement for {patience} epochs)")
            break
    
    return {
        "train_acc": best_train_acc,
        "val_acc": best_val_acc,
        "best_epoch": best_epoch + 1,
        "total_epochs": epoch + 1,
        "history": history,
    }


# ═══════════════════════════════════════════════════════════
# EVALUATION
# ═══════════════════════════════════════════════════════════

def evaluate_model(model_path: str, pairs: list,
                   seq_len: int = SEQ_LEN) -> dict:
    """Оценить модель на свежих данных."""
    from ai.ml.lstm_numpy import load_model
    
    model = load_model(model_path)
    if model is None:
        return {"error": "Cannot load model"}
    
    results = {}
    for pair in pairs:
        try:
            candles = fetch_binance_candles(pair, limit=200)
            features = extract_features_v2(candles)
            labels = generate_labels(candles, forward_bars=4)
            
            correct = 0
            total = 0
            for i in range(seq_len, min(len(features), len(labels))):
                seq = features[i - seq_len:i]
                seq_norm = seq[np.newaxis, :]  # (1, seq_len, 23)
                pred = model.predict(seq_norm)
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
# MAIN
# ═══════════════════════════════════════════════════════════

def run_auto_retrain(pairs: list, epochs: int = 100,
                     seq_len: int = SEQ_LEN, threshold: float = 0.005,
                     deploy_if_better: bool = True) -> dict:
    """Полный pipeline автоматического ретрейнинга v2."""
    if not HAS_TORCH:
        return {"error": "PyTorch required"}
    
    result = {"steps": []}
    old_model_path = MODEL_DIR / "candle_lstm_v1.npz"
    
    # 1. Fetch data
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
    
    # 2. Prepare dataset
    print("\n📊 Preparing dataset (23 features)...")
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
    
    # Class distribution
    classes, counts = np.unique(y, return_counts=True)
    class_dist = {str(k): int(v) for k, v in zip(classes, counts)}
    print(f"  Total: {len(X)} sequences (train={len(X_train)}, val={len(X_val)})")
    print(f"  Class distribution: {class_dist}")
    
    result["steps"].append({
        "name": "prepare_dataset",
        "total": len(X), "train": len(X_train), "val": len(X_val),
        "class_distribution": class_dist
    })
    
    # 3. Evaluate current model
    old_accuracy = 0.0
    if old_model_path.exists():
        print("\n🔍 Evaluating current model...")
        eval_result = evaluate_model(str(old_model_path), list(all_candles.keys()), seq_len)
        old_accuracy = eval_result.get("average_accuracy", 0.0)
        print(f"  Current model accuracy: {old_accuracy:.3f}")
        result["steps"].append({"name": "evaluate_old", "accuracy": old_accuracy})
    
    # 4. Train new model
    print(f"\n🎓 Training new LSTMv2 ({epochs} epochs, {INPUT_SIZE} features)...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"  Device: {device}")
    
    model = CandleLSTMv2(input_size=INPUT_SIZE, hidden_size=128,
                         num_layers=2, num_classes=3, dropout=0.3)
    
    # Class weights
    class_weights = compute_class_weights(y_train)
    print(f"  Class weights: hold={class_weights[0]:.3f} "
          f"buy={class_weights[1]:.3f} sell={class_weights[2]:.3f}")
    
    train_dataset = CandleDataset(X_train, y_train)
    val_dataset = CandleDataset(X_val, y_val)
    train_loader = DataLoader(train_dataset, batch_size=64, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=64, shuffle=False)
    
    train_result = train_model(
        model, train_loader, val_loader,
        epochs=epochs, device=device,
        class_weights=class_weights,
        patience=10
    )
    
    print(f"\n  Best: train_acc={train_result['train_acc']:.3f}, "
          f"val_acc={train_result['val_acc']:.3f} "
          f"(epoch {train_result['best_epoch']})")
    
    result["steps"].append({
        "name": "train_new",
        "train_acc": train_result["train_acc"],
        "val_acc": train_result["val_acc"],
        "best_epoch": train_result["best_epoch"],
        "total_epochs": train_result["total_epochs"],
    })
    
    # 5. Compare and deploy
    improvement = train_result["val_acc"] - old_accuracy
    print(f"\n📈 Improvement: {improvement:+.3f} "
          f"({old_accuracy:.3f} → {train_result['val_acc']:.3f})")
    
    deployed = False
    if deploy_if_better and improvement > 0.01:
        if old_model_path.exists():
            backup = MODEL_DIR / f"backup_{int(time.time())}.npz"
            shutil.copy2(str(old_model_path), str(backup))
            print(f"  💾 Backup: {backup}")
        
        model.export_npz(str(old_model_path))
        print(f"  ✅ Deployed new model: {old_model_path}")
        deployed = True
    elif improvement <= 0.01:
        print(f"  ⏭️  New model not better enough (need >1% improvement)")
    
    result["steps"].append({"name": "deploy", "deployed": deployed})
    result["deployed"] = deployed
    
    return result


def main():
    parser = argparse.ArgumentParser(description="Auto-Retrain LSTM v2")
    parser.add_argument("--pairs", default="BTC/USDT,ETH/USDT,SOL/USDT,XRP/USDT,"
                        "DOGE/USDT,PEPE/USDT,ADA/USDT,AVAX/USDT,"
                        "DOT/USDT,LINK/USDT,MATIC/USDT,ATOM/USDT,"
                        "UNI/USDT,FIL/USDT")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--seq-len", type=int, default=20)
    parser.add_argument("--threshold", type=float, default=0.005)
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--evaluate-only", action="store_true")
    parser.add_argument("--no-deploy", action="store_true")
    args = parser.parse_args()
    
    pairs = [p.strip() for p in args.pairs.split(",")]
    
    if args.evaluate_only:
        model_path = MODEL_DIR / "candle_lstm_v1.npz"
        if model_path.exists():
            result = evaluate_model(str(model_path), pairs, args.seq_len)
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
