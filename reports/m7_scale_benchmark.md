# Milestone 7 Scale & Stress Benchmark Report — RecoverAI

> **Scope Notice**: *This document reports computational scalability, latency, memory, and statistical uncertainty under synthetic scale workloads (Mode B). It does NOT replace the authoritative frozen `sim_v1` scientific benchmark.*

## 1. Executive Workload & Performance Summary

- **Workload Profile**: `SMOKE`
- **Scale Workload Size**: **1,000 Cases** across **200 Unique Customers**
- **Total Revenue at Risk**: ₹2,798,838.00 (279,883,800 paise)
- **Total Benchmark Runtime**: **1,807.16 ms**
- **Overall Pipeline Throughput**: **553.4 cases/sec**
- **Peak Memory Allocated**: **5.82 MB** (5.958 KB/case)
- **Random Seed**: `42` (Common Random Numbers paired potential outcomes)

### Pipeline Stage Latency Breakdown

| Stage Name | Elapsed Time (ms) | Mean Latency / Case (ms) | Throughput (cases/sec) |
| :--- | :--- | :--- | :--- |
| `workload_generation` | 1,485.41 ms | 1.48541 ms | 673.2 |
| `model_resolution` | 6.22 ms | 0.00622 ms | 160,792.4 |
| `feature_extraction` | 68.16 ms | 0.06816 ms | 14,672.1 |
| `model_inference` | 84.48 ms | 0.08448 ms | 11,836.9 |
| `decision_selection` | 3.41 ms | 0.00341 ms | 293,410.0 |
| `outcome_simulation` | 40.06 ms | 0.04006 ms | 24,961.7 |
| `customer_bootstrap` | 74.25 ms | 0.07425 ms | 13,467.7 |
| `subgroup_analysis` | 45.17 ms | 0.04517 ms | 22,140.0 |

## 2. Policy Economic & Decision Performance (CRN Paired)

| Policy / Engine | Net Recovery (INR) | Gross Recovery (INR) | Cost (INR) | Delta vs Rule Baseline | Regret vs Oracle | Recovery Rate | Intervention Rate | Headroom % |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **No Action** | ₹50,690.00 | ₹50,690.00 | ₹0.00 | -₹1,755,807.00 | ₹1,999,326.00 | 2.3% | 0.0% | -721.0% |
| **Rule Baseline** | ₹1,806,497.00 | ₹1,819,177.00 | ₹12,680.00 | -- | ₹243,519.00 | 66.0% | 100.0% | -- |
| **Logistic Decision Engine (Champion)** | ₹1,991,477.00 | ₹2,009,934.00 | ₹18,457.00 | +₹184,980.00 | ₹58,539.00 | 69.8% | 100.0% | 76.0% |
| **Oracle (Benchmark Ceiling)** | ₹2,050,016.00 | ₹2,066,580.00 | ₹16,564.00 | +₹243,519.00 | ₹0.00 | 72.3% | 88.6% | 100.0% |

## 3. Customer-Clustered Bootstrap 95% Confidence Intervals

> *Bootstrap clusters by `customer_id` (B=500 replicates) to capture customer-level variance.*

| Policy | Net Recovery 95% CI (INR) | Delta vs Rule 95% CI (INR) | Recovery Rate 95% CI |
| :--- | :--- | :--- | :--- |
| **No Action** | [₹26,980.78, ₹79,228.27] | [₹-2,302,744.23, ₹-1,319,245.13] | [1.4%, 3.3%] |
| **Rule Baseline** | [₹1,360,216.15, ₹2,341,461.47] | -- | [62.9%, 69.0%] |
| **Logistic Decision Engine (Champion)** | [₹1,466,328.63, ₹2,666,726.57] | [₹45,631.55, ₹382,065.22] | [66.8%, 72.8%] |
| **Oracle (Benchmark Ceiling)** | [₹1,555,901.43, ₹2,679,755.57] | [₹132,758.08, ₹391,683.65] | [69.5%, 75.2%] |

## 4. Subgroup Stress & Segmentation Analysis (Champion Policy)

