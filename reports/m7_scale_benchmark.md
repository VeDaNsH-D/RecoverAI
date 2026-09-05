# Milestone 7 Scale & Stress Benchmark Report — RecoverAI

> **Scope Notice**: *This document reports computational scalability, latency, memory, and statistical uncertainty under synthetic scale workloads (Mode B). It does NOT replace the authoritative frozen `sim_v1` scientific benchmark.*

## 1. Executive Workload & Performance Summary

- **Workload Profile**: `STANDARD`
- **Scale Workload Size**: **10,000 Cases** across **2,000 Unique Customers**
- **Total Revenue at Risk**: ₹26,007,700.00 (2,600,770,000 paise)
- **Total Benchmark Runtime**: **18,920.50 ms**
- **Overall Pipeline Throughput**: **528.5 cases/sec**
- **Peak Memory Allocated**: **54.82 MB** (5.613 KB/case)
- **Random Seed**: `42` (Common Random Numbers paired potential outcomes)

### Pipeline Stage Latency Breakdown

| Stage Name | Elapsed Time (ms) | Mean Latency / Case (ms) | Throughput (cases/sec) |
| :--- | :--- | :--- | :--- |
| `workload_generation` | 15,461.12 ms | 1.54611 ms | 646.8 |
| `model_resolution` | 6.05 ms | 0.00061 ms | 1,651,991.5 |
| `feature_extraction` | 966.45 ms | 0.09664 ms | 10,347.2 |
| `model_inference` | 169.65 ms | 0.01696 ms | 58,945.4 |
| `decision_selection` | 34.80 ms | 0.00348 ms | 287,344.8 |
| `outcome_simulation` | 973.83 ms | 0.09738 ms | 10,268.7 |
| `customer_bootstrap` | 679.47 ms | 0.06795 ms | 14,717.4 |
| `subgroup_analysis` | 629.13 ms | 0.06291 ms | 15,895.0 |

## 2. Policy Economic & Decision Performance (CRN Paired)

| Policy / Engine | Net Recovery (INR) | Gross Recovery (INR) | Cost (INR) | Delta vs Rule Baseline | Regret vs Oracle | Recovery Rate | Intervention Rate | Headroom % |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **No Action** | ₹662,498.00 | ₹662,498.00 | ₹0.00 | -₹16,579,877.00 | ₹17,684,550.00 | 2.3% | 0.0% | -1500.9% |
| **Rule Baseline** | ₹17,242,375.00 | ₹17,365,463.00 | ₹123,088.00 | -- | ₹1,104,673.00 | 67.2% | 100.0% | -- |
| **Logistic Decision Engine (Champion)** | ₹18,068,576.00 | ₹18,234,665.00 | ₹166,089.00 | +₹826,201.00 | ₹278,472.00 | 69.5% | 100.0% | 74.8% |
| **Oracle (Benchmark Ceiling)** | ₹18,347,048.00 | ₹18,498,281.00 | ₹151,233.00 | +₹1,104,673.00 | ₹0.00 | 70.6% | 88.2% | 100.0% |

## 3. Customer-Clustered Bootstrap 95% Confidence Intervals

> *Bootstrap clusters by `customer_id` (B=500 replicates) to capture customer-level variance.*

| Policy | Net Recovery 95% CI (INR) | Delta vs Rule 95% CI (INR) | Recovery Rate 95% CI |
| :--- | :--- | :--- | :--- |
| **No Action** | [₹528,867.53, ₹799,206.35] | [₹-17,802,580.10, ₹-15,398,260.62] | [2.0%, 2.7%] |
| **Rule Baseline** | [₹15,977,005.80, ₹18,480,133.62] | -- | [66.2%, 68.1%] |
| **Logistic Decision Engine (Champion)** | [₹16,700,175.75, ₹19,394,842.30] | [₹566,808.25, ₹1,100,625.35] | [68.6%, 70.3%] |
| **Oracle (Benchmark Ceiling)** | [₹17,005,315.00, ₹19,763,830.05] | [₹805,714.28, ₹1,405,549.22] | [69.8%, 71.5%] |

## 4. Subgroup Stress & Segmentation Analysis (Champion Policy)

### Dimension: `Failure Type`

