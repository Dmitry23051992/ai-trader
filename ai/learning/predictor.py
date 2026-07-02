"""
ML-based adaptive parameter predictor.

Replaces simple rule-based adaptive thresholds with a
GradientBoostingRegressor that predicts optimal trading parameters
based on market features and historical performance.

Usage:
    predictor = AdaptivePredictor()
    predictor.train(features, targets)
    params = predictor.predict(market_state)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler

from configs.settings import MODEL_DIR, RANDOM_SEED
from core.logger import log


class AdaptivePredictor:
    """ML model for predicting optimal position sizing and risk parameters."""

    def __init__(self, model_dir: Path | str | None = None):
        self.model_dir = Path(model_dir or MODEL_DIR)
        self.model_dir.mkdir(parents=True, exist_ok=True)

        self.model_path = self.model_dir / "adaptive_model.joblib"
        self.scaler_path = self.model_dir / "adaptive_scaler.joblib"

        # Three separate regressors for different targets
        self._models: dict[str, GradientBoostingRegressor] = {}
        self._scaler: StandardScaler | None = None
        self._is_trained = False
        self._feature_names: list[str] = []

        self._load_or_init()

    # ── Public API ────────────────────────────────────────────────────

    def train(
        self,
        features: list[dict[str, float]],
        targets: list[dict[str, float]],
    ) -> dict[str, float]:
        """Train models on historical feature-target pairs.

        Args:
            features: List of feature dicts, each containing market metrics.
            targets: List of target dicts with keys like
                     ``position_size_multiplier``, ``stop_loss_multiplier``,
                     ``take_profit_multiplier``, ``confidence_threshold``.

        Returns:
            Dict of training metrics (R² score per target).
        """
        if len(features) < 10:
            log.warning(
                "AdaptivePredictor: {} samples is too few for reliable training. "
                "Need at least 10.", len(features)
            )
            return {"trained": False, "reason": "insufficient_samples", "n": len(features)}

        X = self._build_feature_matrix(features)
        self._feature_names = list(features[0].keys())

        self._scaler = StandardScaler()
        X_scaled = self._scaler.fit_transform(X)

        scores: dict[str, float] = {}
        target_keys = list(targets[0].keys())

        for key in target_keys:
            y = np.array([t[key] for t in targets], dtype=float)

            model = GradientBoostingRegressor(
                n_estimators=100,
                max_depth=3,
                learning_rate=0.1,
                subsample=0.8,
                random_state=RANDOM_SEED,
            )
            model.fit(X_scaled, y)
            self._models[key] = model
            scores[key] = float(round(model.score(X_scaled, y), 4))

        self._is_trained = True
        self._save()

        log.info(
            "AdaptivePredictor trained on {} samples. R² scores: {}",
            len(features),
            scores,
        )
        return {"trained": True, "n": len(features), "r2_scores": scores}

    def predict(self, market_state: dict[str, Any]) -> dict[str, float]:
        """Predict optimal trading parameters for the current market state.

        Args:
            market_state: Current market metrics (volatility, trend, regime, etc.).

        Returns:
            Dict with predicted parameters and confidence.
        """
        if not self._is_trained or not self._models:
            return self._fallback_params()

        try:
            features = self._extract_features(market_state)
            X = self._build_feature_matrix([features])
            X_scaled = self._scaler.transform(X) if self._scaler else X

            predictions: dict[str, float] = {}
            for key, model in self._models.items():
                pred = float(model.predict(X_scaled)[0])
                predictions[key] = round(float(np.clip(pred, 0.5, 1.5)), 3)

            predictions["source"] = "ml"
            return predictions

        except Exception as exc:
            log.warning("AdaptivePredictor prediction failed: {}. Using fallback.", exc)
            return self._fallback_params()

    def add_sample(
        self,
        features: dict[str, float],
        outcome: dict[str, float],
    ) -> None:
        """Append a single sample to the training cache for future batch training."""
        cache_path = self.model_dir / "training_cache.jsonl"
        entry = {"features": features, "targets": outcome}
        with open(cache_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        log.debug("Sample added to training cache.")

    def batch_train_from_cache(self, min_samples: int = 10) -> dict[str, float]:
        """Train from cached samples collected over time.

        Args:
            min_samples: Minimum number of cached samples required.

        Returns:
            Training metrics or a dict with ``trained=False``.
        """
        cache_path = self.model_dir / "training_cache.jsonl"
        if not cache_path.exists():
            return {"trained": False, "reason": "no_cache"}

        features: list[dict[str, float]] = []
        targets: list[dict[str, float]] = []

        with open(cache_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    features.append(entry.get("features", {}))
                    targets.append(entry.get("targets", {}))
                except json.JSONDecodeError:
                    continue

        if len(features) < min_samples:
            return {
                "trained": False,
                "reason": "insufficient_cache",
                "cached": len(features),
                "required": min_samples,
            }

        result = self.train(features, targets)
        if result.get("trained"):
            # Archive cache after successful training
            archive_path = cache_path.with_suffix(".jsonl.old")
            cache_path.rename(archive_path)
            log.info("Training cache archived to {}", archive_path)

        return result

    def is_trained(self) -> bool:
        """Whether the model has been trained at least once."""
        return self._is_trained

    # ── Private helpers ───────────────────────────────────────────────

    def _extract_features(self, state: dict[str, Any]) -> dict[str, float]:
        """Convert a market state dict into a flat numeric feature dict."""
        return {
            "confidence": float(state.get("confidence", 0.0) or 0.0),
            "adx": float(state.get("adx", 20.0) or 20.0),
            "rsi": float(state.get("rsi", 50.0) or 50.0),
            "atr_pct": float(state.get("atr_pct", 1.0) or 1.0),
            "volatility": self._encode_volatility(state.get("volatility", "moderate")),
            "trend": self._encode_trend(state.get("trend", "neutral")),
            "regime": self._encode_regime(state.get("regime", "ranging")),
            "buy_votes": float(state.get("buy_votes", 0) or 0),
            "sell_votes": float(state.get("sell_votes", 0) or 0),
            "total_states": float(state.get("total_states", 1) or 1),
        }

    def _build_feature_matrix(self, features: list[dict[str, float]]) -> np.ndarray:
        return np.array(
            [[f.get(k, 0.0) for k in self._feature_names] for f in features]
            if self._feature_names
            else [list(f.values()) for f in features],
            dtype=float,
        )

    def _encode_volatility(self, v: str) -> float:
        return {"low": 0.0, "moderate": 0.5, "high": 1.0}.get(v.lower(), 0.5)

    def _encode_trend(self, t: str) -> float:
        return {"bearish": -1.0, "neutral": 0.0, "bullish": 1.0}.get(t.lower(), 0.0)

    def _encode_regime(self, r: str) -> float:
        return {"choppy": 0.0, "ranging": 0.5, "trending": 1.0}.get(r.lower(), 0.5)

    def _fallback_params(self) -> dict[str, float]:
        """Default parameters when model is not trained."""
        return {
            "position_size_multiplier": 1.0,
            "stop_loss_multiplier": 1.0,
            "take_profit_multiplier": 1.0,
            "confidence_threshold": 0.65,
            "source": "fallback",
        }

    def _save(self) -> None:
        """Persist models and scaler to disk."""
        if self._models:
            joblib.dump(self._models, self.model_path)
        if self._scaler:
            joblib.dump(self._scaler, self.scaler_path)
        meta = {
            "feature_names": self._feature_names,
            "model_keys": list(self._models.keys()),
        }
        with open(self.model_dir / "adaptive_meta.json", "w") as f:
            json.dump(meta, f)

    def _load_or_init(self) -> None:
        """Load pre-trained models from disk if available."""
        if self.model_path.exists() and self.scaler_path.exists():
            try:
                self._models = joblib.load(self.model_path)
                self._scaler = joblib.load(self.scaler_path)
                meta_path = self.model_dir / "adaptive_meta.json"
                if meta_path.exists():
                    with open(meta_path) as f:
                        meta = json.load(f)
                    self._feature_names = meta.get("feature_names", [])
                self._is_trained = True
                log.info("Loaded pre-trained AdaptivePredictor from disk.")
            except Exception as exc:
                log.warning("Could not load AdaptivePredictor: {}", exc)
