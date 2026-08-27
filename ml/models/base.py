"""
Abstract Base Recovery Model for RecoverAI.
Defines the standard interface for action-conditional potential-outcome recovery probability models.
SECURITY GUARANTEE: Ingests ONLY observable numerical feature matrices X and binary labels y.
Zero ground-truth objects, optimal actions, or latent states are consumed.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, Union
import pickle
import numpy as np

from simulator.config import RecoveryAction
from ml.features import CANONICAL_FEATURE_NAMES


class BaseRecoveryModel(ABC):
    """
    Abstract interface for action-conditional models: X -> P(Y(a)=1 | X).
    """

    def __init__(
        self,
        action: RecoveryAction,
        feature_names: Optional[List[str]] = None,
        calibrate: bool = True,
        random_state: int = 42,
    ):
        self.action = action
        self.feature_names = list(feature_names or CANONICAL_FEATURE_NAMES)
        self.calibrate = calibrate
        self.random_state = random_state
        self._is_fitted = False
        self._estimator = None

    @property
    @abstractmethod
    def model_type(self) -> str:
        """Returns the canonical model architecture name (e.g. 'logistic_regression', 'gbm')."""
        pass

    @property
    def is_fitted(self) -> bool:
        """Returns True if the model has been fitted on training data."""
        return self._is_fitted

    @property
    def is_calibrated(self) -> bool:
        """Returns True if probability calibration was enabled and applied."""
        return self.calibrate

    def _validate_inputs(self, X: np.ndarray, y: Optional[np.ndarray] = None) -> None:
        """
        Validates shapes and types for input feature matrix X and target y.
        """
        if not isinstance(X, np.ndarray):
            raise TypeError(f"X must be a numpy.ndarray, got {type(X)}")
        if X.ndim != 2:
            raise ValueError(f"X must be a 2D array of shape (N, D), got shape {X.shape}")
        if X.shape[1] != len(self.feature_names):
            raise ValueError(
                f"Feature dimension mismatch: expected {len(self.feature_names)} features, got {X.shape[1]}"
            )
        if np.isnan(X).any() or np.isinf(X).any():
            raise ValueError("X contains NaN or Inf values.")

        if y is not None:
            if not isinstance(y, np.ndarray):
                raise TypeError(f"y must be a numpy.ndarray, got {type(y)}")
            if y.ndim != 1:
                raise ValueError(f"y must be a 1D array of shape (N,), got shape {y.shape}")
            if X.shape[0] != y.shape[0]:
                raise ValueError(f"Sample count mismatch: X has {X.shape[0]} rows, y has {y.shape[0]} elements")
            
            unique_vals = set(np.unique(y))
            if not unique_vals.issubset({0, 1}):
                raise ValueError(f"Target y must be binary with values in {{0, 1}}, got unique: {unique_vals}")

    @abstractmethod
    def fit(self, X: np.ndarray, y: np.ndarray) -> "BaseRecoveryModel":
        """
        Fits the action-conditional recovery probability model on training data.
        Must not mutate the input X or y arrays.
        """
        pass

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """
        Predicts class probabilities for input features X.

        Parameters:
            X: 2D numpy array of shape (N, D).

        Returns:
            2D numpy array of shape (N, 2) where col 0 is P(Y=0) and col 1 is P(Y=1).
        """
        if not self._is_fitted or self._estimator is None:
            raise RuntimeError(f"Model for action '{self.action.value}' has not been fitted yet.")
        self._validate_inputs(X)

        # Make copy to ensure no external mutation
        X_eval = np.array(X, copy=True, dtype=np.float64)
        raw_probs = self._estimator.predict_proba(X_eval)

        # Handle edge case where training data had only 1 class
        if raw_probs.shape[1] == 1:
            # Check classes_ attribute
            classes = getattr(self._estimator, "classes_", np.array([0]))
            if classes[0] == 1:
                col1 = raw_probs[:, 0]
                col0 = 1.0 - col1
            else:
                col0 = raw_probs[:, 0]
                col1 = 1.0 - col0
            raw_probs = np.column_stack([col0, col1])

        # Clip strictly to [0.0, 1.0] and re-normalize
        raw_probs = np.clip(raw_probs, 0.0, 1.0)
        row_sums = raw_probs.sum(axis=1, keepdims=True)
        row_sums[row_sums == 0] = 1.0
        return raw_probs / row_sums

    def predict_positive_proba(self, X: np.ndarray) -> np.ndarray:
        """
        Convenience method: returns 1D array of recovery probability P(Y=1 | X).
        """
        probs = self.predict_proba(X)
        return probs[:, 1]

    def predict(self, X: np.ndarray, threshold: float = 0.5) -> np.ndarray:
        """
        Predicts binary recovery outcome Y in {0, 1} based on decision threshold.
        """
        pos_probs = self.predict_positive_proba(X)
        return (pos_probs >= threshold).astype(np.int64)

    def save(self, file_path: Union[str, Path]) -> None:
        """Serializes the fitted model to disk using pickle."""
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f, protocol=pickle.HIGHEST_PROTOCOL)

    @classmethod
    def load(cls, file_path: Union[str, Path]) -> "BaseRecoveryModel":
        """Deserializes a saved BaseRecoveryModel instance from disk."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Model file not found at: {path}")
        with open(path, "rb") as f:
            model = pickle.load(f)
        if not isinstance(model, BaseRecoveryModel):
            raise TypeError(f"Loaded object is not an instance of BaseRecoveryModel: {type(model)}")
        return model
