"""
High-level prediction API v3 — LSTM + XGBoost + RL + Outcome Tracking.

v3: Added XGBoost backend (pure numpy inference).
  - Dual model: LSTM (10 features, sequence) + XGBoost (23 features, single candle)
  - XGBoost is primary (86.8% val acc), LSTM is secondary
  - Ensemble: weighted average of both models
  - RL can override when confident
"""

import os
import time
import numpy as np
from pathlib import Path

from ai.ml.candle_features import extract_features, normalize_features, create_sequence
from ai.ml.lstm_numpy import load_model, CandlePredictorModel

# Lazy imports for optional modules
_tracker = None
_rl_trader = None
_xgb_model = None


def _get_tracker():
    global _tracker
    if _tracker is None:
        try:
            from ai.ml.outcome_tracker import get_tracker
            _tracker = get_tracker()
        except Exception:
            pass
    return _tracker


def _get_rl_trader():
    global _rl_trader
    if _rl_trader is None:
        try:
            from ai.ml.rl_agent import get_rl_trader
            _rl_trader = get_rl_trader()
        except Exception:
            pass
    return _rl_trader


def _get_xgb():
    """Lazy-load XGBoost numpy model."""
    global _xgb_model
    if _xgb_model is None:
        try:
            from ai.ml.xgb_numpy import XGBoostNumpy
            xgb_path = Path(__file__).parent / "models" / "candle_xgboost_v1.json"
            if xgb_path.exists():
                _xgb_model = XGBoostNumpy(str(xgb_path))
        except Exception as e:
            print(f"[Predictor] XGBoost load error: {e}")
    return _xgb_model


# Model paths
DEFAULT_LSTM_PATH = Path(__file__).parent / "models" / "candle_lstm_v1.npz"
XGB_MODEL_PATH = Path(__file__).parent / "models" / "candle_xgboost_v1.json"

# Singleton
_predictor_instance = None


def get_predictor(model_path: str = None) -> "CandlePredictor":
    """Get or create singleton CandlePredictor."""
    global _predictor_instance
    if _predictor_instance is None:
        _predictor_instance = CandlePredictor(model_path)
    return _predictor_instance


def reset_predictor():
    """Reset singleton (useful for reloading model)."""
    global _predictor_instance
    _predictor_instance = None


