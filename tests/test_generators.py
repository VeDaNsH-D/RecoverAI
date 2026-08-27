"""
Tests for customer, case, and dataset split generation.
"""

import pytest
from simulator.config import FailureType, PaymentMethod
from simulator.generators.customer_generator import generate_customers
from simulator.generators.case_generator import generate_cases
from simulator.schemas.customer import CustomerProfile
from simulator.schemas.case import PaymentCase


def test_customer_generator_properties():
    customers = generate_customers(count=100, seed=42)
    assert len(customers) == 100

    for c in customers:
        assert isinstance(c, CustomerProfile)
        assert c.customer_id.startswith("cust_")
        assert 0.0 <= c.historical_success_rate <= 1.0
        assert c.total_transactions >= 1
        assert 0 <= c.total_failures <= c.total_transactions
        assert c.avg_transaction_amount_paise >= 5000  # at least ₹50
        assert c.default_payment_method in PaymentMethod
        assert 1 <= c.tenure_months <= 60


def test_case_generator_properties():
    customers = generate_customers(count=50, seed=42)
    cases = generate_cases(customers=customers, total_cases=200, seed=42)
    assert len(cases) == 200

    cust_ids = {c.customer_id for c in customers}
    for case in cases:
        assert isinstance(case, PaymentCase)
        assert case.case_id.startswith("case_")
        assert case.customer_id in cust_ids
        assert case.amount_paise >= 100
        assert case.failure_type in FailureType
        assert case.payment_method in PaymentMethod
        assert case.retry_count >= 0
        assert case.hours_since_failure >= 0.0
        assert isinstance(case.created_at, str)


def test_dataset_customer_disjoint_splits():
    """Verify that train, val, and test customers do not overlap."""
    customers = generate_customers(count=100, seed=123)
    train_custs = customers[:70]
    val_custs = customers[70:85]
    test_custs = customers[85:]

    train_ids = {c.customer_id for c in train_custs}
    val_ids = {c.customer_id for c in val_custs}
    test_ids = {c.customer_id for c in test_custs}

    assert len(train_ids.intersection(val_ids)) == 0
    assert len(train_ids.intersection(test_ids)) == 0
    assert len(val_ids.intersection(test_ids)) == 0
