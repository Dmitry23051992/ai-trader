"""
XGBoost Candle Predictor — Training Script.

Training на PC. Экспорт модели в JSON для инференса на Pi (без PyTorch).

Usage:
    python -m ai.ml.train_xgboost --pairs BTC/USDT,ETH/USDT --epochs 200
    python -m ai.ml.train_xgboost --evaluate-only

Requirements:
    pip install xgboost scikit-learn requests numpy
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import requests

try:
    import xgboost as xgb
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, classification_report
    HAS_XGB = True
except ImportError:
    HAS_XGB = False
    print("ERROR: xgboost required. Install with:")
    print("  pip install xgboost scikit-learn")
    sys.exit(1)

# ── Local imports ──────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))
from ai.ml.candle_features import extract_features, normalize_features

# ── Config ─────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent / "data"
MODEL_DIR = Path(__file__).parent / "models"
XGB_MODEL_PATH = MODEL_DIR / "candle_xgboost_v1.json"
BINANCE_API = "https://api.binance.com/api/v3/klines"


# ═══════════════════════════════════════════════════════════
# DATA COLLECTION
# ═══════════════════════════════════════════════════════════

def fetch_binance_candles(pair: str, interval: str = "15m",
                          limit: int = 1000) -> list:
    """Скачать свечи с Binance."""
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
# LABEL GENERATION — расширенная версия
# ═══════════════════════════════════════════════════════════

def generate_labels_v2(candles: list, forward_bars: int = 4,
                       buy_threshold: float = 0.005,
                       sell_threshold: float = 0.005) -> list:
    """
    Генерация меток с учётом асимметрии рынка.
    
    buy:  если max рост > buy_threshold в следующие forward_bars
    sell: если max падение > sell_threshold
    hold: иначе
    """
    labels = []
    for i in range(len(candles) - forward_bars):
        entry_price = candles[i]["close"]
        
        # Максимальное движение вперёд
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
# FEATURE ENGINEERING — расширенные фичи для XGBoost
# ═══════════════════════════════════════════════════════════

def extract_features_v2(candles: list) -> np.ndarray:
    """
    Извлечь расширенный набор фичей для XGBoost.
    Включает: базовые + паттерны + объём + волатильность.
    """
    features = []
    
    for i in range(len(candles)):
        c = candles[i]
        o, h, l, cl, v = c["open"], c["high"], c["low"], c["close"], c["volume"]
        
        feat = {}
        
        # ── Базовые свечные фичи ──────────────────────
        feat["body"] = (cl - o) / (h - l + 1e-9)
        feat["upper_shadow"] = (h - max(o, cl)) / (h - l + 1e-9)
        feat["lower_shadow"] = (min(o, cl) - l) / (h - l + 1e-9)
        feat["range_pct"] = (h - l) / (cl + 1e-9) * 100
        feat["change_pct"] = (cl - o) / (o + 1e-9) * 100
        
        # ── EMA ────────────────────────────────────────
        closes = [candles[j]["close"] for j in range(max(0, i-49), i+1)]
        if len(closes) >= 12:
            ema12 = _ema(closes, 12)
            ema20 = _ema(closes, 20)
            ema50 = _ema(closes, 50) if len(closes) >= 50 else ema20
            feat["ema12_dist"] = (cl - ema12) / (ema12 + 1e-9) * 100
            feat["ema20_dist"] = (cl - ema20) / (ema20 + 1e-9) * 100
            feat["ema50_dist"] = (cl - ema50) / (ema50 + 1e-9) * 100
            feat["ema12_20_cross"] = 1.0 if ema12 > ema20 else 0.0
            feat["ema20_50_cross"] = 1.0 if ema20 > ema50 else 0.0
        else:
            feat["ema12_dist"] = 0.0
            feat["ema20_dist"] = 0.0
            feat["ema50_dist"] = 0.0
            feat["ema12_20_cross"] = 0.0
            feat["ema20_50_cross"] = 0.0
        
        # ── RSI ────────────────────────────────────────
        if i >= 14:
            closes_14 = [candles[j]["close"] for j in range(i-13, i+1)]
            feat["rsi"] = _rsi(closes_14)
        else:
            feat["rsi"] = 50.0
        
        # ── MACD ───────────────────────────────────────
        if i >= 26:
            closes_26 = [candles[j]["close"] for j in range(i-25, i+1)]
            macd_val, signal_val = _macd(closes_26)
            feat["macd"] = macd_val / (cl + 1e-9) * 100
            feat["macd_signal_diff"] = (macd_val - signal_val) / (cl + 1e-9) * 100
        else:
            feat["macd"] = 0.0
            feat["macd_signal_diff"] = 0.0
        
        # ── Bollinger Bands ────────────────────────────
        if i >= 20:
            closes_20 = [candles[j]["close"] for j in range(i-19, i+1)]
            bb_mid = np.mean(closes_20)
            bb_std = np.std(closes_20)
            bb_upper = bb_mid + 2 * bb_std
            bb_lower = bb_mid - 2 * bb_std
            feat["bb_position"] = (cl - bb_lower) / (bb_upper - bb_lower + 1e-9)
            feat["bb_width"] = (bb_upper - bb_lower) / (bb_mid + 1e-9) * 100
        else:
            feat["bb_position"] = 0.5
            feat["bb_width"] = 0.0
        
        # ── Volume ─────────────────────────────────────
        vols = [candles[j]["volume"] for j in range(max(0, i-19), i+1)]
        vol_ma = np.mean(vols) if vols else v
        feat["vol_ratio"] = v / (vol_ma + 1e-9)
        
        # ── ATR (Average True Range) ───────────────────
        if i >= 14:
            trs = []
            for j in range(i-13, i+1):
                c_j = candles[j]
                tr = max(
                    c_j["high"] - c_j["low"],
                    abs(c_j["high"] - candles[j-1]["close"]) if j > 0 else 0,
                    abs(c_j["low"] - candles[j-1]["close"]) if j > 0 else 0
                )
                trs.append(tr)
            atr = np.mean(trs)
            feat["atr_pct"] = atr / (cl + 1e-9) * 100
        else:
            feat["atr_pct"] = 0.0
        
        # ── ADX (Average Directional Index) ────────────
        if i >= 14:
            feat["adx"] = _adx(candles, i, period=14)
        else:
            feat["adx"] = 20.0
        
        # ── Momentum ───────────────────────────────────
        if i >= 5:
            feat["momentum_5"] = (cl - candles[i-5]["close"]) / (candles[i-5]["close"] + 1e-9) * 100
        else:
            feat["momentum_5"] = 0.0
        
        if i >= 10:
            feat["momentum_10"] = (cl - candles[i-10]["close"]) / (candles[i-10]["close"] + 1e-9) * 100
        else:
            feat["momentum_10"] = 0.0
        
        if i >= 20:
            feat["momentum_20"] = (cl - candles[i-20]["close"]) / (candles[i-20]["close"] + 1e-9) * 100
        else:
            feat["momentum_20"] = 0.0
        
        # ── Волатильность ──────────────────────────────
        if i >= 20:
            closes_20 = [candles[j]["close"] for j in range(i-19, i+1)]
            returns = np.diff(closes_20) / (np.array(closes_20[:-1]) + 1e-9)
            feat["volatility_20"] = np.std(returns) * 100
        else:
            feat["volatility_20"] = 0.0
        
        # ── Тренд-сила ─────────────────────────────────
        feat["trend_strength"] = feat["momentum_5"] * feat["vol_ratio"]
        
        features.append(feat)
    
    return features


def _ema(data: list, period: int) -> float:
    """Exponential Moving Average."""
    multiplier = 2 / (period + 1)
    ema = data[0]
    for val in data[1:]:
        ema = (val - ema) * multiplier + ema
    return ema


def _rsi(closes: list, period: int = 14) -> float:
    """Relative Strength Index."""
    if len(closes) < period + 1:
        return 50.0
    
    gains = []
    losses = []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _macd(closes: list) -> Tuple[float, float]:
    """MACD line and signal line."""
    if len(closes) < 26:
        return 0.0, 0.0
    
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line = ema12 - ema26
    
    # Signal line (9-period EMA of MACD)
    # Simplified: just return macd_line and a simple average
    signal_line = macd_line * 0.8  # approximation
    
    return macd_line, signal_line


def _adx(candles: list, idx: int, period: int = 14) -> float:
    """Average Directional Index (simplified)."""
    if idx < period + 1:
        return 20.0
    
    plus_dm = []
    minus_dm = []
    tr_list = []
    
    for i in range(idx - period, idx + 1):
        if i == 0:
            continue
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i-1]["close"]
        
        up = high - candles[i-1]["high"]
        down = candles[i-1]["low"] - low
        
        plus_dm.append(max(up, 0) if up > down else 0)
        minus_dm.append(max(down, 0) if down > up else 0)
        tr_list.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    
    if not tr_list:
        return 20.0
    
    atr = np.mean(tr_list)
    if atr == 0:
        return 20.0
    
    plus_di = (np.mean(plus_dm) / atr) * 100
    minus_di = (np.mean(minus_dm) / atr) * 100
    
    di_sum = plus_di + minus_di
    if di_sum == 0:
        return 20.0
    
    dx = abs(plus_di - minus_di) / di_sum * 100
    return dx


# ═══════════════════════════════════════════════════════════
# DATASET PREPARATION
# ═══════════════════════════════════════════════════════════

def prepare_dataset_v2(candles: list, forward_bars: int = 4,
                       buy_threshold: float = 0.005) -> Tuple[np.ndarray, np.ndarray, list]:
    """
    Подготовить dataset с расширенными фичами.
    """
    features = extract_features_v2(candles)
    labels = generate_labels_v2(candles, forward_bars=forward_bars,
                                buy_threshold=buy_threshold)
    
    # Feature names for feature importance
    feature_names = list(features[0].keys()) if features else []
    
    X = []
    y = []
    
    # Skip first 50 candles (need history for indicators)
    start = 50
    for i in range(start, min(len(features), len(labels))):
        feat = features[i]
        X.append([feat[k] for k in feature_names])
        y.append(labels[i - 1] if i - 1 < len(labels) else 0)
    
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.int64), feature_names


# ═══════════════════════════════════════════════════════════
# TRAINING
# ═══════════════════════════════════════════════════════════

def train_xgboost(X: np.ndarray, y: np.ndarray, feature_names: list,
                   n_estimators: int = 200, max_depth: int = 6,
                   learning_rate: float = 0.1) -> dict:
    """Обучить XGBoost модель."""
    
    # Split data
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    
    print(f"Train: {len(X_train)}, Val: {len(X_val)}")
    print(f"Class distribution: {dict(zip(*np.unique(y, return_counts=True)))}")
    
    # Train
    model = xgb.XGBClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=3,
        gamma=0.1,
        reg_alpha=0.1,
        reg_lambda=1.0,
        objective="multi:softprob",
        num_class=3,
        eval_metric="mlogloss",
        use_label_encoder=False,
        random_state=42,
    )
    
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=50,
    )
    
    # Evaluate
    y_pred = model.predict(X_val)
    y_pred_proba = model.predict_proba(X_val)
    
    train_acc = accuracy_score(y_train, model.predict(X_train))
    val_acc = accuracy_score(y_val, y_pred)
    
    print(f"\nResults:")
    print(f"  Train accuracy: {train_acc:.3f}")
    print(f"  Val accuracy: {val_acc:.3f}")
    
    # Feature importance
    importances = model.feature_importances_
    feat_imp = sorted(zip(feature_names, importances), key=lambda x: -x[1])
    print(f"\nTop features:")
    for name, imp in feat_imp[:10]:
        print(f"  {name}: {imp:.3f}")
    
    # Classification report
    target_names = ["hold", "buy", "sell"]
    print(f"\nClassification Report:")
    print(classification_report(y_val, y_pred, target_names=target_names))
    
    return {
        "model": model,
        "train_acc": train_acc,
        "val_acc": val_acc,
        "feature_names": feature_names,
        "feature_importances": feat_imp,
    }


# ═══════════════════════════════════════════════════════════
# EXPORT — сохранение модели для Pi
# ═══════════════════════════════════════════════════════════

def export_model(model, feature_names: list, path: Path):
    """
    Экспорт XGBoost модели в JSON для Pi.
    XGBoost умеет экспортировать в JSON — можно загрузить с numpy.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # Save as XGBoost JSON
    model.save_model(str(path))
    print(f"✅ Model saved to {path}")
    
    # Also save feature names
    meta_path = path.with_suffix(".meta.json")
    with open(meta_path, "w") as f:
        json.dump({
            "feature_names": feature_names,
            "model_type": "xgboost",
            "num_classes": 3,
            "class_names": ["hold", "buy", "sell"],
        }, f, indent=2)
    print(f"✅ Metadata saved to {meta_path}")


