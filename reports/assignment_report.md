# FINA 60201A - TP2

## Part One

### Question 1

The assignment asks for the quarterly series of Johnson & Johnson's debt in current liabilities (`DLCQ_t`) and long-term debt (`DLTTQ_t`) from 2024Q4 to 2025Q4, then for the daily series

```text
L_t = DLCQ_t + 0.5 * DLTTQ_t
```

I downloaded the data from WRDS using the Compustat Fundamentals Quarterly table (`comp.fundq`) for Johnson & Johnson (`GVKEY 006266`). The fields used are the exact assignment fields:

- `DLCQ_t = dlcq`
- `DLTTQ_t = dlttq`

Compustat reports these debt values in millions of USD, so I converted them to USD in the processing pipeline before computing `L_t`.

Quarterly observations obtained for Johnson & Johnson:

| Quarter | Statement date | `DLCQ_t` ($bn) | `DLTTQ_t` ($bn) | `L_t` ($bn) |
| --- | --- | ---: | ---: | ---: |
| 2024Q4 | 2024-12-31 | 5.983 | 30.651 | 21.308 |
| 2025Q1 | 2025-03-31 | 13.897 | 38.355 | 33.075 |
| 2025Q2 | 2025-06-30 | 11.526 | 39.235 | 31.143 |
| 2025Q3 | 2025-09-30 | 6.387 | 39.408 | 26.091 |
| 2025Q4 | 2025-12-31 | 8.495 | 39.438 | 28.214 |

Daily interpolation method:

- I used linear interpolation on calendar days between consecutive quarter-end statement dates.
- This produces a daily series from `2024-12-31` to `2025-12-31`, for a total of 366 observations.

Generated files:

- WRDS Compustat extract: `data/raw/compustat_jnj_debt_quarterly.csv`
- Quarterly source table: `data/raw/question1_jnj_quarterly_debt_series.csv`
- Daily interpolated series: `data/processed/question1_jnj_daily_default_point.csv`

### Question 2

I downloaded the daily equity series from WRDS using the CRSP daily stock file v2 (`crsp.dsf_v2`) for Johnson & Johnson (`PERMCO 21018`, `PERMNO 22111`). The daily market capitalization is computed as:

```text
Market Cap_t = |Price_t| * Shares Outstanding_t
```

In CRSP v2 this is equivalent to `dlycap * 1000`, because `dlycap` is reported in thousands of USD.

Question 2 output summary:

- Observation window: `2025-01-02` to `2025-12-31`
- Number of daily observations: `250`
- First market capitalization: `346.746` billion USD
- Last market capitalization: `498.604` billion USD
- Minimum market capitalization in 2025: `342.027` billion USD
- Maximum market capitalization in 2025: `515.999` billion USD

Generated file:

- CRSP market cap series: `data/raw/part1_q2_jnj_market_cap_daily.csv`

### Question 3

For the daily risk-free rate, I used the St. Louis Fed one-year zero-coupon series `THREEFY1`. I aligned this series with the CRSP market capitalization dates and with the daily default-point series from Question 1. The merged sample contains `248` common dates from `2025-01-02` to `2025-12-31`.

I then applied the standard iterative Merton procedure:

1. Start from an initial guess for asset volatility.
2. For each day, solve the Black-Scholes equity equation for the asset value.
3. Re-estimate asset volatility from the resulting daily asset returns.
4. Iterate until convergence.

Result:

- Convergence achieved in `2` iterations
- Estimated annual asset volatility at end-2025: `18.477%`
- Estimated asset value at `2025-12-31`: `525.845` billion USD

Generated files:

- FRED one-year zero-coupon series: `data/raw/part1_q3_fred_1y_zero_coupon_daily.csv`
- Aligned daily estimation inputs: `data/processed/part1_q3_aligned_inputs.csv`
- Estimated daily asset series: `data/processed/part1_q3_asset_series.csv`
- Asset-value summary: `data/processed/part1_q3_asset_summary.csv`

### Question 4

Using the Question 1 end-2025 values, I imposed:

- one-year default point = `L_t = 28.214` billion USD
- twenty-year default point = `DLTTQ_t = 39.438` billion USD

