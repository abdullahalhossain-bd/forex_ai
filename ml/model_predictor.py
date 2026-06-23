"""
ml/model_predictor.py — Live ensemble prediction (Day 69)
===========================================================

Loads all trained models for a pair and produces a single ensemble
prediction with:
  - Per-model probability
  - Model agreement score (e.g. "3/3 models agree")
  - Ensemble probability (average of all model probabilities)
  - Final prediction (BUY if ensemble > threshold, SELL if < 1-threshold, WAIT otherwise)
  - Top important features (from the best model)

If no models are trained yet, returns a "not ready" prediction — the
agent falls back to rule-based logic.

Usage:
    predictor = get_model_predictor()
    pred = predictor.predict(features_dict, pair="EURUSD", timeframe="15m")
    # pred = {"prediction": "BUY", "probability": 0.78, "agreement": "2/3", ...}
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from utils.logger import get_logger

from ml.model_store import get_model_store
from ml.data_preprocessor import get_preprocessor

log = get_logger("model_predictor")

PREDICTIONS_DB = Path("memory/ml_predictions.db")

# Threshold for BUY/SELL decision
BUY_THRESHOLD = 0.58
SELL_THRESHOLD = 0.42


class ModelPredictor:
    """Live ensemble predictor combining XGBoost + RF + LSTM."""

    def __init__(self):
        self.store = get_model_store()
        self.preprocessor = get_preprocessor()
        self._lock = threading.RLock()
        self._model_cache: Dict[str, Any] = {}  # pair_tf_modeltype → model
        self._scaler_loaded = False
        self._init_predictions_db()

    def _init_predictions_db(self) -> None:
        PREDICTIONS_DB.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(PREDICTIONS_DB)) as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS ml_predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pair TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prediction TEXT,
                    probability REAL,
                    actual_result TEXT,
                    timestamp TEXT NOT NULL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS ml_ensemble (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pair TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    ensemble_prediction TEXT,
                    ensemble_probability REAL,
                    model_agreement TEXT,
                    per_model TEXT,
                    timestamp TEXT NOT NULL
                )
            """)
            c.commit()

    def _load_models(self, pair: str, timeframe: str) -> Dict[str, Any]:
        """Load all available models for a pair (cached)."""
        cache_key_prefix = f"{pair.upper()}_{timeframe}_"
        models: Dict[str, Any] = {}
        for model_type in ("xgboost", "random_forest", "lstm"):
            cache_key = cache_key_prefix + model_type
            if cache_key in self._model_cache:
                models[model_type] = self._model_cache[cache_key]
                continue
            model = self.store.load_model(pair, timeframe, model_type)
            if model is not None:
                self._model_cache[cache_key] = model
                models[model_type] = model
        return models

    def _load_scaler(self, pair: str, timeframe: str) -> bool:
        """Try to load the scaler saved during training."""
        if self._scaler_loaded:
            return True
        scaler_path = Path("memory/ml_processed/scaler.pkl")
        if scaler_path.exists():
            try:
                self.preprocessor.load_scaler(scaler_path)
                self._scaler_loaded = True
                return True
            except Exception:
                pass
        return False

    def predict(
        self,
        features: Dict[str, float],
        pair: str,
        timeframe: str = "15m",
    ) -> Dict[str, Any]:
        """Run ensemble prediction on a single feature vector.

        Returns:
            {
                "prediction": "BUY" | "SELL" | "WAIT" | "NOT_READY",
                "probability": float,           # ensemble BUY probability
                "model_agreement": str,          # e.g. "3/3"
                "per_model": {                   # per-model breakdown
                    "xgboost": {"prediction": "BUY", "probability": 0.78},
                    "random_forest": {...},
                    "lstm": {...},
                },
                "important_features": [...],     # top features (if available)
                "models_used": int,
                "timestamp": str,
            }
        """
        pair = pair.upper()
        result: Dict[str, Any] = {
            "prediction": "NOT_READY",
            "probability": 0.5,
            "model_agreement": "0/0",
            "per_model": {},
            "important_features": [],
            "models_used": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

        # Load models
        models = self._load_models(pair, timeframe)
        if not models:
            log.debug(f"[Predictor] no models for {pair} {timeframe} — NOT_READY")
            return result

        result["models_used"] = len(models)

        # Load scaler
        self._load_scaler(pair, timeframe)

        # Build feature vector in the right order
        # We need to match the feature names from training. Since we don't have
        # the exact list here, we pass the dict as a single-row DataFrame and
        # let the model handle it (tree-based models are order-independent by name).
        try:
            X = pd.DataFrame([features])
        except Exception as e:
            log.warning(f"[Predictor] feature vector build failed: {e}")
            return result

        # Transform with scaler (if loaded)
        try:
            if self._scaler_loaded:
                X = self.preprocessor.transform(X)
        except Exception:
            pass  # scaler may not have all columns — use raw

        buy_count = 0
        sell_count = 0
        probabilities: List[float] = []

        for model_type, model in models.items():
            model_result: Dict[str, Any] = {"prediction": "WAIT", "probability": 0.5}
            try:
                if model_type == "lstm":
                    # LSTM needs 3D input
                    n_features = X.shape[1]
                    X_3d = X.values.reshape(1, 1, n_features)
                    proba = float(model.predict(X_3d, verbose=0).ravel()[0])
                else:
                    proba_arr = model.predict_proba(X)
                    proba = float(proba_arr[0][1]) if proba_arr.shape[1] > 1 else float(proba_arr[0][0])

                model_result["probability"] = round(proba, 4)
                if proba >= BUY_THRESHOLD:
                    model_result["prediction"] = "BUY"
                    buy_count += 1
                elif proba <= SELL_THRESHOLD:
                    model_result["prediction"] = "SELL"
                    sell_count += 1
                probabilities.append(proba)

                # Record individual prediction
                self._record_prediction(pair, timeframe, model_type, model_result["prediction"], proba)

            except Exception as e:
                log.debug(f"[Predictor] {model_type} predict failed: {e}")
                model_result = {"prediction": "WAIT", "probability": 0.5, "error": str(e)[:100]}

            result["per_model"][model_type] = model_result

        # Ensemble: average probability
        if probabilities:
            ensemble_proba = float(np.mean(probabilities))
            result["probability"] = round(ensemble_proba, 4)

            # Agreement
            total_models = len(probabilities)
            if buy_count > sell_count and buy_count > 0:
                result["prediction"] = "BUY"
                result["model_agreement"] = f"{buy_count}/{total_models}"
            elif sell_count > buy_count and sell_count > 0:
                result["prediction"] = "SELL"
                result["model_agreement"] = f"{sell_count}/{total_models}"
            else:
                result["prediction"] = "WAIT"
                result["model_agreement"] = f"{max(buy_count, sell_count)}/{total_models}"

        # Important features (from xgboost if available)
        try:
            if "xgboost" in models:
                importances = models["xgboost"].feature_importances_
                feat_names = list(X.columns)
                top_idx = np.argsort(importances)[::-1][:5]
                result["important_features"] = [
                    {"feature": feat_names[i], "importance": round(float(importances[i]), 4)}
                    for i in top_idx if i < len(feat_names)
                ]
        except Exception:
            pass

        # Record ensemble prediction
        self._record_ensemble(pair, timeframe, result)

        return result

    def _record_prediction(self, pair, tf, model, prediction, probability):
        try:
            with sqlite3.connect(str(PREDICTIONS_DB)) as c:
                c.execute(
                    "INSERT INTO ml_predictions (pair, timeframe, model, prediction, probability, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                    (pair, tf, model, prediction, float(probability),
                     datetime.now(timezone.utc).isoformat(timespec="seconds")),
                )
                c.commit()
        except Exception:
            pass

    def _record_ensemble(self, pair, tf, result):
        try:
            with sqlite3.connect(str(PREDICTIONS_DB)) as c:
                c.execute(
                    "INSERT INTO ml_ensemble (pair, timeframe, ensemble_prediction, ensemble_probability, model_agreement, per_model, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (pair, tf, result["prediction"], result["probability"],
                     result["model_agreement"], json.dumps(result["per_model"], default=str),
                     result["timestamp"]),
                )
                c.commit()
        except Exception:
            pass

    def update_actual_result(self, pair: str, timeframe: str, prediction_id: int, actual: str):
        """Update the actual result after the trade closes (for accuracy tracking)."""
        try:
            with sqlite3.connect(str(PREDICTIONS_DB)) as c:
                c.execute(
                    "UPDATE ml_predictions SET actual_result = ? WHERE id = ?",
                    (actual, prediction_id),
                )
                c.commit()
        except Exception:
            pass

    def prediction_stats(self, pair: Optional[str] = None) -> Dict[str, Any]:
        """Return prediction accuracy stats."""
        try:
            with sqlite3.connect(str(PREDICTIONS_DB)) as c:
                if pair:
                    rows = c.execute(
                        "SELECT model, COUNT(*), SUM(CASE WHEN prediction = actual_result THEN 1 ELSE 0 END) FROM ml_predictions WHERE pair = ? AND actual_result IS NOT NULL GROUP BY model",
                        (pair.upper(),),
                    ).fetchall()
                else:
                    rows = c.execute(
                        "SELECT model, COUNT(*), SUM(CASE WHEN prediction = actual_result THEN 1 ELSE 0 END) FROM ml_predictions WHERE actual_result IS NOT NULL GROUP BY model",
                    ).fetchall()
            stats = {}
            for model, total, correct in rows:
                stats[model] = {
                    "total": total,
                    "correct": correct,
                    "accuracy_pct": round((correct / total * 100) if total else 0, 1),
                }
            return stats
        except Exception as e:
            return {"error": str(e)}


# ── Singleton ───────────────────────────────────────────────────────

_PREDICTOR: Optional[ModelPredictor] = None


def get_model_predictor() -> ModelPredictor:
    global _PREDICTOR
    if _PREDICTOR is None:
        _PREDICTOR = ModelPredictor()
    return _PREDICTOR
