# Final Benchmark Evaluation Report — RecoverAI (Held-Out Test Split)

- **Dataset**: `sim_v1` Held-Out Test Set (1,500 Cases, 300 Unseen Customers)
- **Total Revenue at Risk**: ₹4,065,306.00 (406,530,600 paise)
- **Evaluation Framework**: Potential Outcomes under Common Random Numbers (Deterministic Realization)

## 1. Primary Economic Benchmark Table

| Policy / Model Engine | Net Recovery (INR) | Gross Recovery (INR) | Intervention Cost (INR) | Delta vs Rule Baseline | Regret vs Oracle | Recovery Rate | Intervention Rate | Oracle Headroom Captured |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **No Action** | ₹66,517.00 | ₹66,517.00 | ₹0.00 | -₹2,638,788.00 (-97.54%) | ₹2,936,714.00 | 2.7% | 0.0% | -885.7% |
| **Rule Baseline** | ₹2,705,305.00 | ₹2,724,137.00 | ₹18,832.00 | -- | ₹297,926.00 | 69.2% | 100.0% | -- |
| **Logistic Decision Engine** | ₹2,946,931.00 | ₹2,972,057.00 | ₹25,126.00 | +₹241,626.00 (+8.93%) | ₹56,300.00 | 71.3% | 100.0% | 81.1% |
| **GBM Decision Engine** | ₹2,831,319.00 | ₹2,859,193.00 | ₹27,874.00 | +₹126,014.00 (+4.66%) | ₹171,912.00 | 69.6% | 100.0% | 42.3% |
| **Oracle** | ₹3,003,231.00 | ₹3,025,648.00 | ₹22,417.00 | +₹297,926.00 (+11.01%) | ₹0.00 | 72.9% | 88.5% | 100.0% |

## 2. Action Distributions

| Policy / Engine | No Action | Retry | Payment Link | Reminder | Escalate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **No Action** | 1500 (100.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| **Rule Baseline** | 0 (0.0%) | 561 (37.4%) | 731 (48.7%) | 0 (0.0%) | 208 (13.9%) |
| **Logistic Decision Engine** | 0 (0.0%) | 423 (28.2%) | 602 (40.1%) | 122 (8.1%) | 353 (23.5%) |
| **GBM Decision Engine** | 0 (0.0%) | 377 (25.1%) | 638 (42.5%) | 78 (5.2%) | 407 (27.1%) |
| **Oracle** | 172 (11.5%) | 381 (25.4%) | 504 (33.6%) | 123 (8.2%) | 320 (21.3%) |
