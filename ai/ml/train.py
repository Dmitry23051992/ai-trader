"""Train LSTM candle predictor on Binance OHLCV data.

Usage:
    python -m ai.ml.train [--pairs BTCUSDT,ETHUSDT] [--timeframe 15m] [--epochs 50]

Trains on PC, exports .npz weights for pure-numpy inference on Raspberry Pi.
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

# ── Config ───────────────────────────────────────────────────

BINANCE_API = "https://api.binance.com"
DEFAULT_PAIRS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT", "SHIBUSDT", "PEPEUSDT", "BONKUSDT", "FLOKIUSDT",
    "WIFUSDT", "MEMEUSDT", "TURBOUSDT", "PEOPLEUSDT"
]
DEFAULT_TIMEFRAME = "15m"
DEFAULT_LIMIT = 1500  # ~15 days of 15m candles per pair
SEQ_LEN = 20
INPUT_SIZE = 10
HIDDEN_SIZE = 64
NUM_LAYERS = 2
OUTPUT_SIZE = 3  # buy, hold, sell

# Labeling: if price goes up > THRESHOLD in next N candles → buy
BUY_THRESHOLD = 0.5   # % price increase to label as buy
SELL_THRESHOLD = -0.5  # % price decrease to label as sell
FUTURE_CANDLES = 4     # look 4 candles ahead (1 hour)

EXPORT_DIR = Path(__file__).parent / "models"


# ── Data Download ────────────────────────────────────────────

def fetch_ohlcv(symbol: str, interval: str = "15m", limit: int = 1000) -> list[dict]:
    """Download OHLCV from Binance."""
    url = f"{BINANCE_API}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "ai-trader-trainer/1.0")
        with urllib.request.urlopen(req, timeout=30) as resp:
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
        print(f"  Error fetching {symbol}: {e}")
        return []


# ── Feature Extraction (same as candle_features.py) ──────

def sma(data: np.ndarray, period: int) -> np.ndarray:
    result = np.full_like(data, np.nan, dtype=np.float64)
    for i in range(period - 1, len(data)):
        result[i] = np.mean(data[i - period + 1: i + 1])
    return result


def ema(data: np.ndarray, period: int) -> np.ndarray:
    result = np.full_like(data, np.nan, dtype=np.float64)
    alpha = 2.0 / (period + 1)
    if len(data) >= period:
        result[period - 1] = np.mean(data[:period])
        for i in range(period, len(data)):
            result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
    return result


def rsi(data: np.ndarray, period: int = 14) -> np.ndarray:
    deltas = np.diff(data, prepend=data[0])
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = ema(gains, period)
    avg_loss = ema(losses, period)
    rs = np.where(avg_loss > 0, avg_gain / avg_loss, 100.0)
    return 100.0 - (100.0 / (1.0 + rs))


def macd(data: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = ema(data, fast)
    ema_slow = ema(data, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr1 = high - low
    tr2 = np.abs(high - prev_close)
    tr3 = np.abs(low - prev_close)
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    return ema(tr, period)


def extract_features(candles: list[dict]) -> np.ndarray:
    """Extract 10 features from OHLCV candles."""
    opens = np.array([c["open"] for c in candles], dtype=np.float64)
    highs = np.array([c["high"] for c in candles], dtype=np.float64)
    lows = np.array([c["low"] for c in candles], dtype=np.float64)
    closes = np.array([c["close"] for c in candles], dtype=np.float64)
    volumes = np.array([c["volume"] for c in candles], dtype=np.float64)

    ranges = highs - lows
    ranges = np.where(ranges == 0, 1e-10, ranges)
    closes_safe = np.where(closes == 0, 1e-10, closes)

    features = np.column_stack([
        (closes - opens) / ranges,                                           # body_ratio
        (highs - np.maximum(opens, closes)) / ranges,                        # upper_shadow
        (np.minimum(opens, closes) - lows) / ranges,                         # lower_shadow
        ranges / closes_safe * 100.0,                                        # range_pct
        volumes / np.where(sma(volumes, 20) == 0, 1e-10, sma(volumes, 20)), # vol_relative
        np.diff(np.concatenate([[closes[0]], closes])) /                     # change_pct
            np.where(np.roll(closes, 1) == 0, 1e-10, np.roll(closes, 1)) * 100,
        (closes - sma(closes, 20)) / np.where(sma(closes, 20) == 0, 1e-10, sma(closes, 20)) * 100,  # sma20_dist
        rsi(closes, 14) / 100.0,                                             # rsi_norm
        np.where(closes_safe == 0, 0.0, (macd(closes)[0] - macd(closes)[1]) / closes_safe * 1000),  # macd_norm
        np.where(closes_safe == 0, 0.0, atr(highs, lows, closes, 14) / closes_safe * 100.0),        # atr_norm
    ])

    return features


# ── Labeling ─────────────────────────────────────────────────

def create_labels(candles: list[dict], buy_thresh: float, sell_thresh: float,
                  future_n: int) -> np.ndarray:
    """Create buy/hold/sell labels based on future price movement.
    
    Returns:
        labels: (N,) array of 0=buy, 1=hold, 2=sell
    """
    closes = np.array([c["close"] for c in candles], dtype=np.float64)
    n = len(closes)
    labels = np.ones(n, dtype=np.int64)  # default: hold (1)

    for i in range(n - future_n):
        future_change = (closes[i + future_n] - closes[i]) / closes[i] * 100
        if future_change >= buy_thresh:
            labels[i] = 0  # buy
        elif future_change <= sell_thresh:
            labels[i] = 2  # sell

    return labels


# ── Dataset ──────────────────────────────────────────────────

class CandleDataset(Dataset):
    def __init__(self, features: np.ndarray, labels: np.ndarray, seq_len: int = 20):
        self.seq_len = seq_len
        # Create sequences
        self.sequences = []
        self.targets = []
        for i in range(seq_len, len(features)):
            seq = features[i - seq_len: i]
            self.sequences.append(seq)
            self.targets.append(labels[i])
        self.sequences = np.array(self.sequences, dtype=np.float32)
        self.targets = np.array(self.targets, dtype=np.int64)

    def __len__(self):
        return len(self.targets)

    def __getitem__(self, idx):
        return (
            torch.tensor(self.sequences[idx], dtype=torch.float32),
            torch.tensor(self.targets[idx], dtype=torch.long)
        )


# ── Model ────────────────────────────────────────────────────

class CandleLSTM(nn.Module):
    """2-layer LSTM → Linear → output logits."""

    def __init__(self, input_size=10, hidden_size=64, num_layers=2, output_size=3):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True
        )
        self.fc = nn.Linear(hidden_size, output_size)

    def forward(self, x):
        # x: (batch, seq_len, input_size)
        lstm_out, (h_n, c_n) = self.lstm(x)
        last_hidden = lstm_out[:, -1, :]  # (batch, hidden_size)
        logits = self.fc(last_hidden)
        return logits


# ── Training ─────────────────────────────────────────────────

def train_model(model, train_loader, val_loader, epochs=50, lr=0.001, device="cpu",
                class_weights=None):
    """Train the model."""
    model = model.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=5, factor=0.5)
    if class_weights is not None:
        criterion = nn.CrossEntropyLoss(weight=class_weights.to(device))
    else:
        criterion = nn.CrossEntropyLoss()

    best_val_loss = float("inf")
    best_state = None

    for epoch in range(epochs):
        # Training
        model.train()
        train_loss = 0
        train_correct = 0
        train_total = 0

        for batch_x, batch_y in train_loader:
            batch_x, batch_y = batch_x.to(device), batch_y.to(device)
            optimizer.zero_grad()
            logits = model(batch_x)
            loss = criterion(logits, batch_y)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

            train_loss += loss.item() * len(batch_y)
            preds = logits.argmax(dim=1)
            train_correct += (preds == batch_y).sum().item()
            train_total += len(batch_y)

        train_loss /= train_total
        train_acc = train_correct / train_total

        # Validation
        model.eval()
        val_loss = 0
        val_correct = 0
        val_total = 0

        with torch.no_grad():
            for batch_x, batch_y in val_loader:
                batch_x, batch_y = batch_x.to(device), batch_y.to(device)
                logits = model(batch_x)
                loss = criterion(logits, batch_y)
                val_loss += loss.item() * len(batch_y)
                preds = logits.argmax(dim=1)
                val_correct += (preds == batch_y).sum().item()
                val_total += len(batch_y)

        val_loss /= val_total if val_total > 0 else 1
        val_acc = val_correct / val_total if val_total > 0 else 0

        scheduler.step(val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}

        if (epoch + 1) % 5 == 0 or epoch == 0:
            print(f"  Epoch {epoch+1:3d}/{epochs} | "
                  f"train_loss={train_loss:.4f} acc={train_acc:.1%} | "
                  f"val_loss={val_loss:.4f} acc={val_acc:.1%}")

    if best_state:
        model.load_state_dict(best_state)
    return model


# ── Export to .npz ───────────────────────────────────────────

def export_weights(model: CandleLSTM, scaler_min: np.ndarray,
                   scaler_max: np.ndarray, output_path: Path):
    """Export PyTorch model to .npz for pure-numpy inference on Pi.
    
    PyTorch LSTM stores weights as stacked [i,g,f,o] gates.
    We split them into separate arrays matching lstm_numpy.py expectations.
    """
    state = model.state_dict()

    # Layer 1 LSTM
    w_ih_1 = state["lstm.weight_ih_l0"].numpy()   # (4*hidden, input)
    b_ih_1 = state["lstm.bias_ih_l0"].numpy()     # (4*hidden,)
    w_hh_1 = state["lstm.weight_hh_l0"].numpy()   # (4*hidden, hidden)
    b_hh_1 = state["lstm.bias_hh_l0"].numpy()     # (4*hidden,)

    # Layer 2 LSTM
    w_ih_2 = state["lstm.weight_ih_l1"].numpy()   # (4*hidden, hidden)
    b_ih_2 = state["lstm.bias_ih_l1"].numpy()     # (4*hidden,)
    w_hh_2 = state["lstm.weight_hh_l1"].numpy()   # (4*hidden, hidden)
    b_hh_2 = state["lstm.bias_hh_l1"].numpy()     # (4*hidden,)

    # Linear layer
    fc_weight = state["fc.weight"].numpy().T       # transpose: (hidden, output)
    fc_bias = state["fc.bias"].numpy()             # (output,)

    # Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        output_path,
        lstm1_w_ih=w_ih_1,
        lstm1_b_ih=b_ih_1,
        lstm1_w_hh=w_hh_1,
        lstm1_b_hh=b_hh_1,
        lstm2_w_ih=w_ih_2,
        lstm2_b_ih=b_ih_2,
        lstm2_w_hh=w_hh_2,
        lstm2_b_hh=b_hh_2,
        fc_weight=fc_weight,
        fc_bias=fc_bias,
        scaler_min=scaler_min.astype(np.float32),
        scaler_max=scaler_max.astype(np.float32),
    )
    print(f"\n✅ Weights exported to: {output_path}")
    print(f"   File size: {output_path.stat().st_size / 1024:.1f} KB")


# ── Main ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Train LSTM candle predictor")
    parser.add_argument("--pairs", default=",".join(DEFAULT_PAIRS),
                       help="Comma-separated Binance pair symbols")
    parser.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                       help="Candles per pair to download")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=0.001)
    parser.add_argument("--seq-len", type=int, default=SEQ_LEN)
    parser.add_argument("--buy-thresh", type=float, default=BUY_THRESHOLD)
    parser.add_argument("--sell-thresh", type=float, default=SELL_THRESHOLD)
    parser.add_argument("--future-candles", type=int, default=FUTURE_CANDLES)
    parser.add_argument("--output", default=str(EXPORT_DIR / "candle_lstm_v1.npz"))
    args = parser.parse_args()

    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    print(f"═══ LSTM Candle Predictor Training ═══")
    print(f"Pairs: {len(pairs)} ({pairs[0]}...{pairs[-1]})")
    print(f"Timeframe: {args.timeframe}, Limit: {args.limit}")
    print(f"Epochs: {args.epochs}, Batch: {args.batch_size}, LR: {args.lr}")
    print(f"Labels: buy>{args.buy_thresh}%, sell<{args.sell_thresh}%, future={args.future_candles}c")
    print()

    # 1. Download data
    print("📥 Downloading OHLCV data...")
    all_features = []
    all_labels = []
    total_candles = 0

    for i, pair in enumerate(pairs):
        candles = fetch_ohlcv(pair, args.timeframe, args.limit)
        if len(candles) < args.seq_len + args.future_candles + 10:
            print(f"  [{i+1}/{len(pairs)}] {pair}: SKIP ({len(candles)} candles, need {args.seq_len + args.future_candles + 10})")
            continue

        features = extract_features(candles)
        labels = create_labels(candles, args.buy_thresh, args.sell_thresh, args.future_candles)

        all_features.append(features)
        all_labels.append(labels)
        total_candles += len(candles)

        buy_count = (labels == 0).sum()
        hold_count = (labels == 1).sum()
        sell_count = (labels == 2).sum()
        print(f"  [{i+1}/{len(pairs)}] {pair}: {len(candles)} candles, labels: buy={buy_count} hold={hold_count} sell={sell_count}")

        # Rate limit
        if i < len(pairs) - 1:
            time.sleep(0.2)

    if not all_features:
        print("❌ No data collected!")
        sys.exit(1)

    print(f"\n📊 Total candles: {total_candles}")

    # 2. Concatenate and normalize
    features_all = np.vstack(all_features)
    labels_all = np.concatenate(all_labels)

    # Compute scaler from full dataset
    scaler_min = np.nanmin(features_all, axis=0)
    scaler_max = np.nanmax(features_all, axis=0)
    scaler_range = scaler_max - scaler_min
    scaler_range = np.where(scaler_range == 0, 1e-10, scaler_range)
    features_norm = (features_all - scaler_min) / scaler_range
    features_norm = np.nan_to_num(features_norm, nan=0.0)

    print(f"Features shape: {features_norm.shape}")
    print(f"Label distribution: buy={((labels_all==0).sum())} hold={((labels_all==1).sum())} sell={((labels_all==2).sum())}")

    # 3. Train/val split (80/20)
    split = int(len(features_norm) * 0.8)
    train_ds = CandleDataset(features_norm[:split], labels_all[:split], args.seq_len)
    val_ds = CandleDataset(features_norm[split:], labels_all[split:], args.seq_len)

    print(f"Train: {len(train_ds)} samples, Val: {len(val_ds)} samples")

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False)

    # 4. Train
    print(f"\n🔥 Training LSTM ({NUM_LAYERS} layers × {HIDDEN_SIZE} hidden)...")
    model = CandleLSTM(INPUT_SIZE, HIDDEN_SIZE, NUM_LAYERS, OUTPUT_SIZE)
    param_count = sum(p.numel() for p in model.parameters())
    print(f"Model parameters: {param_count:,}")

    model = train_model(model, train_loader, val_loader,
                       epochs=args.epochs, lr=args.lr)

    # 5. Export
    output_path = Path(args.output)
    export_weights(model, scaler_min, scaler_max, output_path)

    # 6. Verify with numpy inference
    print("\n🔍 Verifying numpy inference...")
    try:
        from ai.ml.lstm_numpy import load_model
        from ai.ml.candle_features import normalize_features, create_sequence

        np_model = load_model(str(output_path))

        # Take a sample sequence
        sample_features = features_all[-SEQ_LEN:]
        sample_norm = normalize_features(sample_features)
        sample_seq = create_sequence(sample_norm, SEQ_LEN)

        probs = np_model.predict(sample_seq)
        print(f"   Sample prediction: buy={probs[0]:.1%} hold={probs[1]:.1%} sell={probs[2]:.1%}")
        print("   ✅ Numpy inference OK!")
    except Exception as e:
        print(f"   ⚠️ Numpy verification failed: {e}")

    print(f"\n🎉 Done! Deploy {output_path} to Pi:")
    print(f"   scp {output_path} user@100.109.236.50:/home/user/ai-trader/ai/ml/models/")


if __name__ == "__main__":
    main()
