"""
ml/dataset_builder.py — Training dataset assembler (Day 69)
=============================================================

Assembles ML-ready training datasets from the FeatureStore + historical
market data. Handles:
  1. Loading features from the store
  2. Generating labels via LabelGenerator (if not already labeled)
  3. Chronological train/validation/test split (70/15/15)
  4. Returning clean DataFrames ready for model training

CRITICAL: All splits are chronological (no shuffle) to prevent future leakage.
The most recent 15% of data is ALWAYS the test set — never used in training.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from utils.logger import get_logger

log = get_logger("dataset_builder")


@dataclass
class Dataset:
    """A chronologically-split ML dataset."""
    X_train: pd.DataFrame
    X_val: pd.DataFrame
    X_test: pd.DataFrame
    y_train: pd.Series
    y_val: pd.Series
    y_test: pd.Series
    feature_names: List[str]
    pair: str
    timeframe: str
    train_size: int
    val_size: int
    test_size: int
    label_distribution: Dict[str, Any]

    def summary(self) -> Dict[str, Any]:
        return {
            "pair": self.pair,
            "timeframe": self.timeframe,
            "train_size": self.train_size,
            "val_size": self.val_size,
            "test_size": self.test_size,
            "n_features": len(self.feature_names),
            "label_distribution": self.label_distribution,
        }


class DatasetBuilder:
    """Builds chronologically-split training datasets."""

    def __init__(self, train_pct: float = 0.70, val_pct: float = 0.15):
        self.train_pct = train_pct
        self.val_pct = val_pct
        # test_pct = 1 - train_pct - val_pct = 0.15

    def build_from_store(
        self,
        pair: str,
        timeframe: str = "15m",
        min_samples: int = 100,
    ) -> Optional[Dataset]:
        """Load features + labels from the FeatureStore and split."""
        try:
            from ml.feature_store import get_feature_store
            store = get_feature_store()
            df = store.load_training_data(pair=pair, timeframe=timeframe, min_samples=min_samples)
        except Exception as e:
            log.error(f"[DatasetBuilder] FeatureStore load failed: {e}")
            return None

        if df.empty:
            log.warning(f"[DatasetBuilder] No data for {pair} {timeframe}")
            return None

        return self.build_from_dataframe(df, pair=pair, timeframe=timeframe)

    def build_from_dataframe(
        self,
        df: pd.DataFrame,
        pair: str = "EURUSD",
        timeframe: str = "15m",
    ) -> Optional[Dataset]:
        """Split a feature dataframe into train/val/test."""
        if "label" not in df.columns:
            log.error("[DatasetBuilder] no 'label' column in dataframe")
            return None

        # Drop meta columns + rows without labels
        meta_cols = [c for c in df.columns if c.startswith("_") or c in
                     ("outcome", "pnl_usd", "forward_pips", "label_ternary",
                      "label_forward_return", "label_forward_pips",
                      "label_mae_pips", "label_mfe_pips", "label_r_multiple")]
        feature_df = df.drop(columns=meta_cols, errors="ignore").copy()
        feature_df = feature_df.replace([np.inf, -np.inf], np.nan).dropna()

        labels = df.loc[feature_df.index, "label"].copy()
        # Ensure binary labels
        labels = labels.astype(int)

        if len(feature_df) < 50:
            log.warning(f"[DatasetBuilder] only {len(feature_df)} samples — need ≥50")
            return None

        n = len(feature_df)
        train_end = int(n * self.train_pct)
        val_end = int(n * (self.train_pct + self.val_pct))

        X_train = feature_df.iloc[:train_end]
        X_val = feature_df.iloc[train_end:val_end]
        X_test = feature_df.iloc[val_end:]
        y_train = labels.iloc[:train_end]
        y_val = labels.iloc[train_end:val_end]
        y_test = labels.iloc[val_end:]

        # Label distribution
        def _dist(y):
            vc = y.value_counts().to_dict()
            return {str(int(k)): int(v) for k, v in vc.items()}

        label_dist = {
            "train": _dist(y_train),
            "val": _dist(y_val),
            "test": _dist(y_test),
        }

        log.info(
            f"[DatasetBuilder] {pair} {timeframe}: "
            f"train={len(X_train)}, val={len(X_val)}, test={len(X_test)}, "
            f"features={len(feature_df.columns)}"
        )

        return Dataset(
            X_train=X_train, X_val=X_val, X_test=X_test,
            y_train=y_train, y_val=y_val, y_test=y_test,
            feature_names=list(feature_df.columns),
            pair=pair, timeframe=timeframe,
            train_size=len(X_train), val_size=len(X_val), test_size=len(X_test),
            label_distribution=label_dist,
        )


# ── Singleton ───────────────────────────────────────────────────────

_BUILDER: Optional[DatasetBuilder] = None


def get_dataset_builder() -> DatasetBuilder:
    global _BUILDER
    if _BUILDER is None:
        _BUILDER = DatasetBuilder()
    return _BUILDER