I then linearly inter- and extrapolated the default point over maturities from `0` to `30` years.

Key points on the default frontier:

- `D(0) = 27.623` billion USD
- `D(1) = 28.214` billion USD
- `D(20) = 39.438` billion USD
- `D(30) = 45.345` billion USD

Generated file:

- Default frontier: `data/processed/part1_q4_default_frontier.csv`

### Question 5

The first trading day of 2026 in the risk-free dataset is `2026-01-02`. For Question 5, the practical challenge is that the St. Louis Fed/FRED fitted zero-coupon series are directly accessible for benchmark maturities such as `1Y`, `5Y`, and `10Y`, while the complete daily `1Y-30Y` term structure needed for pricing is available from the underlying Federal Reserve Board nominal yield curve table (`SVENY01` to `SVENY30`).

To make the source choice transparent, I validated the `2026-01-02` Board curve against the St. Louis Fed/FRED fitted zero-coupon yields at overlapping benchmark maturities:

| Maturity | St. Louis Fed / FRED (%) | Board curve (%) | Difference (bps) |
| --- | ---: | ---: | ---: |
| 1Y | 3.5075 | 3.4986 | 0.8900 |
| 5Y | 3.7151 | 3.7178 | -0.2700 |
| 10Y | 4.2640 | 4.2822 | -1.8200 |

The overlap differences stay within about `1.82` basis points, so the full Board curve is a very tight proxy for the St. Louis Fed fitted zero-coupon release family when extending the pricing curve out to `30` years.

Using:

- the end-2025 asset value from Question 3,
- the end-2025 asset volatility from Question 3,
- the default frontier from Question 4,
- and the `2026-01-02` zero-coupon risk-free curve,

I priced risky zero-coupon debt under the Merton model and converted the prices into risky yields and credit spreads.

Selected maturities:

| Maturity | Risk-free yield (%) | Risky yield (%) | Credit spread (bps) |
| --- | ---: | ---: | ---: |
| 1Y | 3.4986 | 3.4986 | 0.0000 |
| 5Y | 3.7178 | 3.7178 | 0.0000 |
| 10Y | 4.2822 | 4.2822 | 0.0000 |
| 20Y | 4.9458 | 4.9458 | 0.0036 |
| 30Y | 5.1050 | 5.1052 | 0.0209 |

The Merton-implied term structure is therefore extremely tight for Johnson & Johnson, which is consistent with the large asset cushion relative to the default frontier.

Generated files:

- St. Louis Fed benchmark curve used for the Q5 source check: `data/raw/part1_q5_fred_zero_coupon_benchmarks_daily.csv`
- Full daily zero-coupon curve used for Question 5: `data/raw/part1_zero_coupon_yield_curve_daily.csv`
- Q5 risk-free source validation: `data/processed/part1_q5_risk_free_source_validation.csv`
- Credit spread term structure: `data/processed/part1_q5_credit_spread_term_structure.csv`

## Part Two

### Question 1

The assignment asks for the risk-free zero-coupon term structure on `2026-02-27`, the associated AA curve for the 11 given maturities, and the resulting credit spreads. The assignment wording references the St. Louis Fed fitted zero-coupon curve family; for the actual Nelson-Siegel-Svensson (`NSS`) parameter row, I used the Federal Reserve Board daily nominal yield-curve table because it publishes the `BETA0`, `BETA1`, `BETA2`, `BETA3`, `TAU1`, and `TAU2` parameters directly for each date.

Estimated `2026-02-27` NSS parameters:

| Date | `BETA0` | `BETA1` | `BETA2` | `BETA3` | `TAU1` | `TAU2` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-02-27 | 1.615248 | 2.172234 | -0.000000 | 10.475890 | 1.459293 | 16.868434 |

Using these parameters, I computed the risk-free zero-coupon yields

```text
zcy(t) = beta0
       + beta1 * ((1 - e^(-t/tau1)) / (t/tau1))
       + beta2 * (((1 - e^(-t/tau1)) / (t/tau1)) - e^(-t/tau1))
       + beta3 * (((1 - e^(-t/tau2)) / (t/tau2)) - e^(-t/tau2))
```

