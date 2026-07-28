"""Pure numpy LSTM forward pass — NO PyTorch needed on Raspberry Pi.

Поддерживает две архитектуры:
  v1: Input(10) → LSTM(2 layers × hidden=64) → Linear(64→3) → Softmax
  v2: Input(23) → LSTM(2 layers × hidden=128) → LayerNorm → MLP(128→64→3) → Softmax

Output: [buy_prob, hold_prob, sell_prob]
"""

import numpy as np


class NumpyLinear:
    """Simple linear layer: y = x @ W + T"""

    def __init__(self, weight: np.ndarray, bias: np.ndarray):
        self.weight = weight  # (in_features, out_features)
        self.bias = bias      # (out_features,)

    def forward(self, x: np.ndarray) -> np.ndarray:
        return x @ self.weight + self.bias


class NumpyLSTM:
    """Single LSTM layer forward pass."""

    def __init__(self, w_ih: np.ndarray, b_ih: np.ndarray,
                 w_hh: np.ndarray, b_hh: np.ndarray):
        """
        Args:
            w_ih: (4*hidden, input_size) — input-to-hidden weights
            b_ih: (4*hidden,)           — input-to-hidden bias
            w_hh: (4*hidden, hidden)    — hidden-to-hidden weights
            b_hh: (4*hidden,)           — hidden-to-hidden bias
        """
        self.w_ih = w_ih
        self.b_ih = b_ih
        self.w_hh = w_hh
        self.b_hh = b_hh
        self.hidden_size = w_hh.shape[0] // 4

    def forward(self, x_seq: np.ndarray, h0: np.ndarray = None, c0: np.ndarray = None):
        """Forward pass through time steps.
        
        Args:
            x_seq: (seq_len, input_size)
            h0: (1, hidden_size) initial hidden state
            c0: (1, hidden_size) initial cell state
            
        Returns:
            h_n: (1, hidden_size) final hidden state
            c_n: (1, hidden_size) final cell state
        """
        seq_len, input_size = x_seq.shape
        hs = self.hidden_size

        if h0 is None:
            h = np.zeros((1, hs), dtype=np.float64)
        else:
            h = h0.copy()
        if c0 is None:
            c = np.zeros((1, hs), dtype=np.float64)
        else:
            c = c0.copy()

        for t in range(seq_len):
            x_t = x_seq[t:t+1]  # (1, input_size)
            gates = x_t @ self.w_ih.T + self.b_ih + h @ self.w_hh.T + self.b_hh
            i_gate = _sigmoid(gates[:, :hs])
            f_gate = _sigmoid(gates[:, hs:2*hs])
            g_gate = np.tanh(gates[:, 2*hs:3*hs])
            o_gate = _sigmoid(gates[:, 3*hs:])

            c = f_gate * c + i_gate * g_gate
            h = o_gate * np.tanh(c)

        return h, c


class NumpyLayerNorm:
    """Simple Layer Normalization."""
    
    def __init__(self, weight: np.ndarray, bias: np.ndarray):
        self.weight = weight
        self.bias = bias
    
    def forward(self, x: np.ndarray) -> np.ndarray:
        mean = np.mean(x, axis=-1, keepdims=True)
        var = np.var(x, axis=-1, keepdims=True)
        return self.weight * (x - mean) / np.sqrt(var + 1e-5) + self.bias