def load_model_for_pi(path: Path):
    """Загрузить модель на Pi для инференса."""
    if not path.exists():
        return None
    model = xgb.XGBClassifier()
    model.load_model(str(path))
    return model


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

def run_training(pairs: list, n_estimators: int = 200, max_depth: int = 6) -> dict:
    """Полный pipeline обучения."""
    
    print("=" * 50)
    print("XGBoost Candle Predictor Training")
    print("=" * 50)
    
    # 1. Fetch data
    print("\n📥 Fetching candles...")
    all_candles = []
    for pair in pairs:
        try:
            candles = fetch_binance_candles(pair, limit=1000)
            all_candles.extend(candles)
            print(f"  ✅ {pair}: {len(candles)} candles")
        except Exception as e:
            print(f"  ❌ {pair}: {e}")
    
    if not all_candles:
        return {"error": "No data"}
    
    # Remove duplicates by timestamp
    seen = set()
    unique_candles = []
    for c in sorted(all_candles, key=lambda x: x["timestamp"]):
        if c["timestamp"] not in seen:
            seen.add(c["timestamp"])
            unique_candles.append(c)
    all_candles = unique_candles
    
    print(f"\n📊 Total unique candles: {len(all_candles)}")
    
    # 2. Prepare dataset
    print("\n🔧 Preparing features...")
    X, y, feature_names = prepare_dataset_v2(all_candles, forward_bars=4)
    print(f"  Features: {len(feature_names)}, Samples: {len(X)}")
    
    # 3. Train
    print("\n🎓 Training XGBoost...")
    result = train_xgboost(X, y, feature_names, n_estimators=n_estimators,
                           max_depth=max_depth)
    
    # 4. Export
    print("\n💾 Exporting model...")
    export_model(result["model"], feature_names, XGB_MODEL_PATH)
    
    return {
        "train_acc": result["train_acc"],
        "val_acc": result["val_acc"],
        "top_features": result["feature_importances"][:10],
        "samples": len(X),
        "features": len(feature_names),
        "model_path": str(XGB_MODEL_PATH),
    }


