"""
Strict verification of Data Leakage Prevention.
Asserts that observable models and policy inputs contain zero hidden ground-truth fields.
"""

import json
import pytest
from simulator.generators.customer_generator import generate_customers
from simulator.generators.case_generator import generate_cases
from simulator.schemas.case import PaymentCase
from simulator.policies.base import BasePolicy
from simulator.policies.rule_baseline import RuleBasedBaselinePolicy


FORBIDDEN_GROUND_TRUTH_KEYS = [
    "is_recoverable",
    "is_recoverable_indicator",
    "recovery_probabilities",
    "potential_outcomes",
    "latent_intent",
    "latent_funds_available",
    "latent_customer_intent",
    "latent_funds",
    "optimal_action",
    "expected_net_values_paise",
    "expected_recovery_value",
    "actual_outcome",
    "ground_truth_probability",
    "ground_truth_best_action",
]


def test_payment_case_schema_has_no_ground_truth_fields():
    """Verify PaymentCase fields at the schema reflection level."""
    case_fields = set(PaymentCase.model_fields.keys())
    for forbidden in FORBIDDEN_GROUND_TRUTH_KEYS:
        assert forbidden not in case_fields, f"Data leakage: '{forbidden}' found in PaymentCase schema!"


def test_serialized_case_has_no_ground_truth_keys():
    """Verify that serialized case dictionaries and JSON strings contain no ground truth."""
    customers = generate_customers(count=10, seed=42)
    cases = generate_cases(customers=customers, total_cases=25, seed=42)

    for case in cases:
        case_dict = case.model_dump()
        json_str = json.dumps(case_dict)

        for forbidden in FORBIDDEN_GROUND_TRUTH_KEYS:
            assert forbidden not in case_dict, f"Leakage in dict: {forbidden}"
            assert f'"{forbidden}"' not in json_str, f"Leakage in json: {forbidden}"


def test_policy_operates_strictly_on_observable_case():
    """Verify that the baseline policy can execute with only observable features."""
    customers = generate_customers(count=10, seed=42)
    cases = generate_cases(customers=customers, total_cases=20, seed=42)
    policy = RuleBasedBaselinePolicy()

    for case in cases:
        action = policy.predict(case)
        assert action is not None
