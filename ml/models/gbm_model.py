"""
Gradient Boosted Recovery Probability Model for RecoverAI.
Uses HistGradientBoostingClassifier to model non-linear failure dynamics and interactions.
"""

from typing import List, Optional
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.calibration import CalibratedClassifierCV

from simulator.config import RecoveryAction
from ml.models.base import BaseRecoveryModel


class GBMRecoveryModel(BaseRecoveryModel):
    """
    Action-conditional recovery model using HistGradientBoostingClassifier.
    Captures non-linear failure interactions, amount thresholds, and retry-fatigue curves.
    """

    def __init__(
        self,
        action: RecoveryAction,
        feature_names: Optional[List[str]] = None,
        learning_rate: float = 0.08,
        max_iter: int = 100,
        max_leaf_nodes: int = 31,
        min_samples_leaf: int = 20,
        l2_regularization: float = 1.0,
        calibrate: bool = True,
        calibration_cv: int = 5,
        random_state: int = 42,
    ):
        super().__init__(
            action=action,
            feature_names=feature_names,
            calibrate=calibrate,
            random_state=random_state,
        )
        self.learning_rate = learning_rate
        self.max_iter = max_iter
        self.max_leaf_nodes = max_leaf_nodes
        self.min_samples_leaf = min_samples_leaf
        self.l2_regularization = l2_regularization
        self.calibration_cv = calibration_cv

    @property
    def model_type(self) -> str:
        return "hist_gradient_boosting"

    def fit(self, X: np.ndarray, y: np.ndarray) -> "GBMRecoveryModel":
        """
        Fits the gradient boosting model on training features X and binary target y.
        """
        self._validate_inputs(X, y)

        X_train = np.array(X, copy=True, dtype=np.float64)
        y_train = np.array(y, copy=True, dtype=np.int64)

        base_clf = HistGradientBoostingClassifier(
            learning_rate=self.learning_rate,
            max_iter=self.max_iter,
            max_leaf_nodes=self.max_leaf_nodes,
            min_samples_leaf=self.min_samples_leaf,
            l2_regularization=self.l2_regularization,
            random_state=self.random_state,
        )

        unique_classes = np.unique(y_train)
        if len(unique_classes) < 2:
            base_clf.fit(X_train, y_train)
            self._estimator = base_clf
            self._is_fitted = True
            return self

        # Dynamically determine feasible CV folds for calibration
        min_class_count = int(min(np.sum(y_train == 0), np.sum(y_train == 1)))
        effective_cv = min(self.calibration_cv, min_class_count)

        if self.calibrate and effective_cv >= 2:
            calibrated_clf = CalibratedClassifierCV(
                estimator=base_clf,
                method="sigmoid",
                cv=effective_cv,
            )
            calibrated_clf.fit(X_train, y_train)
            self._estimator = calibrated_clf
        else:
            base_clf.fit(X_train, y_train)
            self._estimator = base_clf

        self._is_fitted = True
        return self
