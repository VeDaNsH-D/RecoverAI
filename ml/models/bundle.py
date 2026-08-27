"""
Multi-Action Recovery Model container and factory for RecoverAI.
Manages the set of 5 action-conditional potential-outcome models.
"""

from pathlib import Path
from typing import Dict, List, Optional, Type, Union
import pickle
import numpy as np

from simulator.config import RecoveryAction
from ml.features import CANONICAL_FEATURE_NAMES
from ml.dataset import PotentialOutcomeDatasetBundle
from ml.models.base import BaseRecoveryModel
from ml.models.logistic_model import LogisticRecoveryModel
from ml.models.gbm_model import GBMRecoveryModel


# Deterministic action sequence
ACTION_ORDER: List[RecoveryAction] = [
    RecoveryAction.NO_ACTION,
    RecoveryAction.RETRY,
    RecoveryAction.PAYMENT_LINK,
    RecoveryAction.REMINDER,
    RecoveryAction.ESCALATE,
]


class MultiActionRecoveryModel:
    """
    Manages and coordinates the 5 action-specific recovery probability models.
    """

    def __init__(
        self,
        models: Dict[RecoveryAction, BaseRecoveryModel],
        feature_names: Optional[List[str]] = None,
    ):
        self.models = dict(models)
        self.feature_names = list(feature_names or CANONICAL_FEATURE_NAMES)
        self._validate_model_coverage()

    def _validate_model_coverage(self) -> None:
        for act in ACTION_ORDER:
            if act not in self.models:
                raise ValueError(f"Missing required action model for: '{act.value}'")

    @property
    def is_fitted(self) -> bool:
        """Returns True if all 5 action models have been fitted."""
        return all(m.is_fitted for m in self.models.values())

    def get_model(self, action: RecoveryAction) -> BaseRecoveryModel:
        """Returns the specific action model."""
        return self.models[action]

    def fit_all(self, dataset_bundle: PotentialOutcomeDatasetBundle) -> "MultiActionRecoveryModel":
        """
        Fits all 5 action models using the respective action datasets in the bundle.
        """
        for act in ACTION_ORDER:
            action_ds = dataset_bundle.get_dataset(act)
            self.models[act].fit(action_ds.X, action_ds.y)
        return self

    def predict_proba(self, X: np.ndarray, action: RecoveryAction) -> np.ndarray:
        """
        Predicts class probabilities (N, 2) for a specific action.
        """
        return self.models[action].predict_proba(X)

    def predict_positive_proba(self, X: np.ndarray, action: RecoveryAction) -> np.ndarray:
        """
        Predicts 1D positive recovery probabilities (N,) for a specific action.
        """
        return self.models[action].predict_positive_proba(X)

    def predict_all_positive_probas(self, X: np.ndarray) -> Dict[RecoveryAction, np.ndarray]:
        """
        Predicts recovery probabilities for all 5 actions simultaneously across N samples.
        """
        return {act: self.predict_positive_proba(X, act) for act in ACTION_ORDER}

    def save(self, file_path: Union[str, Path]) -> None:
        """Serializes the entire multi-action model bundle to disk."""
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f, protocol=pickle.HIGHEST_PROTOCOL)

    @classmethod
    def load(cls, file_path: Union[str, Path]) -> "MultiActionRecoveryModel":
        """Loads a MultiActionRecoveryModel from disk."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Model file not found at: {path}")
        with open(path, "rb") as f:
            obj = pickle.load(f)
        if not isinstance(obj, MultiActionRecoveryModel):
            raise TypeError(f"Loaded object is not a MultiActionRecoveryModel: {type(obj)}")
        return obj


def create_multi_action_model(
    model_type: str = "gbm",
    calibrate: bool = True,
    random_state: int = 42,
    feature_names: Optional[List[str]] = None,
) -> MultiActionRecoveryModel:
    """
    Factory function to construct a fresh MultiActionRecoveryModel.

    Parameters:
        model_type: 'logistic' or 'gbm'.
        calibrate: Whether to enable internal probability calibration.
        random_state: Random seed for reproducibility.
        feature_names: Optional custom feature names list.

    Returns:
        Configured MultiActionRecoveryModel ready for fitting.
    """
    feats = list(feature_names or CANONICAL_FEATURE_NAMES)
    models: Dict[RecoveryAction, BaseRecoveryModel] = {}

    for act in ACTION_ORDER:
        if model_type in ("logistic", "logistic_regression"):
            models[act] = LogisticRecoveryModel(
                action=act,
                feature_names=feats,
                calibrate=calibrate,
                random_state=random_state,
            )
        elif model_type in ("gbm", "hist_gradient_boosting", "gradient_boosting"):
            models[act] = GBMRecoveryModel(
                action=act,
                feature_names=feats,
                calibrate=calibrate,
                random_state=random_state,
            )
        else:
            raise ValueError(f"Unknown model_type '{model_type}'. Choose 'logistic' or 'gbm'.")

    return MultiActionRecoveryModel(models=models, feature_names=feats)