def main():
    parser = argparse.ArgumentParser(description="Train XGBoost Candle Predictor")
    parser.add_argument("--pairs", default="BTC/USDT,ETH/USDT,SOL/USDT,XRP/USDT,DOGE/USDT,PEPE/USDT")
    parser.add_argument("--n-estimators", type=int, default=200)
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--evaluate-only", action="store_true")
    args = parser.parse_args()
    
    pairs = [p.strip() for p in args.pairs.split(",")]
    
    if args.evaluate_only:
        if not XGB_MODEL_PATH.exists():
            print("No model found. Train first.")
            return
        
        model = load_model_for_pi(XGB_MODEL_PATH)
        if model is None:
            print("Cannot load model")
            return
        
        # Evaluate on fresh data
        all_candles = []
        for pair in pairs:
            try:
                candles = fetch_binance_candles(pair, limit=200)
                all_candles.extend(candles)
            except Exception:
                pass
        
        X, y, feature_names = prepare_dataset_v2(all_candles)
        y_pred = model.predict(X)
        acc = accuracy_score(y, y_pred)
        print(f"Accuracy on fresh data: {acc:.3f}")
        print(classification_report(y, y_pred, target_names=["hold", "buy", "sell"]))
        return
    
    result = run_training(pairs, args.n_estimators, args.max_depth)
    
    print("\n" + "=" * 50)
    print(json.dumps({k: v for k, v in result.items() if k != "top_features"}, indent=2))
    if result.get("top_features"):
        print("\nTop features:")
        for name, imp in result["top_features"]:
            print(f"  {name}: {imp:.3f}")


if __name__ == "__main__":
    main()
