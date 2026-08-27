"""
Tests for action-conditional potential-outcome supervised datasets.
Verifies target construction, anti-leakage isolation, shape consistency, and split separation.
"""

import json
from pathlib import Path
import pytest
import numpy as np

from simulator.config import RecoveryAction, FailureType, PaymentMethod
from simulator.generators.customer_generator import generate_customers
from simulator.generators.case_generator import generate_cases
from simulator.generators.ground_truth_generator import generate_ground_truth
from simulator.schemas.case import PaymentCase
from ml.features import CANONICAL_FEATURE_NAMES
from ml.dataset import (
    ActionDataset,
    PotentialOutcomeDatasetBundle,
    build_potential_outcome_datasets,
    load_split_dataset_bundle,
)


@pytest.fixture
def sample_cases_and_gt():
    customers = generate_customers(count=20, seed=42)
    cases = generate_cases(customers=customers, total_cases=50, seed=42)
    cust_map = {c.customer_id: c for c in customers}
    gt_map = generate_ground_truth(cases, cust_map, seed=42)
    return cases, gt_map


def test_action_dataset_properties(sample_cases_and_gt):
    cases, gt_map = sample_cases_and_gt
    bundle = build_potential_outcome_datasets(cases, gt_map, split_name="test_split")

    assert isinstance(bundle, PotentialOutcomeDatasetBundle)
    assert bundle.num_cases == 50
    assert bundle.feature_names == CANONICAL_FEATURE_NAMES

    # All 5 actions must be present
    for act in RecoveryAction:
        ds = bundle.get_dataset(act)
        assert isinstance(ds, ActionDataset)
        assert ds.action == act
        assert ds.num_samples == 50
        assert ds.num_features == 24
        assert ds.X.shape == (50, 24)
        assert ds.y.shape == (50,)
        assert ds.y.dtype == np.int64
        
        # Binary target verification
        unique_targets = set(np.unique(ds.y))
        assert unique_targets.issubset({0, 1})
        assert 0.0 <= ds.positive_rate <= 1.0
        assert ds.positive_count + ds.negative_count == 50


def test_anti_leakage_in_dataset_matrix(sample_cases_and_gt):
    """
    CRITICAL TEST: Target y comes from Y(a), but X must contain ZERO ground truth or latent fields.
    """
    cases, gt_map = sample_cases_and_gt
    bundle = build_potential_outcome_datasets(cases, gt_map, split_name="train")

    for act in RecoveryAction:
        ds = bundle.get_dataset(act)
        
        # Feature names must match exactly the canonical observable allowlist
        assert ds.feature_names == CANONICAL_FEATURE_NAMES

        # Ensure no latent intent/funds or ground-truth probabilities are columns in X
        for col_name in ds.feature_names:
            assert "latent" not in col_name
            assert "ground_truth" not in col_name
            assert "optimal" not in col_name
            assert "oracle" not in col_name
            assert "outcome" not in col_name


def test_deterministic_dataset_construction(sample_cases_and_gt):
    cases, gt_map = sample_cases_and_gt

    bundle1 = build_potential_outcome_datasets(cases, gt_map, split_name="train")
    bundle2 = build_potential_outcome_datasets(cases, gt_map, split_name="train")

    for act in RecoveryAction:
        ds1 = bundle1.get_dataset(act)
        ds2 = bundle2.get_dataset(act)

        np.testing.assert_array_equal(ds1.X, ds2.X)
        np.testing.assert_array_equal(ds1.y, ds2.y)
        assert ds1.case_ids == ds2.case_ids


def test_missing_ground_truth_raises_key_error(sample_cases_and_gt):
    cases, gt_map = sample_cases_and_gt
    
    # Remove one case from ground truth
    corrupted_gt = dict(gt_map)
    del corrupted_gt[cases[0].case_id]

    with pytest.raises(KeyError, match="Missing ground truth record"):
        build_potential_outcome_datasets(cases, corrupted_gt)


def test_malformed_target_detection():
    # Directly test ActionDataset validator on non-binary targets
    X = np.zeros((10, 24), dtype=np.float64)
    y_malformed = np.array([0, 1, 2, 0, 1, 0, 1, 0, 1, 0], dtype=np.int64)  # Contains 2
    case_ids = [f"c_{i}" for i in range(10)]

    with pytest.raises(ValueError, match="Target y must be binary"):
        ActionDataset(
            action=RecoveryAction.RETRY,
            X=X,
            y=y_malformed,
            case_ids=case_ids,
            feature_names=CANONICAL_FEATURE_NAMES,
        )


def test_load_sim_v1_splits_from_disk():
    """Verify that frozen sim_v1 train, val, and test splits load cleanly with proper dimensions."""
    data_dir = Path("data/sim_v1")
    if not data_dir.exists():
        pytest.skip("data/sim_v1 not generated yet")

    train_bundle = load_split_dataset_bundle(data_dir, split="train")
    assert train_bundle.num_cases == 7000

    val_bundle = load_split_dataset_bundle(data_dir, split="val")
    assert val_bundle.num_cases == 1500

    test_bundle = load_split_dataset_bundle(data_dir, split="test")
    assert test_bundle.num_cases == 1500

    # Ensure train and test customer IDs are completely disjoint
    with open(data_dir / "train" / "observable_cases.json") as f:
        train_custs = {x["customer_id"] for x in json.load(f)}
    with open(data_dir / "test" / "observable_cases.json") as f:
        test_custs = {x["customer_id"] for x in json.load(f)}
    with open(data_dir / "val" / "observable_cases.json") as f:
        val_custs = {x["customer_id"] for x in json.load(f)}

    assert len(train_custs.intersection(test_custs)) == 0
    assert len(train_custs.intersection(val_custs)) == 0
    assert len(val_custs.intersection(test_custs)) == 0
