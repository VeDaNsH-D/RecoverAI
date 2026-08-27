# Causal Ground-Truth & Potential Outcomes Model — RecoverAI

## 1. Causal Architecture Overview

The synthetic revenue recovery world is governed by a causal structural equation model (SEM). The recovery probability $P(Y(a)=1 \mid X, Z)$ represents the true probability that intervention action $a$ successfully recovers the payment given observable context $X$ and hidden latent context $Z$.

```
Observable Context (X)              Latent State (Z)
  - Failure Type                      - Customer Willingness (Z_intent)
  - Amount (Paise)                    - Liquidity / Balance (Z_funds)
  - Payment Method                    - Irrecoverability / Abandonment
  - Customer History
  - Retry Count
  - Subscription Flag
  - Hours Since Failure
          \                                /
           \                              /
            v                            v
      +----------------------------------------+
      |  Causal Probability Model              |
      |  P(Y(a) = 1 | X, Z) for each action a  |
      +-------------------+--------------------+
                          |
                          v
      +----------------------------------------+
      |  Common Random Numbers (ξ_a ~ U(0, 1)) |
      |  Potential Outcome:                    |
      |  Y(a) = I(ξ_a <= P(Y(a) = 1 | X, Z))   |
      +----------------------------------------+
```

---

## 2. Mathematical Specification

For any payment case $i$ with observable context $X_i$, latent vector $Z_i = (Z_{\text{intent}}, Z_{\text{funds}}) \in [0, 1]^2$, and action $a \in \{\text{no\_action}, \text{retry}, \text{payment\_link}, \text{reminder}, \text{escalate}\}$, the recovery probability is defined via the logistic link:

$$P(Y_i(a) = 1 \mid X_i, Z_i) = \sigma\left( \alpha_a + \mu(X_i, Z_i) + \psi(a, X_i, Z_i) \right)$$

where $\sigma(v) = \frac{1}{1 + e^{-v}}$ is the standard sigmoid function.

### 2.1 Latent Unrecoverability & Abandonment

In real payment operations, a meaningful portion of payment failures are fundamentally unrecoverable:
- **Hard Unrecoverable Cases (~12%)**: Fraud drop, permanently closed bank account, hostile churn. For these cases, $P(Y_i(a) = 1) \le 0.0008$ across all actions. Any active intervention produces negative net revenue due to wasted fees.
- **Abandoned Transactions (~10%)**: Customer changed their mind ($Z_{\text{intent}} < 0.20$). Link and reminder response rates are near zero.

---

### 2.2 Base Context Term $\mu(X_i, Z_i)$

$$\mu(X_i, Z_i) = w_{\text{rel}} \cdot (\text{HistSuccessRate}_i - 0.7) + w_{\text{tenure}} \cdot \ln(1 + \text{TenureMonths}_i) - w_{\text{time}} \cdot \ln(1 + \text{HoursSinceFailure}_i)$$

- **Customer Reliability**: Historically loyal customers have higher underlying recovery propensity ($w_{\text{rel}} = 1.3$).
- **Tenure**: Established customer relationships improve responsiveness ($w_{\text{tenure}} = 0.18$).
- **Time Decay**: Stale failures decay significantly in recovery likelihood ($w_{\text{time}} = -0.38$).

---

### 2.3 Calibrated Action Mechanics $\psi(a, X_i, Z_i)$

Each action has distinct mechanics tailored to the root failure cause, retry state, and customer context:

#### 1. Action: `no_action` (Cost: ₹0)
- **Logit**: $\alpha_{\text{no\_action}} = -3.8 + 0.8 \cdot w_{\text{rel}} + 0.5 \cdot (Z_{\text{intent}} - 0.5)$.
- **Fresh Temporary Bonus**: $+1.8$ if `TEMPORARY_FAILURE`, `retry_count == 0`, and `hours < 3.0` (transient switch self-healing).
- **Optimality**: Becomes the strictly optimal decision for unrecoverable cases and micro-transactions where intervention cost exceeds expected gross recovery.

#### 2. Action: `retry` (Cost: ₹2.00 / 200 paise)
- **Logit**: $\alpha_{\text{retry}} = 0.3 + 1.1 \cdot w_{\text{rel}} + 0.4 \cdot w_{\text{time}}$.
- **Failure Type Modifiers**: $+1.4$ for `TEMPORARY_FAILURE`, $-2.6$ for `INSUFFICIENT_FUNDS`, $-4.8$ for `INVALID_PAYMENT_METHOD`, $-1.6$ for `UNKNOWN_FAILURE`.
- **Strong Retry Fatigue**: Penalized by $-1.45 \times \text{retry\_count}$. While highly effective on attempt 0, recovery probability falls below 15% by retry 2.
- **Amount Friction**: $-0.25 \times \ln(1 + \text{amount\_paise} / 100000)$.

#### 3. Action: `payment_link` (Cost: ₹10.00 / 1,000 paise)
- **Logit**: $\alpha_{\text{link}} = -0.5 + 0.7 \cdot w_{\text{rel}} + 3.6 \cdot (Z_{\text{intent}} - 0.5) + 0.8 \cdot (Z_{\text{funds}} - 0.5)$.
- **Failure Type Modifiers**: $+1.4$ for `INVALID_PAYMENT_METHOD` (allows entering new card/UPI), $+1.0$ for `INSUFFICIENT_FUNDS`, $-0.2$ for `TEMPORARY_FAILURE`.
- **Channel Affinity**: $+0.35$ for UPI and Card checkout.

#### 4. Action: `reminder` (Cost: ₹5.00 / 500 paise)
- **Logit**: $\alpha_{\text{reminder}} = -0.9 + 0.6 \cdot w_{\text{rel}} + 3.2 \cdot (Z_{\text{intent}} - 0.5) + 1.4 \cdot (Z_{\text{funds}} - 0.5)$.
- **Failure Type Modifiers**: $+1.3$ for `INSUFFICIENT_FUNDS`, $-2.5$ for `INVALID_PAYMENT_METHOD`, $-0.9$ for `TEMPORARY_FAILURE`.
- **Subscription Bonus**: $+0.95$ (subscription customers respond well to softer renewal nudges).

#### 5. Action: `escalate` (Cost: ₹50.00 / 5,000 paise)
- **Logit**: $\alpha_{\text{escalate}} = -0.3 + 0.5 \cdot w_{\text{rel}} + 2.2 \cdot (Z_{\text{intent}} - 0.5)$.
- **Failure Type Modifiers**: $+1.8$ for `UNKNOWN_FAILURE`, $+1.5$ for `retry_count >= 2`, $+0.5$ for `INVALID_PAYMENT_METHOD`.
- **Large Check Bonus**: $+0.55 \times \ln(1 + \text{amount\_paise} / 100000)$. The ₹50 fee is negligible on ₹15,000 invoices, making escalation highly optimal for high-ticket failures.

---

## 3. Potential Outcomes under Common Random Numbers

For every case $i$ and action $a$:
$$\xi_{i, a} \sim U(0, 1)$$
$$Y_i(a) = \mathbb{I}\left(\xi_{i, a} \le P(Y_i(a) = 1 \mid X_i, Z_i)\right)$$

---

## 4. Ground-Truth Expected Value & Action Optimality

$$\mathbb{E}[\text{Net}](a) = \lfloor P(Y(a) = 1 \mid X, Z) \cdot \text{Amount}_{\text{paise}} \rfloor - \text{Cost}_{\text{paise}}(a)$$
$$a^* = \arg\max_{a \in \mathcal{A}} \mathbb{E}[\text{Net}](a)$$