class CandlePredictorModel:
    """Full model: 2-layer LSTM → (optional LayerNorm) → Linear → Softmax
    
    Поддерживает v1 (простой Linear head) и v2 (LayerNorm + MLP head).
    """

    def __init__(self, lstm1: NumpyLSTM, lstm2: NumpyLSTM,
                 fc: NumpyLinear, scaler_min: np.ndarray = None,
                 scaler_max: np.ndarray = None,
                 fc2: NumpyLinear = None,
                 layernorm: NumpyLayerNorm = None):
        self.lstm1 = lstm1
        self.lstm2 = lstm2
        self.fc = fc
        self.fc2 = fc2
        self.layernorm = layernorm
        self.scaler_min = scaler_min
        self.scaler_max = scaler_max

    def predict(self, x_seq: np.ndarray) -> np.ndarray:
        """Run forward pass.
        
        Args:
            x_seq: (1, seq_len, input_size) normalized features
            
        Returns:
            probs: (3,) — [buy, hold, sell] probabilities
        """
        seq = x_seq[0]  # (seq_len, input_size)

        h1, c1 = self.lstm1.forward(seq)
        h2, c2 = self.lstm2.forward(h1)

        # v2: LayerNorm + MLP head
        if self.layernorm is not None:
            h2 = self.layernorm.forward(h2)
        
        # v2: MLP head (128→64→3)
        if self.fc2 is not None:
            logits = self.fc2.forward(h2)       # 128→64
            logits = np.maximum(logits, 0)      # ReLU
            logits = self.fc.forward(logits)     # 64→3
        else:
            logits = self.fc.forward(h2)         # v1: 64→3
        
        probs = _softmax(logits[0])
        return probs


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -500, 500)))


def _softmax(x: np.ndarray) -> np.ndarray:
    e_x = np.exp(x - np.max(x))
    return e_x / e_x.sum()


def load_model(path: str) -> CandlePredictorModel:
    """Load model weights from .npz file.
    
    Поддерживает два формата:
    
    v1 (старый, 10 features):
        lstm1_w_ih, lstm1_b_ih, lstm1_w_hh, lstm1_b_hh
        lstm2_w_ih, lstm2_b_ih, lstm2_w_hh, lstm2_b_hh
        fc_weight, fc_bias
        scaler_min, scaler_max
    
    v2 (новый, 23 features):
        W_ii, b_ii, W_hi, b_hi  (LSTMCell format)
        W_ii2, b_ii2, W_hi2, b_hi2
        fc_weight, fc_bias  (first linear layer)
        fc2_weight, fc2_bias  (second linear layer)
        bn_weight, bn_bias  (LayerNorm)
        input_size, hidden_size
    """
    data = np.load(path, allow_pickle=False)
    
    # Detect format: v1 has lstm1_w_ih, v2 has W_ii
    is_v2 = "W_ii" in data
    
    if is_v2:
        # ── v2 format (LSTMCell) ──────────────────────────
        hidden_size = int(data.get("hidden_size", np.array([128]))[0])
        
        # LSTMCell stores gates in i,f,g,o order — same as NumpyLSTM
        # weight_ih: (4*hidden, input_size), weight_hh: (4*hidden, hidden)
        # No reordering needed
        
        lstm1 = NumpyLSTM(data["W_ii"], data["b_ii"], data["W_hi"], data["b_hi"])
        lstm2 = NumpyLSTM(data["W_ii2"], data["b_ii2"], data["W_hi2"], data["b_hi2"])
        
        # Head layers
        # PyTorch saves weight as (out_features, in_features)
        # NumpyLinear expects (in_features, out_features) → need transpose
        fc2 = NumpyLinear(data["fc2_weight"].T, data["fc2_bias"])  # 128→64
        fc = NumpyLinear(data["fc_weight"].T, data["fc_bias"])     # 64→3
        
        layernorm = None
        if "bn_weight" in data:
            layernorm = NumpyLayerNorm(data["bn_weight"], data["bn_bias"])
        
        return CandlePredictorModel(lstm1, lstm2, fc, fc2=fc2, layernorm=layernorm)
    
    else:
        # ── v1 format (old, 10 features) ──────────────────
        lstm1 = NumpyLSTM(
            data["lstm1_w_ih"], data["lstm1_b_ih"],
            data["lstm1_w_hh"], data["lstm1_b_hh"]
        )
        lstm2 = NumpyLSTM(
            data["lstm2_w_ih"], data["lstm2_b_ih"],
            data["lstm2_w_hh"], data["lstm2_b_hh"]
        )
        fc = NumpyLinear(data["fc_weight"], data["fc_bias"])

        scaler_min = data.get("scaler_min")
        scaler_max = data.get("scaler_max")

        return CandlePredictorModel(lstm1, lstm2, fc, scaler_min, scaler_max)
