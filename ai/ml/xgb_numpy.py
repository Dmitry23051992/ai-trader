"""
XGBoost → Pure NumPy Inference Engine v2.

Конвертирует XGBoost v2 модель (JSON с массивами) в numpy массивы деревьев
и выполняет инференс без зависимости от xgboost.

Формат XGBoost v2:
  - Деревья хранятся как массивы: left_children, right_children, split_indices,
    split_conditions, base_weights
  - tree_info указывает класс для каждого дерева (0, 1, 2 для multi:softprob)
  - iteration_indptr группирует деревья по итерациям
  - base_score — вектор базовых оценок для каждого класса

Идеально для Raspberry Pi где xgboost не устанавливается.

Usage:
    from ai.ml.xgb_numpy import XGBoostNumpy
    
    model = XGBoostNumpy("models/candle_xgboost_v1.json")
    probs = model.predict_proba(features_2d_array)
"""

import json
import numpy as np
from pathlib import Path
from typing import Optional


def softmax(x: np.ndarray) -> np.ndarray:
    """Numerically stable softmax."""
    x_max = np.max(x)
    exps = np.exp(x - x_max)
    return exps / np.sum(exps)


class XGBoostNumpy:
    """
    Pure NumPy XGBoost inference engine v2.
    
    Загружает модель из XGBoost v2 JSON формата (с массивами)
    и выполняет инференс без установки xgboost.
    """
    
    def __init__(self, model_path: str):
        self.model_path = Path(model_path)
        self.trees_by_class: list[list[dict]] = []
        self.num_classes = 0
        self.num_trees_per_class = 0
        self.num_features = 0
        self.base_scores: list[float] = []
        self.feature_names: list[str] = []
        self.class_names: list[str] = []
        self._loaded = False
        
        self._load()
    
    def _load(self):
        """Load model from XGBoost v2 JSON."""
        if not self.model_path.exists():
            print(f"[XGBoostNumpy] Model not found: {self.model_path}")
            return
        
        try:
            with open(self.model_path) as f:
                model_json = json.load(f)
        except json.JSONDecodeError:
            print(f"[XGBoostNumpy] Invalid JSON in {self.model_path}")
            return
        
        # Load meta
        meta_path = self.model_path.with_suffix(".meta.json")
        if meta_path.exists():
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                self.feature_names = meta.get("feature_names", [])
                self.class_names = meta.get("class_names", ["hold", "buy", "sell"])
            except Exception:
                pass
        
        try:
            learner = model_json.get("learner", {})
            
            # Feature names
            self.feature_names = learner.get("feature_names", self.feature_names)
            
            # Base scores for multi-class
            learner_params = learner.get("learner_model_param", {})
            base_score_str = learner_params.get("base_score", "0.0")
            base_score_str = base_score_str.strip("[]")
            self.base_scores = [float(x) for x in base_score_str.split(",")]
            self.num_classes = int(learner_params.get("num_class", len(self.base_scores)))
            
            # Trees
            gb = learner.get("gradient_booster", {})
            model_data = gb.get("model", {})
            trees_raw = model_data.get("trees", [])
            tree_info = model_data.get("tree_info", [])
            
            # Get num_features from tree_param
            if trees_raw:
                tree_param = trees_raw[0].get("tree_param", {})
                self.num_features = int(tree_param.get("num_feature", len(self.feature_names)))
            else:
                self.num_features = len(self.feature_names)
            
            if not trees_raw:
                print(f"[XGBoostNumpy] No trees found")
                return
            
            # Group trees by class using tree_info
            self.trees_by_class = [[] for _ in range(self.num_classes)]
            for i, tree in enumerate(trees_raw):
                class_idx = tree_info[i] if i < len(tree_info) else (i % self.num_classes)
                if class_idx < self.num_classes:
                    self.trees_by_class[class_idx].append(tree)
            
            self.num_trees_per_class = len(self.trees_by_class[0]) if self.trees_by_class else 0
            
            self._loaded = True
            total_trees = sum(len(g) for g in self.trees_by_class)
            print(f"[XGBoostNumpy] Loaded {total_trees} trees "
                  f"({self.num_classes} classes x {self.num_trees_per_class} trees)")
            
        except Exception as e:
            print(f"[XGBoostNumpy] Parse error: {e}")
            import traceback
            traceback.print_exc()
    
    @property
    def available(self) -> bool:
        return self._loaded
    
    def _predict_tree(self, tree: dict, features: np.ndarray) -> float:
        """
        Predict a single tree for a single sample.
        
        Tree format:
          left_children: array of node indices for left child (-1 = leaf)
          right_children: array of node indices for right child
          split_indices: feature index to split on
          split_conditions: threshold for split (or leaf value if leaf)
          default_left: array of bools
        """
        left = tree["left_children"]
        right = tree["right_children"]
        split_idx = tree["split_indices"]
        conditions = tree["split_conditions"]
        
        node = 0
        while left[node] != -1:  # -1 means leaf
            feat_val = features[split_idx[node]]
            if feat_val <= conditions[node]:
                node = left[node]
            else:
                node = right[node]
        
        # Leaf node value is in conditions[node]
        return float(conditions[node])
    
    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        """
        Predict class probabilities.
        
        Args:
            features: np.ndarray of shape (n_samples, n_features)
            
        Returns:
            np.ndarray of shape (n_samples, n_classes) with probabilities
        """
        if not self._loaded:
            return np.full((len(features), 3), 1.0 / 3)
        
        if features.ndim == 1:
            features = features.reshape(1, -1)
        
        n_samples = len(features)
        
        # Sum tree outputs for each class
        raw_scores = np.zeros((n_samples, self.num_classes))
        
        for c in range(self.num_classes):
            if c < len(self.trees_by_class):
                for tree in self.trees_by_class[c]:
                    for i in range(n_samples):
                        raw_scores[i, c] += self._predict_tree(tree, features[i])
        
        # Add base scores
        for c in range(self.num_classes):
            if c < len(self.base_scores):
                raw_scores[:, c] += self.base_scores[c]
        
        # Apply softmax for multi-class
        probs = np.zeros((n_samples, self.num_classes))
        for i in range(n_samples):
            probs[i] = softmax(raw_scores[i])
        
        return probs
    
    def predict(self, features: np.ndarray) -> np.ndarray:
        """Predict class labels."""
        probs = self.predict_proba(features)
        return np.argmax(probs, axis=1)


def convert_xgb_to_numpy(xgb_model_path: str) -> Optional[XGBoostNumpy]:
    """Convert XGBoost model to numpy format and test it."""
    model = XGBoostNumpy(xgb_model_path)
    if not model.available:
        print(f"Failed to load model from {xgb_model_path}")
        return None
    
    print(f"Model loaded: {model.num_classes} classes, "
          f"{model.num_trees_per_class} trees per class")
    
    return model


if __name__ == "__main__":
    import sys
    model_path = sys.argv[1] if len(sys.argv) > 1 else \
        str(Path(__file__).parent / "models" / "candle_xgboost_v1.json")
    
    model = convert_xgb_to_numpy(model_path)
    if model:
        test_features = np.random.randn(5, model.num_features).astype(np.float32)
        probs = model.predict_proba(test_features)
        print(f"\nTest predictions (5 random samples):")
        for i, p in enumerate(probs):
            pred = ["hold", "buy", "sell"][np.argmax(p)]
            print(f"  Sample {i}: {pred} (hold={p[0]:.3f} buy={p[1]:.3f} sell={p[2]:.3f})")
