"""
Logistic Regression Recovery Probability Model for RecoverAI.
Serves as the transparent, regularized linear baseline for action-conditional recovery estimation.
"""

from typing import List, Optional
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.calibration import CalibratedClassifierCV

from simulator.config import RecoveryAction
from ml.models.base import BaseRecoveryModel


class LogisticRecoveryModel(BaseRecoveryModel):
    """
    Action-conditional recovery model using regularized Logistic Regression.
    Includes feature standardization and internal cross-validated probability calibration.
    """

    def __init__(
        self,
        action: RecoveryAction,
        feature_names: Optional[List[str]] = None,
        C: float = 1.0,
        max_iter: int = 1000,
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
        self.C = C
        self.max_iter = max_iter
        self.calibration_cv = calibration_cv

    @property
    def model_type(self) -> str:
        return "logistic_regression"

    def fit(self, X: np.ndarray, y: np.ndarray) -> "LogisticRecoveryModel":
        """
        Fits the logistic regression pipeline on training features X and binary target y.
        """
        self._validate_inputs(X, y)
        
        # Clone arrays to ensure zero mutation of caller inputs
        X_train = np.array(X, copy=True, dtype=np.float64)
        y_train = np.array(y, copy=True, dtype=np.int64)

        base_pipe = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(
                C=self.C,
                max_iter=self.max_iter,
                random_state=self.random_state,
                solver="lbfgs",
            )),
        ])

        # Check class distribution
        unique_classes = np.unique(y_train)
        if len(unique_classes) < 2:
            base_pipe.fit(X_train, y_train)
            self._estimator = base_pipe
            self._is_fitted = True
            return self

        # Dynamically determine feasible CV folds for calibration
        min_class_count = int(min(np.sum(y_train == 0), np.sum(y_train == 1)))
        effective_cv = min(self.calibration_cv, min_class_count)

        if self.calibrate and effective_cv >= 2:
            # Calibrate using internal K-fold CV on training data only
            calibrated_clf = CalibratedClassifierCV(
                estimator=base_pipe,
                method="sigmoid",
                cv=effective_cv,
            )
            calibrated_clf.fit(X_train, y_train)
            self._estimator = calibrated_clf
        else:
            base_pipe.fit(X_train, y_train)
            self._estimator = base_pipe

        self._is_fitted = True
        return self