### Dimension: `Failure Type`

| Subgroup Segment | Cases (N) | Revenue at Risk (INR) | Net Recovery (INR) | Recovery Rate | Intervention Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `insufficient_funds` | 305 | ₹984,450.00 | ₹730,606.00 | 71.5% | 100.0% |
| `invalid_payment_method` | 187 | ₹496,425.00 | ₹345,914.00 | 71.7% | 100.0% |
| `temporary_failure` | 400 | ₹1,041,325.00 | ₹707,160.00 | 66.5% | 100.0% |
| `unknown_failure` | 108 | ₹276,638.00 | ₹207,797.00 | 74.1% | 100.0% |

### Dimension: `Payment Method`

| Subgroup Segment | Cases (N) | Revenue at Risk (INR) | Net Recovery (INR) | Recovery Rate | Intervention Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `card` | 257 | ₹780,379.00 | ₹583,539.00 | 70.8% | 100.0% |
| `mandate` | 112 | ₹472,312.00 | ₹353,115.00 | 71.4% | 100.0% |
| `netbanking` | 186 | ₹542,094.00 | ₹347,600.00 | 64.0% | 100.0% |
| `upi` | 445 | ₹1,004,053.00 | ₹707,223.00 | 71.2% | 100.0% |

### Dimension: `Retry Count`

| Subgroup Segment | Cases (N) | Revenue at Risk (INR) | Net Recovery (INR) | Recovery Rate | Intervention Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `retries_0` | 676 | ₹1,771,192.00 | ₹1,226,508.00 | 69.2% | 100.0% |
| `retries_1` | 208 | ₹616,092.00 | ₹434,454.00 | 67.8% | 100.0% |
| `retries_2` | 77 | ₹250,525.00 | ₹207,131.00 | 76.6% | 100.0% |
| `retries_3` | 39 | ₹161,029.00 | ₹123,384.00 | 76.9% | 100.0% |

### Dimension: `Subscription`

| Subgroup Segment | Cases (N) | Revenue at Risk (INR) | Net Recovery (INR) | Recovery Rate | Intervention Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `one_off` | 841 | ₹1,978,319.00 | ₹1,356,199.00 | 68.8% | 100.0% |
| `subscription` | 159 | ₹820,519.00 | ₹635,278.00 | 74.8% | 100.0% |

### Dimension: `Amount Tier`

| Subgroup Segment | Cases (N) | Revenue at Risk (INR) | Net Recovery (INR) | Recovery Rate | Intervention Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `1. Micro (< INR 200)` | 6 | ₹969.00 | ₹606.00 | 66.7% | 100.0% |
| `2. Low (INR 200 - 1k)` | 222 | ₹143,815.00 | ₹100,975.00 | 72.1% | 100.0% |
| `3. Mid (INR 1k - 5k)` | 637 | ₹1,447,333.00 | ₹962,387.00 | 68.3% | 100.0% |
| `4. High (> INR 5k)` | 135 | ₹1,206,721.00 | ₹927,509.00 | 73.3% | 100.0% |

### Dimension: `Customer Success Tier`

| Subgroup Segment | Cases (N) | Revenue at Risk (INR) | Net Recovery (INR) | Recovery Rate | Intervention Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `2. Medium (60-80%)` | 331 | ₹1,280,111.00 | ₹948,662.00 | 70.1% | 100.0% |
| `3. High (> 80%)` | 669 | ₹1,518,727.00 | ₹1,042,815.00 | 69.7% | 100.0% |

## 5. Reproducibility & Environment Manifest

- **Benchmark Version**: `1.0.0`
- **Execution Timestamp**: `2026-09-05T09:44:52Z`
- **Python Version**: `3.13.7`
- **Platform**: `Windows-11-10.0.26200-SP0`
- **NumPy Version**: `2.4.4` | **pandas**: `2.3.3` | **scikit-learn**: `1.8.0`
- **Model Artifact**: `models/champion_recovery_model.pkl`
- **Action Costs Configuration**: `{"no_action": 0, "retry": 200, "payment_link": 1000, "reminder": 500, "escalate": 5000}`