class CandlePredictor:
    """Wraps LSTM + XGBoost + RL models for candle prediction with self-learning."""

    def __init__(self, model_path: str = None):
        self.lstm_path = Path(model_path) if model_path else DEFAULT_LSTM_PATH
        self.lstm_model = None
        self.fallback_mode = True
        self._prediction_count = 0

        # Load LSTM
        if self.lstm_path.exists():
            try:
                self.lstm_model = load_model(str(self.lstm_path))
                print(f"[CandlePredictor] LSTM loaded from {self.lstm_path}")
            except Exception as e:
                print(f"[CandlePredictor] Failed to load LSTM: {e}")
                self.lstm_model = None
        
        # XGBoost loads lazily on first use
        self._xgb_checked = False

    def _get_lstm_probs(self, candles: list, seq_len: int = 20) -> tuple:
        """Get LSTM predictions. Returns (buy, hold, sell) or None."""
        if self.lstm_model is None:
            return None
        
        try:
            # Detect v2 model (has fc2 layer = MLP head)
            if self.lstm_model.fc2 is not None:
                # v2: 23 features, no normalization needed
                from ai.ml.candle_features_v2 import extract_features_v2
                features = extract_features_v2(candles)
                if len(features) < seq_len:
                    return None
                # Take last seq_len rows as (seq_len, 23)
                sequence = features[-seq_len:].astype(np.float64)
                sequence = sequence[np.newaxis, :]  # (1, seq_len, 23)
            else:
                # v1: 10 features with normalization
                features = extract_features(candles)
                normalized = normalize_features(features)
                sequence = create_sequence(normalized, seq_len)
            
            probs = self.lstm_model.predict(sequence)
            return float(probs[0]), float(probs[1]), float(probs[2])
        except Exception as e:
            print(f"[Predictor] LSTM predict error: {e}")
            return None

    def _get_xgb_probs(self, candles: list) -> tuple:
        """Get XGBoost predictions. Returns (buy, hold, sell) or None."""
        xgb = _get_xgb()
        if xgb is None or not xgb.available:
            return None
        
        try:
            from ai.ml.candle_features_v2 import extract_features_v2
            features = extract_features_v2(candles)
            if len(features) == 0:
                return None
            # Use last candle
            last_features = features[-1:].astype(np.float32)
            probs = xgb.predict_proba(last_features)
            return float(probs[0][1]), float(probs[0][0]), float(probs[0][2])
            # Note: XGBoost classes: 0=hold, 1=buy, 2=sell
        except Exception as e:
            print(f"[Predictor] XGBoost predict error: {e}")
            return None

    def _temperature_scale(self, buy: float, hold: float, sell: float, temp: float = 0.7) -> tuple:
        """Apply temperature-scaled softmax."""
        exps = np.exp(np.array([buy, hold, sell]) / temp)
        scaled = exps / exps.sum()
        return float(scaled[0]), float(scaled[1]), float(scaled[2])

    def _determine_signal(self, buy: float, hold: float, sell: float, margin: float = 0.10) -> str:
        """Determine signal from probabilities."""
        if buy > hold + margin and buy > sell + margin:
            return "buy"
        elif sell > hold + margin and sell > buy + margin:
            return "sell"
        else:
            return "hold"

    def analyze(self, candles: list[dict], seq_len: int = 20,
                pair: str = None) -> dict:
        """Analyze candles and return prediction.
        
        Uses ensemble of XGBoost (primary) + LSTM (secondary).
        
        Args:
            candles: List of OHLCV dicts
            seq_len: Sequence length for LSTM
            pair: Pair name for tracking
            
        Returns:
            dict with 'buy', 'hold', 'sell' probs and 'signal'
        """
        if len(candles) < 10:
            return self._fallback("insufficient data")

        try:
            # ── Get predictions from both models ────────────
            lstm_result = self._get_lstm_probs(candles, seq_len)
            xgb_result = self._get_xgb_probs(candles)
            
            models_used = []
            
            # ── Ensemble: weighted average ──────────────────
            if xgb_result is not None and lstm_result is not None:
                # XGBoost: 86.8% val acc, LSTM: ~60% val acc
                # Weight: XGBoost 0.7, LSTM 0.3
                xgb_buy, xgb_hold, xgb_sell = xgb_result
                lstm_buy, lstm_hold, lstm_sell = lstm_result
                
                buy = 0.7 * xgb_buy + 0.3 * lstm_buy
                hold = 0.7 * xgb_hold + 0.3 * lstm_hold
                sell = 0.7 * xgb_sell + 0.3 * lstm_sell
                models_used = ["xgboost", "lstm"]
                
            elif xgb_result is not None:
                buy, hold, sell = xgb_result
                models_used = ["xgboost"]
                
            elif lstm_result is not None:
                buy, hold, sell = lstm_result
                models_used = ["lstm"]
                
            else:
                return self._fallback("no model available")

            # Temperature scaling
            buy_s, hold_s, sell_s = self._temperature_scale(buy, hold, sell)
            
            # Determine signal
            signal = self._determine_signal(buy_s, hold_s, sell_s)

            # ── RL Integration ──────────────────────────────
            rl_signal = None
            rl_confidence = 0.0
            rl_available = False
            
            rl_trader = _get_rl_trader()
            if rl_trader and rl_trader.available:
                try:
                    features = extract_features(candles)
                    if features is not None and len(features.shape) > 1:
                        market_features = features[-1]
                        rl_result = rl_trader.decide(
                            pair or "unknown",
                            market_features.astype(np.float32),
                            is_holding=False
                        )
                        rl_signal = rl_result["action"]
                        rl_confidence = rl_result["confidence"]
                        rl_available = True
                except Exception:
                    pass

            # ── Combine Ensemble + RL ───────────────────────
            if rl_available and rl_signal in ("buy", "sell"):
                if rl_signal == signal:
                    confidence_boost = 0.1
                    if signal == "buy":
                        buy = min(buy + confidence_boost, 0.95)
                    elif signal == "sell":
                        sell = min(sell + confidence_boost, 0.95)
                elif rl_signal != "hold" and signal == "hold":
                    if rl_confidence > 0.6:
                        signal = rl_signal
                        if rl_signal == "buy":
                            buy = max(buy, 0.45)
                        elif rl_signal == "sell":
                            sell = max(sell, 0.45)

            result = {
                "buy": round(buy, 4),
                "hold": round(hold, 4),
                "sell": round(sell, 4),
                "signal": signal,
                "model": "+".join(models_used),
                "fallback": False,
            }
            
            # RL info
            if rl_available:
                result["rl_signal"] = rl_signal
                result["rl_confidence"] = round(rl_confidence, 4)

            # ── Outcome Tracking ────────────────────────────
            self._prediction_count += 1
            if pair and pair != "unknown":
                tracker = _get_tracker()
                if tracker:
                    try:
                        current_price = float(candles[-1]["close"])
                        tracker.log_prediction(
                            pair=pair,
                            prediction=signal,
                            confidence=max(buy, hold, sell),
                            current_price=current_price,
                            features={"models": models_used}
                        )
                    except Exception:
                        pass

            return result
        except Exception as e:
            return self._fallback(str(e))

    def analyze_batch(self, pairs_data: dict[str, list[dict]], seq_len: int = 20) -> dict:
        """Analyze multiple pairs.
        
        Args:
            pairs_data: {pair_name: [candle_dicts]}
            
        Returns:
            {pair_name: analysis_result}
        """
        results = {}
        for pair, candles in pairs_data.items():
            results[pair] = self.analyze(candles, seq_len, pair=pair)
        return results

    def format_for_llm(self, results: dict) -> str:
        """Format results for inclusion in LLM prompt.
        
        Args:
            results: Dict from analyze_batch
            
        Returns:
            String formatted for LLM consumption
        """
        lines = ["AI Model (XGBoost + LSTM + RL) predictions:"]
        for pair, res in results.items():
            signal = res.get("signal", "unknown")
            buy = res.get("buy", 0)
            hold = res.get("hold", 0)
            sell = res.get("sell", 0)
            fallback = " [FALLBACK]" if res.get("fallback") else ""
            model_info = f" [{res.get('model', '?')}]"
            rl_info = ""
            if res.get("rl_signal"):
                rl_info = f" RL={res['rl_signal']}"
            lines.append(
                f"  {pair}: {signal.upper()}{model_info} "
                f"(buy={buy:.1%} hold={hold:.1%} sell={sell:.1%}){fallback}{rl_info}"
            )
        
        # Add accuracy stats
        tracker = _get_tracker()
        if tracker:
            try:
                acc = tracker.get_accuracy(days=7)
                if acc["total"] > 0:
                    lines.append(f"\n  📊 Model accuracy (7d): {acc['accuracy']:.0%} "
                                 f"({acc['total']} predictions, "
                                 f"avg_reward={acc['avg_reward']:+.3f})")
            except Exception:
                pass
        
        # Add RL status
        rl_trader = _get_rl_trader()
        if rl_trader and rl_trader.available:
            status = rl_trader.get_status()
            lines.append(f"  🧠 RL: {status['experiences']} experiences, "
                         f"epsilon={status['epsilon']:.2f}")
        
        # Add XGBoost status
        xgb = _get_xgb()
        if xgb and xgb.available:
            lines.append(f"  🌲 XGBoost: {xgb.num_trees_per_class} trees/class, "
                         f"{xgb.num_features} features")
        
        return "\n".join(lines)

    def get_learning_stats(self) -> dict:
        """Получить статистику самообучения."""
        stats = {
            "lstm_loaded": self.lstm_model is not None,
            "total_predictions": self._prediction_count,
        }
        
        xgb = _get_xgb()
        if xgb:
            stats["xgboost_loaded"] = xgb.available
            stats["xgboost_trees"] = xgb.num_trees_per_class
        
        tracker = _get_tracker()
        if tracker:
            try:
                stats["accuracy_7d"] = tracker.get_accuracy(days=7)
                stats["pending_outcomes"] = tracker.get_pending_predictions_count()
                stats["total_stored"] = tracker.get_total_predictions()
            except Exception:
                pass
        
        rl_trader = _get_rl_trader()
        if rl_trader:
            stats["rl"] = rl_trader.get_status()
        
        return stats

    def _fallback(self, reason: str) -> dict:
        return {
            "buy": 0.33,
            "hold": 0.34,
            "sell": 0.33,
            "signal": "hold",
            "model": "fallback",
            "fallback": True,
            "reason": reason,
        }
