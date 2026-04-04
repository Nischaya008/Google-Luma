"""
Safety Prediction Service.

Trains and runs an XGBoost regressor to predict per-edge safety scores.
Uses heuristic labels derived from real feature data for initial training,
then persists the model for fast subsequent startups.

The model operates on 8 real features:
- lighting_score (VIIRS satellite or road-type estimation)
- crime_density (KDE on real incidents)
- poi_density (OSM Overpass API)
- footfall_proxy (derived from POI + road type + time)
- weather_risk (OpenWeatherMap real-time)
- vegetation_isolation (GEE NDVI, optional)
- is_night (Astral astronomical)
- length_m (OSM road segment length, log-normalized to [0,1])

IMPORTANT: All features are expected to be pre-normalized to [0,1] by
the feature engineering pipeline. NO additional normalization is applied
here — this avoids the distribution mismatch between training labels
and inference that previously caused uniform safety scores.
"""
import os
import sys
import pickle
import logging
import pandas as pd
import numpy as np
import networkx as nx
from typing import Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import settings

logger = logging.getLogger(__name__)

# All features used by the XGBoost model — order matters for consistency
ML_FEATURE_COLS = [
    "lighting_score",
    "crime_density",
    "footfall_proxy",
    "poi_density",
    "weather_risk",
    "vegetation_isolation",
    "is_night",
    "length_m",
]