for the 11 required maturities, then formed credit spreads as `AA(t) - zcy(t)`.

| Maturity | Risk-free (%) | AA (%) | Credit spread (bps) |
| --- | ---: | ---: | ---: |
| 0.5Y | 3.6067 | 3.7600 | 15.33 |
| 1Y | 3.4862 | 3.7900 | 30.38 |
| 2Y | 3.3717 | 3.8600 | 48.83 |
| 3Y | 3.3648 | 3.9600 | 59.52 |
| 4Y | 3.4187 | 4.0800 | 66.13 |
| 5Y | 3.5060 | 4.2000 | 69.40 |
| 7Y | 3.7207 | 4.5200 | 79.93 |
| 10Y | 4.0444 | 4.8300 | 78.56 |
| 15Y | 4.4605 | 5.4200 | 95.95 |
| 20Y | 4.7087 | 5.6900 | 98.13 |
| 30Y | 4.8471 | 6.0100 | 116.29 |

The AA credit spread curve is therefore upward sloping overall, rising from about `15.33` bps at `6M` to about `116.29` bps at `30Y`.

To make the St. Louis Fed source wording explicit, I validated the `2026-02-27` FRB/NSS-implied yields against the overlapping St. Louis Fed / FRED fitted zero-coupon benchmark maturities:

| Maturity | St. Louis Fed / FRED (%) | Board NSS (%) | Difference (bps) |
| --- | ---: | ---: | ---: |
| 1Y | 3.4742 | 3.4862 | -1.20 |
| 5Y | 3.5342 | 3.5060 | 2.82 |
| 10Y | 4.0481 | 4.0444 | 0.37 |

The overlap differences stay within about `2.82` basis points, so the FRB parameter row is a very tight implementation source for the St. Louis Fed fitted zero-coupon term structure on the assignment date.

Generated files:

- NSS parameter row: `data/raw/part2_q1_nss_params_2026-02-27.csv`
- Observed AA yields: `data/raw/part2_q1_aa_yields_observed.csv`
- St. Louis Fed benchmark yields for source validation: `data/raw/part2_q1_fred_zero_coupon_benchmarks_daily.csv`
- Question 1 term structures: `data/processed/part2_q1_term_structures.csv`
- Question 1 source validation: `data/processed/part2_q1_source_validation.csv`

### Question 2

The Duffee (1999) specification is

```text
dr_t = kappa_r * (theta_r - r_t) dt + sigma_r * sqrt(r_t) dW_t
ds_t = kappa_s * (theta_s - s_t) dt + sigma_s * sqrt(s_t) dZ_t
lambda_t = alpha + beta * r_t + s_t
```

with `dW_t dZ_t = 0`.

The defaultable zero-coupon price is

```text
P^D(0,t) = E[exp(-integral_0^t (r_u + lambda_u) du)]
         = E[exp(-integral_0^t (alpha + (1 + beta) r_u + s_u) du)]
```

Because `r_t` and `s_t` are independent, define `x_t = (1 + beta) r_t`. Then `x_t` is still a CIR process with:

- the same mean-reversion speed `kappa_r`
- long-run mean `(1 + beta) theta_r`
- volatility `sigma_r * sqrt(1 + beta)`

Therefore

```text
P^D(0,t) = exp(-alpha * t) * P_CIR^x(0,t) * P_CIR^s(0,t)
```

and the defaultable zero-coupon yield is

```text
Y(t) = -(1/t) * ln(P^D(0,t))
     = alpha
       + y_CIR(t; (1 + beta) r_0, kappa_r, (1 + beta) theta_r, sigma_r * sqrt(1 + beta))
       + y_CIR(t; s_0, kappa_s, theta_s, sigma_s)
```

This is the pricing formula I used for the calibration in Question 3 and for the non-callable bond valuation in Question 5.

### Question 3

I calibrated the model in two steps exactly as requested.

Step 1: fit the CIR risk-free term structure to the 11 `2026-02-27` risk-free zero-coupon yields.

