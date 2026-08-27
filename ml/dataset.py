"""
Dataset construction for action-conditional potential-outcome ML models.
Constructs clean supervised datasets D_a = (X, y_a) for each candidate action a in A.
SECURITY GUARANTEE: Feature matrix X contains strictly observable PaymentCase features.
Potential outcome Y(a) is used strictly as the supervised target label y, NEVER as a feature.
"""

from pathlib import Path
from typing import Dict, List, Optional
import json
import numpy as np
from pydantic import BaseModel, ConfigDict

from simulator.config import RecoveryAction
from simulator.schemas.case import PaymentCase
from simulator.schemas.ground_truth import CaseGroundTruth
from ml.features import FeatureExtractor, DataLeakageError


class ActionDataset:
    """
    Supervised dataset for a single candidate recovery action a in A.
    Represents the mapping X -> y_a where y_a = Y(a) in {0, 1}.
    """

    def __init__(
        self,
        action: RecoveryAction,
        X: np.ndarray,
        y: np.ndarray,
        case_ids: List[str],
        feature_names: List[str],
    ):
        if X.shape[0] != y.shape[0]:
            raise ValueError(f"X rows ({X.shape[0]}) do not match y length ({y.shape[0]})")
        if X.shape[0] != len(case_ids):
            raise ValueError(f"X rows ({X.shape[0]}) do not match case_ids count ({len(case_ids)})")
        if X.ndim != 2:
            raise ValueError(f"X must be 2D array, got shape {X.shape}")
        if y.ndim != 1:
            raise ValueError(f"y must be 1D array, got shape {y.shape}")

        # Assert binary targets
        unique_targets = set(np.unique(y))
        if not unique_targets.issubset({0, 1}):
            raise ValueError(f"Target y must be binary in {{0, 1}}, got unique values: {unique_targets}")

        self.action = action
        self.X = X
        self.y = y
        self.case_ids = list(case_ids)
        self.feature_names = list(feature_names)

    @property
    def num_samples(self) -> int:
        return self.X.shape[0]

    @property
    def num_features(self) -> int:
        return self.X.shape[1]

    @property
    def positive_count(self) -> int:
        return int(np.sum(self.y == 1))

    @property
    def negative_count(self) -> int:
        return int(np.sum(self.y == 0))

    @property
    def positive_rate(self) -> float:
        return float(np.mean(self.y)) if self.num_samples > 0 else 0.0


class PotentialOutcomeDatasetBundle:
    """
    Bundle of action-conditional potential-outcome datasets across all candidate actions.
    """

    def __init__(
        self,
        split_name: str,
        datasets: Dict[RecoveryAction, ActionDataset],
        num_cases: int,
        feature_names: List[str],
    ):
        self.split_name = split_name
        self.datasets = datasets
        self.num_cases = num_cases
        self.feature_names = feature_names

    def get_dataset(self, action: RecoveryAction) -> ActionDataset:
        """Returns the ActionDataset for a specific action."""
        if action not in self.datasets:
            raise KeyError(f"Action '{action}' not found in dataset bundle.")
        return self.datasets[action]


def build_potential_outcome_datasets(
    cases: List[PaymentCase],
    ground_truth_map: Dict[str, CaseGroundTruth],
    split_name: str = "train",
    feature_extractor: Optional[FeatureExtractor] = None,
) -> PotentialOutcomeDatasetBundle:
    """
    Builds supervised action-conditional datasets for all recovery actions from cases and ground truth.

    Parameters:
        cases: Observable PaymentCase objects.
        ground_truth_map: Ground-truth registry holding potential outcomes Y(a).
        split_name: Name of the partition (train, val, test).
        feature_extractor: Optional FeatureExtractor instance.

    Returns:
        PotentialOutcomeDatasetBundle with datasets for all 5 recovery actions.
    """
    if not cases:
        raise ValueError("Cases list cannot be empty.")

    extractor = feature_extractor or FeatureExtractor()
    feature_names = extractor.feature_names
    num_cases = len(cases)

    # 1. Transform observable cases into feature matrix X (N x D)
    X = extractor.transform_cases(cases)
    case_ids = [c.case_id for c in cases]

    # Verify that case_ids and observable cases match ground truth exactly
    datasets: Dict[RecoveryAction, ActionDataset] = {}

    all_actions = [
        RecoveryAction.NO_ACTION,
        RecoveryAction.RETRY,
        RecoveryAction.PAYMENT_LINK,
        RecoveryAction.REMINDER,
        RecoveryAction.ESCALATE,
    ]

    for action in all_actions:
        y_list = []
        for case in cases:
            gt = ground_truth_map.get(case.case_id)
            if gt is None:
                raise KeyError(f"Missing ground truth record for case_id: '{case.case_id}'.")
            if action not in gt.potential_outcomes:
                raise KeyError(f"Missing potential outcome for action '{action}' in case '{case.case_id}'.")
            
            outcome = gt.potential_outcomes[action]
            if outcome not in (0, 1):
                raise ValueError(
                    f"Malformed potential outcome '{outcome}' for action '{action}' in case '{case.case_id}'."
                )
            y_list.append(int(outcome))

        y = np.array(y_list, dtype=np.int64)

        action_ds = ActionDataset(
            action=action,
            X=X,
            y=y,
            case_ids=case_ids,
            feature_names=feature_names,
        )
        datasets[action] = action_ds

    return PotentialOutcomeDatasetBundle(
        split_name=split_name,
        datasets=datasets,
        num_cases=num_cases,
        feature_names=feature_names,
    )


def load_split_dataset_bundle(
    data_dir: Path,
    split: str = "train",
    feature_extractor: Optional[FeatureExtractor] = None,
) -> PotentialOutcomeDatasetBundle:
    """
    Loads observable cases and hidden ground truth from disk and constructs the PotentialOutcomeDatasetBundle.

    Parameters:
        data_dir: Base directory containing sim_v1 splits.
        split: Split name (train, val, test).
        feature_extractor: Optional FeatureExtractor.

    Returns:
        PotentialOutcomeDatasetBundle.
    """
    split_dir = Path(data_dir) / split
    cases_file = split_dir / "observable_cases.json"
    gt_file = split_dir / "hidden_ground_truth.json"

    if not cases_file.exists() or not gt_file.exists():
        raise FileNotFoundError(f"Dataset split files not found in {split_dir}.")

    with open(cases_file, "r", encoding="utf-8") as f:
        cases_raw = json.load(f)
        cases = [PaymentCase.model_validate(item) for item in cases_raw]

    with open(gt_file, "r", encoding="utf-8") as f:
        gt_raw = json.load(f)
        gt_map = {cid: CaseGroundTruth.model_validate(item) for cid, item in gt_raw.items()}

    return build_potential_outcome_datasets(
        cases=cases,
        ground_truth_map=gt_map,
        split_name=split,
        feature_extractor=feature_extractor,
    )
