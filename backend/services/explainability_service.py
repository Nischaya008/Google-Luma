"""
Model Explainability Service.
Uses SHAP (SHapley Additive exPlanations) to decode standard XGBoost predictions into human-readable constraints.
API-ready configuration for injecting reasoning streams directly into the Frontend routing payload.
"""
import logging
import shap
import numpy as np
import pandas as pd
from typing import Dict, List, Any
import matplotlib.pyplot as plt

# Handle matplotlib GUI bindings securely for server context executions
import matplotlib
matplotlib.use('Agg')

logger = logging.getLogger(__name__)

class SafetyExplainabilityService:
    """
    Decodes XGBoost logic arrays utilizing native high-speed TreeExplainer mathematics.
    Resolves exact feature contributions for frontend client pipeline consumption.
    """
    def __init__(self, model: Any):
        """
        Initializes the service architecture.
        
        Args:
            model: An initialized, trained XGBoost binary execution block.
        """
        self.model = model
        logger.info("Initializing SHAP TreeExplainer mathematics layout...")
        self.explainer = shap.TreeExplainer(self.model)
        
        # User-legible presentation mappings
        self.feature_vocabulary = {
            'lighting_score': 'lighting',
            'crime_density': 'crime',
            'footfall_proxy': 'crowd traffic',
            'poi_density': 'amenities footprint',
            'is_night': 'time of day',
            'length_m': 'exposure distance'
        }

    def _qualify_value(self, raw_value: float, feature_name: str) -> str:
        """
        Heuristic conditional resolver mapped to explicitly translate raw normalized tensors [0, 1] 
        into UI-optimized English qualifiers.
        """
        vocab = self.feature_vocabulary.get(feature_name, feature_name)
        if raw_value <= 0.33:
            return f"Low {vocab}"
        elif raw_value > 0.66:
            return f"High {vocab}"
        else:
            return f"Moderate {vocab}"
            
    def _format_impact(self, shap_val: float) -> str:
        """Safely formats floating point impact metrics."""
        if shap_val > 0:
            return f"+{shap_val:.3f}"
        return f"{shap_val:.3f}"

    def explain_prediction(self, feature_vector: pd.DataFrame) -> Dict[str, Any]:
        """
        API-Ready Engine Endpoint payload hook. 
        Calculates impact math logic sequentially and formulates a direct English layout matching exact specs.
        
        Args:
            feature_vector (pd.DataFrame): Vector targeting the geometry attributes mapping.
            
        Returns:
            Dict[str, Any]: Processed Frontend API representation blob.
        """
        if len(feature_vector) != 1:
            raise ValueError("Explainability API handles strictly isolated inference edges one at a time.")
            
        # Push through raw SHAP execution physics natively (High C++ performance block)
        shap_values = self.explainer(feature_vector)
        
        # Unpack SHAP logic arrays
        base_safety_score = float(shap_values.base_values[0])
        contributions = shap_values.values[0]
        actual_features = feature_vector.iloc[0]
        
        # Re-calc final score implicitly from base constraints logic
        final_score = base_safety_score + sum(contributions)
        is_safe = final_score > 0.50  # Center partition boundary calculation
        
        details = []
        positive_factors = []
        negative_factors = []
        
        for idx, col in enumerate(feature_vector.columns):
            c_val = float(contributions[idx])
            raw_val = float(actual_features[col])
            
            # Formatting presentation state dynamically
            desc = self._qualify_value(raw_val, col)
            impact_str = self._format_impact(c_val)
            
            # Persist payload explicitly for developer/ui components map
            details.append({
                "feature": col,
                "raw_value": raw_val,
                "contribution": c_val,
                "human_descriptor": desc
            })
            
            # Isolate massive movers to formulate English reasoning explanation constraints
            # We use an explicit threshold (e.g., impact > 0.05 or < -0.05) to only report major influence events
            if is_safe and c_val > 0.05:
                positive_factors.append(f" - {desc} ({impact_str})")
            elif not is_safe and c_val < -0.05:
                negative_factors.append(f" - {desc} ({impact_str})")
                
        # Generate target payload exact mapping:
        # "This road is unsafe because: \n - Low lighting (-0.3) \n - High crime (+0.5)"
        
        if len(negative_factors) > 0 and not is_safe:
            explanation_str = "This road is unsafe because:\n" + "\n".join(negative_factors)
            
        elif len(positive_factors) > 0 and is_safe:
             explanation_str = "This road feels safe because:\n" + "\n".join(positive_factors)
             
        else:
             # Universal fallback for highly neutral/baseline prediction conditions
             explanation_str = "This road represents an average ambient physical safety risk."
             
        # Package and return explicit API schema layout
        payload = {
            "prediction_score": round(final_score, 4),
            "base_shap_score": round(base_safety_score, 4),
            "is_safe": bool(is_safe),
            "human_readable_explanation": explanation_str,
            "feature_contributions": details
        }
        
        return payload
        
    def generate_summary_plot(self, X_sample: pd.DataFrame, save_path: str = "./data/models/shap_summary.png"):
        """
        Visualization extraction block compiling the scatter plot global distribution explicitly to image binaries.
        """
        logger.info(f"Targeting {len(X_sample)} points for global SHAP plot distribution.")
        shap_values = self.explainer(X_sample)
        
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            
            plt.figure(figsize=(10, 6))
            shap.summary_plot(shap_values, X_sample, show=False)
            plt.tight_layout()
            
            plt.savefig(save_path, dpi=300)
            plt.close()
            
        logger.info(f"SHAP Map Visual exported robustly onto: {save_path}")
