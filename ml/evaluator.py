"""
Predictive evaluation and validation diagnostics for RecoverAI ML probability models.
Computes Log Loss, Brier Score, ROC-AUC, and Expected Calibration Error (ECE).
"""

from typing import Dict, List, Optional
import numpy as np
from pydantic import BaseModel
from sklearn.metrics import log_loss, brier_score_loss, roc_auc_score

from simulator.config import RecoveryAction
from ml.dataset import ActionDataset, PotentialOutcomeDatasetBundle
from ml.models.base import BaseRecoveryModel
from ml.models.bundle import MultiActionRecoveryModel, ACTION_ORDER


class ActionModelMetrics(BaseModel):
    """
    Predictive quality metrics for a single action model evaluated on a dataset.
    """
    action: str
    model_type: str
    num_samples: int
    positive_samples: int
    positive_rate: float
    log_loss: float
    brier_score: float
    roc_auc: Optional[float]
    expected_calibration_error: float


class ValidationDiagnosticReport(BaseModel):
    """
    Validation comparison diagnostic report across multiple model architectures.
    """
    split_name: str
    num_cases: int
    results: Dict[str, Dict[str, ActionModelMetrics]]  # model_name -> (action -> metrics)

    def generate_console_report(self) -> str:
        lines = []
        lines.append("=" * 95)
        lines.append(f" RECOVERAI ML VALIDATION DIAGNOSTIC REPORT (SPLIT: {self.split_name.upper()} -- {self.num_cases:,} Cases)")
        lines.append("=" * 95)

        headers = ["Action", "Model Type", "Log Loss", "Brier Score", "ROC-AUC", "ECE", "Pos Rate"]
        row_fmt = "{:<16} | {:<22} | {:>9} | {:>11} | {:>8} | {:>7} | {:>8}"
        lines.append(row_fmt.format(*headers))
        lines.append("-" * 95)

        for act in ACTION_ORDER:
            act_str = act.value
            for model_name, action_map in self.results.items():
                m = action_map.get(act_str)
                if m:
                    auc_str = f"{m.roc_auc:.4f}" if m.roc_auc is not None else "N/A"
                    lines.append(row_fmt.format(
                        act_str,
                        m.model_type,
                        f"{m.log_loss:.4f}",
                        f"{m.brier_score:.4f}",
                        auc_str,
                        f"{m.expected_calibration_error:.4f}",
                        f"{m.positive_rate:.2%}",
                    ))
            lines.append("-" * 95)

        lines.append("=" * 95)
        return "\n".join(lines)


def calculate_expected_calibration_error(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> float:
    """
    Calculates the Expected Calibration Error (ECE) with equal-width binning.
    """
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    total_samples = len(y_true)

    for i in range(n_bins):
        bin_lower, bin_upper = bin_edges[i], bin_edges[i + 1]
        if i == n_bins - 1:
            in_bin = (y_prob >= bin_lower) & (y_prob <= bin_upper)
        else:
            in_bin = (y_prob >= bin_lower) & (y_prob < bin_upper)
        
        bin_count = np.sum(in_bin)
        if bin_count > 0:
            bin_acc = np.mean(y_true[in_bin])
            bin_conf = np.mean(y_prob[in_bin])
            ece += (bin_count / total_samples) * abs(bin_acc - bin_conf)

    return float(ece)


def evaluate_action_model(
    model: BaseRecoveryModel,
    dataset: ActionDataset,
) -> ActionModelMetrics:
    """
    Evaluates a single action recovery model on an ActionDataset.
    """
    probs = model.predict_proba(dataset.X)
    pos_probs = probs[:, 1]
    y_true = dataset.y

    # Log Loss (with epsilon clipping to avoid log(0))
    ll = float(log_loss(y_true, probs, labels=[0, 1]))

    # Brier Score
    bs = float(brier_score_loss(y_true, pos_probs))

    # ROC-AUC
    unique_classes = len(np.unique(y_true))
    if unique_classes > 1:
        auc = float(roc_auc_score(y_true, pos_probs))
    else:
        auc = None

    # Expected Calibration Error
    ece = calculate_expected_calibration_error(y_true, pos_probs)

    return ActionModelMetrics(
        action=dataset.action.value,
        model_type=model.model_type,
        num_samples=dataset.num_samples,
        positive_samples=dataset.positive_count,
        positive_rate=dataset.positive_rate,
        log_loss=round(ll, 4),
        brier_score=round(bs, 4),
        roc_auc=round(auc, 4) if auc is not None else None,
        expected_calibration_error=round(ece, 4),
    )


def evaluate_multi_action_model(
    multi_model: MultiActionRecoveryModel,
    dataset_bundle: PotentialOutcomeDatasetBundle,
) -> Dict[str, ActionModelMetrics]:
    """
    Evaluates a MultiActionRecoveryModel across all 5 actions in a dataset bundle.
    """
    results: Dict[str, ActionModelMetrics] = {}
    for act in ACTION_ORDER:
        model = multi_model.get_model(act)
        ds = dataset_bundle.get_dataset(act)
        results[act.value] = evaluate_action_model(model, ds)
    return results


def run_validation_comparison(
    models: Dict[str, MultiActionRecoveryModel],
    val_bundle: PotentialOutcomeDatasetBundle,
) -> ValidationDiagnosticReport:
    """
    Compares multiple trained MultiActionRecoveryModel bundles on a validation dataset.
    """
    all_results: Dict[str, Dict[str, ActionModelMetrics]] = {}
    for name, multi_model in models.items():
        all_results[name] = evaluate_multi_action_model(multi_model, val_bundle)

    return ValidationDiagnosticReport(
        split_name=val_bundle.split_name,
        num_cases=val_bundle.num_cases,
        results=all_results,
    )