class SafetyScoringModel:
    """
    Manages the XGBoost safety scoring lifecycle:
    1. Load a pre-trained model from disk if available (fast startup)
    2. Otherwise, train dynamically on the current graph's real features
    3. Persist the trained model for subsequent restarts
    """

    def __init__(self, model_path: Optional[str] = None):
        self.target_path = model_path if model_path else settings.MODEL_PATH
        self.model = None
        self._load_model(self.target_path)

    def _load_model(self, path: str) -> None:
        """Attempt to load a pre-trained model from disk."""
        try:
            expanded = os.path.abspath(path)
            if not os.path.exists(expanded):
                logger.info(f"No pre-trained model at {expanded}. Will train on first request.")
                return

            logger.info(f"Loading pre-trained XGBoost model from {expanded}")
            with open(expanded, "rb") as f:
                self.model = pickle.load(f)
            logger.info("XGBoost model loaded successfully.")
        except Exception as e:
            logger.warning(f"Failed to load model ({e}). Will train dynamically.")

    # ── Heuristic Label Generation ──────────────────────────────────────────

    def _generate_heuristic_labels(self, X: pd.DataFrame) -> pd.Series:
        """
        Generate deterministic safety labels from real features using
        domain-expert heuristic weights. Fully vectorized with NumPy.

        IMPORTANT: No normalization is applied here. All features are
        expected to already be in [0,1] from the feature engineering pipeline.
        This ensures the XGBoost model learns a consistent mapping that
        works identically at inference time.

        Weight profiles differ between day and night to reflect real-world
        safety dynamics:
        - Night: lighting and crime become dominant factors
        - Day: footfall and POI proximity are more important
        """
        # Extract feature arrays — all already in [0,1]
        light = X["lighting_score"].values if "lighting_score" in X.columns else np.full(len(X), 0.5)
        crime_safe = 1.0 - (X["crime_density"].values if "crime_density" in X.columns else np.zeros(len(X)))
        footfall = X["footfall_proxy"].values if "footfall_proxy" in X.columns else np.zeros(len(X))
        poi = X["poi_density"].values if "poi_density" in X.columns else np.zeros(len(X))
        weather = X["weather_risk"].values if "weather_risk" in X.columns else np.zeros(len(X))
        veg_iso = X["vegetation_isolation"].values if "vegetation_isolation" in X.columns else np.zeros(len(X))
        is_night = (X["is_night"].values if "is_night" in X.columns else np.zeros(len(X))).astype(int)

        # Day scores: balanced across all factors
        day_score = (
            0.20 * light
            + 0.20 * crime_safe
            + 0.25 * footfall
            + 0.15 * poi
            - 0.10 * weather
            - 0.10 * veg_iso
        )

        # Night scores: lighting and crime dominate
        night_score = (
            0.35 * light
            + 0.30 * crime_safe
            + 0.10 * footfall
            + 0.05 * poi
            - 0.10 * weather
            - 0.10 * veg_iso
        )

        # Vectorized selection based on time-of-day (no Python loop)
        y = np.where(is_night == 1, night_score, day_score)
        y = np.clip(y, 0.0, 1.0)

        return pd.Series(y, index=X.index)

    # ── Dynamic Training ────────────────────────────────────────────────────

    def train_dynamic_model(self, edge_features: pd.DataFrame) -> None:
        """
        Train XGBoost on real features with heuristic labels.
        Persists the trained model to disk for fast subsequent starts.
        """
        from xgboost import XGBRegressor

        logger.info("Training XGBoost on real graph features...")

        # Ensure all required columns exist (fill missing optional ones with 0)
        for col in ML_FEATURE_COLS:
            if col not in edge_features.columns:
                edge_features[col] = 0.0

        y_train = self._generate_heuristic_labels(edge_features)
        X_train = edge_features[ML_FEATURE_COLS].copy()

        self.model = XGBRegressor(
            n_estimators=150,
            max_depth=6,
            learning_rate=0.1,
            random_state=42,
            n_jobs=-1,
            subsample=0.8,
            colsample_bytree=0.8,
        )
        self.model.fit(X_train, y_train)

        # Log feature importance
        importances = dict(zip(ML_FEATURE_COLS, self.model.feature_importances_))
        sorted_imp = sorted(importances.items(), key=lambda x: x[1], reverse=True)
        logger.info("── Feature Importance ──")
        for feat, imp in sorted_imp:
            logger.info(f"  {feat:>25s} : {imp * 100:5.1f}%")

        # Persist to disk
        expanded = os.path.abspath(self.target_path)
        os.makedirs(os.path.dirname(expanded), exist_ok=True)
        try:
            with open(expanded, "wb") as f:
                pickle.dump(self.model, f)
            logger.info(f"Model saved to {expanded}")
        except Exception as e:
            logger.error(f"Failed to save model: {e}")

    # ── Inference ───────────────────────────────────────────────────────────

    def predict_edge_safety(self, edge_features: pd.DataFrame) -> np.ndarray:
        """
        Predict safety scores for all edges using the trained XGBoost model.

        NO normalization is applied — features arrive pre-normalized from
        the feature engineering pipeline, matching training conditions exactly.
        """
        if self.model is None:
            raise ValueError("Model not initialized. Call train_dynamic_model first.")

        X = edge_features.copy()

        # Ensure all required columns exist
        for col in ML_FEATURE_COLS:
            if col not in X.columns:
                X[col] = 0.0

        predictions = self.model.predict(X[ML_FEATURE_COLS])
        return np.clip(predictions, 0.0, 1.0)

    # ── Graph Annotation ────────────────────────────────────────────────────

    def annotate_graph_with_safety(
        self, G: nx.MultiDiGraph, features_df: pd.DataFrame
    ) -> nx.MultiDiGraph:
        """
        Predict safety scores and write them (plus all raw features)
        as edge attributes into the NetworkX graph.
        """
        logger.info(f"Annotating {len(features_df)} edges with safety scores...")

        # Train if no model exists
        if self.model is None:
            self.train_dynamic_model(features_df)

        predicted_scores = self.predict_edge_safety(features_df)

        # Write scores + raw features into graph edges
        edge_indices = features_df.index
        feature_dicts = features_df.to_dict("records")

        safety_attrs = {}
        for edge_tuple, score, row in zip(edge_indices, predicted_scores, feature_dicts):
            safety_attrs[edge_tuple] = {
                "safety_score": float(score),
                "is_night": int(row.get("is_night", 0)),
                "poi_density": float(row.get("poi_density", 0.0)),
                "footfall_proxy": float(row.get("footfall_proxy", 0.0)),
                "lighting_score": float(row.get("lighting_score", 0.0)),
                "weather_risk": float(row.get("weather_risk", 0.0)),
                "vegetation_isolation": float(row.get("vegetation_isolation", 0.0)),
            }

        nx.set_edge_attributes(G, safety_attrs)

        # Log score distribution
        scores = predicted_scores
        logger.info(
            f"Safety scores: min={scores.min():.3f}, max={scores.max():.3f}, "
            f"mean={scores.mean():.3f}, std={scores.std():.3f}"
        )

        return G
