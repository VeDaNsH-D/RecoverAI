"""
Tests for ML recovery probability models (Logistic Regression, HistGradientBoosting, and MultiActionRecoveryModel).
"""

import tempfile
from pathlib import Path
import pytest
import numpy as np

from simulator.config import RecoveryAction
from simulator.generators.customer_generator import generate_customers
from simulator.generators.case_generator import generate_cases
from simulator.generators.ground_truth_generator import generate_ground_truth
from ml.dataset import build_potential_outcome_datasets
from ml.models.base import BaseRecoveryModel
from ml.models.logistic_model import LogisticRecoveryModel
from ml.models.gbm_model import GBMRecoveryModel
from ml.models.bundle import MultiActionRecoveryModel, create_multi_action_model, ACTION_ORDER
from ml.evaluator import calculate_expected_calibration_error, evaluate_action_model


@pytest.fixture
def sample_dataset_bundle():
    customers = generate_customers(count=50, seed=42)
    cases = generate_cases(customers=customers, total_cases=300, seed=42)
    cust_map = {c.customer_id: c for c in customers}
    gt_map = generate_ground_truth(cases, cust_map, seed=42)
    return build_potential_outcome_datasets(cases, gt_map, split_name="train_sample")


@pytest.mark.parametrize("model_cls", [LogisticRecoveryModel, GBMRecoveryModel])
def test_all_models_can_train_on_all_action_datasets(model_cls, sample_dataset_bundle):
    for act in ACTION_ORDER:
        ds = sample_dataset_bundle.get_dataset(act)
        model = model_cls(action=act, calibrate=True, random_state=42)
        assert not model.is_fitted

        model.fit(ds.X, ds.y)
        assert model.is_fitted

        # Predict proba shape
        probs = model.predict_proba(ds.X)
        assert probs.shape == (ds.num_samples, 2)

        # Probability bounds
        assert np.all(probs >= 0.0)
        assert np.all(probs <= 1.0)
        np.testing.assert_allclose(probs.sum(axis=1), 1.0, rtol=1e-5)

        # Positive probabilities
        pos_probs = model.predict_positive_proba(ds.X)
        assert pos_probs.shape == (ds.num_samples,)
        np.testing.assert_array_equal(pos_probs, probs[:, 1])

        # Binary predictions
        preds = model.predict(ds.X)
        assert preds.shape == (ds.num_samples,)
        assert set(np.unique(preds)).issubset({0, 1})


def test_prediction_determinism(sample_dataset_bundle):
    ds = sample_dataset_bundle.get_dataset(RecoveryAction.RETRY)

    m1 = LogisticRecoveryModel(action=RecoveryAction.RETRY, random_state=42).fit(ds.X, ds.y)
    m2 = LogisticRecoveryModel(action=RecoveryAction.RETRY, random_state=42).fit(ds.X, ds.y)
    np.testing.assert_allclose(m1.predict_proba(ds.X), m2.predict_proba(ds.X))

    g1 = GBMRecoveryModel(action=RecoveryAction.RETRY, random_state=42).fit(ds.X, ds.y)
    g2 = GBMRecoveryModel(action=RecoveryAction.RETRY, random_state=42).fit(ds.X, ds.y)
    np.testing.assert_allclose(g1.predict_proba(ds.X), g2.predict_proba(ds.X))


def test_models_reject_malformed_inputs(sample_dataset_bundle):
    ds = sample_dataset_bundle.get_dataset(RecoveryAction.RETRY)
    model = LogisticRecoveryModel(action=RecoveryAction.RETRY)

    # Wrong feature dimension
    X_bad_dim = np.zeros((10, 10))
    y_good = np.zeros(10, dtype=np.int64)
    with pytest.raises(ValueError, match="Feature dimension mismatch"):
        model.fit(X_bad_dim, y_good)

    # Sample count mismatch
    X_good = ds.X[:10]
    y_bad_len = np.zeros(5, dtype=np.int64)
    with pytest.raises(ValueError, match="Sample count mismatch"):
        model.fit(X_good, y_bad_len)

    # Non-binary target
    y_non_binary = np.array([0, 1, 2, 0, 1, 0, 1, 0, 1, 0], dtype=np.int64)
    with pytest.raises(ValueError, match="Target y must be binary"):
        model.fit(X_good, y_non_binary)

    # Predict before fitting
    with pytest.raises(RuntimeError, match="has not been fitted yet"):
        model.predict_proba(X_good)


def test_dataset_immutability_during_fitting(sample_dataset_bundle):
    ds = sample_dataset_bundle.get_dataset(RecoveryAction.PAYMENT_LINK)
    X_orig = np.array(ds.X, copy=True)
    y_orig = np.array(ds.y, copy=True)

    model = GBMRecoveryModel(action=RecoveryAction.PAYMENT_LINK, calibrate=True).fit(ds.X, ds.y)
    _ = model.predict_proba(ds.X)

    np.testing.assert_array_equal(ds.X, X_orig)
    np.testing.assert_array_equal(ds.y, y_orig)


def test_multi_action_model_bundle(sample_dataset_bundle):
    multi_model = create_multi_action_model(model_type="gbm", calibrate=True, random_state=42)
    assert not multi_model.is_fitted

    multi_model.fit_all(sample_dataset_bundle)
    assert multi_model.is_fitted

    # Test all actions prediction
    ds = sample_dataset_bundle.get_dataset(RecoveryAction.NO_ACTION)
    all_pos_probs = multi_model.predict_all_positive_probas(ds.X)

    assert len(all_pos_probs) == 5
    for act in ACTION_ORDER:
        assert act in all_pos_probs
        probs = all_pos_probs[act]
        assert probs.shape == (ds.num_samples,)
        assert np.all(probs >= 0.0)
        assert np.all(probs <= 1.0)


def test_model_serialization_and_deserialization(sample_dataset_bundle):
    ds = sample_dataset_bundle.get_dataset(RecoveryAction.ESCALATE)
    single_model = LogisticRecoveryModel(action=RecoveryAction.ESCALATE).fit(ds.X, ds.y)
    multi_model = create_multi_action_model(model_type="gbm").fit_all(sample_dataset_bundle)

    with tempfile.TemporaryDirectory() as tmp_dir:
        single_path = Path(tmp_dir) / "single_model.pkl"
        multi_path = Path(tmp_dir) / "multi_model.pkl"

        # Save and reload single model
        single_model.save(single_path)
        loaded_single = LogisticRecoveryModel.load(single_path)
        assert loaded_single.is_fitted
        np.testing.assert_allclose(single_model.predict_proba(ds.X), loaded_single.predict_proba(ds.X))

        # Save and reload multi model
        multi_model.save(multi_path)
        loaded_multi = MultiActionRecoveryModel.load(multi_path)
        assert loaded_multi.is_fitted
        for act in ACTION_ORDER:
            np.testing.assert_allclose(
                multi_model.predict_positive_proba(ds.X, act),
                loaded_multi.predict_positive_proba(ds.X, act),
            )


def test_calibration_metric_calculations():
    y_true = np.array([0, 0, 1, 1, 1, 0, 1, 0, 0, 1])
    y_prob = np.array([0.1, 0.2, 0.8, 0.9, 0.7, 0.3, 0.85, 0.15, 0.05, 0.95])

    ece = calculate_expected_calibration_error(y_true, y_prob, n_bins=5)
    assert 0.0 <= ece <= 1.0
    assert ece < 0.20  # Well-calibrated test probabilities should have low ECE