Step 2: holding those risk-free parameters fixed, fit the Duffee defaultable-yield curve to the 11 observed AA yields.

Calibrated parameters:

| Block | Parameter | Value |
| --- | --- | ---: |
| Risk-free CIR | `r_0` | 0.032816 |
| Risk-free CIR | `kappa_r` | 0.036991 |
| Risk-free CIR | `theta_r` | 0.077737 |
| Risk-free CIR | `sigma_r` | 0.017775 |
| Risk-free CIR | RMSE | 15.3264 bps |
| Duffee credit block | `s_0` | 0.000563 |
| Duffee credit block | `kappa_s` | 0.125016 |
| Duffee credit block | `theta_s` | 0.012993 |
| Duffee credit block | `sigma_s` | 0.056106 |
| Duffee credit block | `alpha` | 0.002384 |
| Duffee credit block | `beta` | 0.001503 |
| Duffee credit block | RMSE | 8.5387 bps |

Selected fitted values:

| Maturity | Observed AA (%) | Fitted AA (%) | Error (bps) |
| --- | ---: | ---: | ---: |
| 1Y | 3.7900 | 3.7378 | -5.22 |
| 5Y | 4.2000 | 4.2855 | 8.55 |
| 10Y | 4.8300 | 4.8292 | -0.08 |
| 20Y | 5.6900 | 5.6076 | -8.24 |
| 30Y | 6.0100 | 6.1377 | 12.77 |

The credit block fit is materially tighter than the risk-free CIR fit, which is expected because a one-factor CIR curve is only a parsimonious approximation to the `NSS` shape. The fitted Duffee curve remains smooth and economically reasonable from `0` to `30` years.

Generated files:

- Risk-free CIR node fit: `data/processed/part2_q3_risk_free_cir_fit.csv`
- Duffee node fit: `data/processed/part2_q3_duffee_fit.csv`
- Continuous fitted curve from `0` to `30Y`: `data/processed/part2_q3_duffee_curve.csv`
- Calibration parameters: `data/processed/part2_q3_parameters.csv`

### Question 4

I priced the AA callable corporate bond with the required two-dimensional explicit finite-difference method using the state variables `(r_t, s_t)` and the Duffee discount-and-default rate

```text
q(r, s) = alpha + (1 + beta) r + s
```

Bond characteristics:

- Face value: `1,000,000`
- Maturity: `5` years
- Coupon rate: `4%`
- Coupon frequency: semiannual
- Call feature: callable at par at any time

Numerical setup:

- `81 x 81` state grid in `(r, s)`
- `r_max = 20%`
- `s_max = 20%`
- `2,782` time steps
- `dt = 0.001797` years

I imposed the callability cap at every time step. Between coupon dates, the call price is `par = 1,000,000`. On coupon dates, I used the more defensible cum-coupon exercise convention: the issuer can redeem at `par + coupon = 1,020,000`, which is equivalent to paying the current coupon and then calling the bond at par.

Results:

- Callable bond price: `968,946.18` USD
- Matched non-callable bond closed-form price: `986,209.64` USD
- Non-callable finite-difference validation price: `986,112.65` USD
- Finite-difference minus closed-form validation error: `-97.00` USD

The finite-difference validation error is less than `0.01%` of face value, which is sufficiently tight for the assignment.

Generated file:

- Bond valuation summary: `data/processed/part2_q4_bond_valuation.csv`

### Question 5

I computed the bond-equivalent semiannual YTM implied by:

- the callable-bond finite-difference price from Question 4
- the matched non-callable closed-form price from the Duffee term structure

Results:

| Bond | Price (USD) | YTM (%) |
| --- | ---: | ---: |
| Callable | 968,946.18 | 4.7042 |
| Non-callable | 986,209.64 | 4.3095 |

Comparison:

- Callable bond price discount relative to the non-callable bond: `17,263.46` USD
- Callable bond YTM pickup: `39.47` bps

The higher YTM on the callable bond is economically consistent with the embedded issuer call option: the option lowers the bond price and raises the yield required by investors.

Generated file:

- YTM comparison: `data/processed/part2_q5_ytm_comparison.csv`