| Subgroup Segment | Cases (N) | Revenue at Risk (INR) | Net Recovery (INR) | Recovery Rate | Intervention Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `insufficient_funds` | 2,989 | ₹7,598,377.00 | ₹5,156,914.00 | 68.3% | 100.0% |
| `invalid_payment_method` | 2,069 | ₹5,613,579.00 | ₹4,170,886.00 | 72.8% | 100.0% |
| `temporary_failure` | 3,948 | ₹10,232,038.00 | ₹6,753,000.00 | 66.4% | 100.0% |
| `unknown_failure` | 994 | ₹2,563,706.00 | ₹1,987,776.00 | 78.3% | 100.0% |

### Dimension: `Payment Method`

| Subgroup Segment | Cases (N) | Revenue at Risk (INR) | Net Recovery (INR) | Recovery Rate | Intervention Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `card` | 2,962 | ₹7,460,404.00 | ₹5,251,293.00 | 70.2% | 100.0% |
| `mandate` | 851 | ₹2,097,021.00 | ₹1,440,692.00 | 69.0% | 100.0% |
| `netbanking` | 1,617 | ₹4,470,128.00 | ₹3,112,144.00 | 69.6% | 100.0% |
| `upi` | 4,570 | ₹11,980,147.00 | ₹8,264,447.00 | 69.1% | 100.0% |

### Dimension: `Retry Count`

| Subgroup Segment | Cases (N) | Revenue at Risk (INR) | Net Recovery (INR) | Recovery Rate | Intervention Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `retries_0` | 6,837 | ₹17,725,887.00 | ₹12,348,003.00 | 70.4% | 100.0% |
| `retries_1` | 2,000 | ₹5,286,880.00 | ₹3,444,656.00 | 63.8% | 100.0% |
| `retries_2` | 785 | ₹2,031,784.00 | ₹1,548,055.00 | 74.3% | 100.0% |
| `retries_3` | 378 | ₹963,149.00 | ₹727,862.00 | 72.8% | 100.0% |

### Dimension: `Subscription`

| Subgroup Segment | Cases (N) | Revenue at Risk (INR) | Net Recovery (INR) | Recovery Rate | Intervention Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `one_off` | 7,833 | ₹20,519,130.00 | ₹14,219,540.00 | 69.2% | 100.0% |
| `subscription` | 2,167 | ₹5,488,570.00 | ₹3,849,036.00 | 70.6% | 100.0% |

### Dimension: `Amount Tier`

| Subgroup Segment | Cases (N) | Revenue at Risk (INR) | Net Recovery (INR) | Recovery Rate | Intervention Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `1. Micro (< INR 200)` | 104 | ₹15,909.00 | ₹9,560.00 | 65.4% | 100.0% |
| `2. Low (INR 200 - 1k)` | 2,735 | ₹1,785,674.00 | ₹1,179,977.00 | 67.8% | 100.0% |
| `3. Mid (INR 1k - 5k)` | 5,918 | ₹13,485,450.00 | ₹9,312,730.00 | 70.0% | 100.0% |
| `4. High (> INR 5k)` | 1,243 | ₹10,720,667.00 | ₹7,566,309.00 | 71.1% | 100.0% |

### Dimension: `Customer Success Tier`

| Subgroup Segment | Cases (N) | Revenue at Risk (INR) | Net Recovery (INR) | Recovery Rate | Intervention Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `2. Medium (60-80%)` | 2,615 | ₹6,770,702.00 | ₹4,606,160.00 | 68.0% | 100.0% |
| `3. High (> 80%)` | 7,385 | ₹19,236,998.00 | ₹13,462,416.00 | 70.0% | 100.0% |

## 5. Reproducibility & Environment Manifest

- **Benchmark Version**: `1.0.0`
- **Execution Timestamp**: `2026-09-05T07:08:01Z`
- **Python Version**: `3.13.7`
- **Platform**: `Windows-11-10.0.26200-SP0`
- **NumPy Version**: `2.4.4` | **pandas**: `2.3.3` | **scikit-learn**: `1.8.0`
- **Model Artifact**: `models/champion_recovery_model.pkl`
- **Action Costs Configuration**: `{"no_action": 0, "retry": 200, "payment_link": 1000, "reminder": 500, "escalate": 5000}`

