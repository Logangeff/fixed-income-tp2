from __future__ import annotations

import io
import math
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from scipy.optimize import brentq, differential_evolution


matplotlib.use("Agg")
import matplotlib.pyplot as plt


FED_NOMINAL_YIELD_CURVE_URL = "https://www.federalreserve.gov/data/yield-curve-tables/feds200628.csv"
FED_USER_AGENT = "fixed-income-tp2/1.0"
PART_TWO_VALUATION_DATE = pd.Timestamp("2026-02-27")

PART_TWO_NSS_PARAMS_PATH = Path("data/raw/part2_q1_nss_params_2026-02-27.csv")
PART_TWO_AA_YIELDS_PATH = Path("data/raw/part2_q1_aa_yields_observed.csv")
PART_TWO_FRED_Q1_BENCHMARK_PATH = Path("data/raw/part2_q1_fred_zero_coupon_benchmarks_daily.csv")
PART_TWO_TERM_STRUCTURES_PATH = Path("data/processed/part2_q1_term_structures.csv")
PART_TWO_Q1_VALIDATION_PATH = Path("data/processed/part2_q1_source_validation.csv")
PART_TWO_RISK_FREE_FIT_PATH = Path("data/processed/part2_q3_risk_free_cir_fit.csv")
PART_TWO_DUFFEE_FIT_PATH = Path("data/processed/part2_q3_duffee_fit.csv")
PART_TWO_DUFFEE_CURVE_PATH = Path("data/processed/part2_q3_duffee_curve.csv")
PART_TWO_PARAMETERS_PATH = Path("data/processed/part2_q3_parameters.csv")
PART_TWO_VALUATION_PATH = Path("data/processed/part2_q4_bond_valuation.csv")
PART_TWO_YTM_PATH = Path("data/processed/part2_q5_ytm_comparison.csv")

FIGURE_Q1_PATH = Path("reports/figures/part2_q1_term_structures.png")
FIGURE_Q3_PATH = Path("reports/figures/part2_q3_duffee_fit.png")

AA_MATURITY_YEARS = np.array([0.5, 1, 2, 3, 4, 5, 7, 10, 15, 20, 30], dtype=float)
AA_YIELD_PCT = np.array([3.76, 3.79, 3.86, 3.96, 4.08, 4.20, 4.52, 4.83, 5.42, 5.69, 6.01], dtype=float)
FRED_Q1_BENCHMARK_SERIES = {
    "THREEFY1": "fred_zero_coupon_1y_pct",
    "THREEFY5": "fred_zero_coupon_5y_pct",
    "THREEFY10": "fred_zero_coupon_10y_pct",
}


@dataclass(frozen=True)
class RiskFreeCirCalibration:
    r0: float
    kappa_r: float
    theta_r: float
    sigma_r: float
    rmse_bps: float


@dataclass(frozen=True)
class DuffeeCalibration:
    s0: float
    kappa_s: float
    theta_s: float
    sigma_s: float
    alpha: float
    beta: float
    rmse_bps: float


@dataclass(frozen=True)
class BondValuationResult:
    callable_price: float
    noncallable_price_closed_form: float
    noncallable_price_fd: float
    callable_ytm: float
    noncallable_ytm: float
    price_difference_usd: float
    ytm_difference_bps: float
    grid_r_points: int
    grid_s_points: int
    time_steps: int
    dt_years: float
    r_max: float
    s_max: float


def _mkdir_for(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _cir_a_b(maturity_years: np.ndarray | float, kappa: float, theta: float, sigma: float) -> tuple[np.ndarray, np.ndarray]:
    maturity = np.asarray(maturity_years, dtype=float)
    a = np.ones_like(maturity)
    b = np.zeros_like(maturity)

    mask = maturity > 1e-12
    if not np.any(mask):
        return a, b

    t = maturity[mask]
    gamma = math.sqrt(kappa * kappa + 2.0 * sigma * sigma)
    exp_gamma_t = np.exp(gamma * t)
    denominator = (gamma + kappa) * (exp_gamma_t - 1.0) + 2.0 * gamma

    b[mask] = 2.0 * (exp_gamma_t - 1.0) / denominator
    a[mask] = (
        2.0 * gamma * np.exp((kappa + gamma) * t / 2.0) / denominator
    ) ** (2.0 * kappa * theta / (sigma * sigma))
    return a, b


def cir_zero_coupon_price(
    maturity_years: np.ndarray | float,
    x0: float,
    kappa: float,
    theta: float,
    sigma: float,
) -> np.ndarray:
    maturity = np.asarray(maturity_years, dtype=float)
    a, b = _cir_a_b(maturity, kappa, theta, sigma)
    return a * np.exp(-b * x0)


def cir_zero_coupon_yield(
    maturity_years: np.ndarray | float,
    x0: float,
    kappa: float,
    theta: float,
    sigma: float,
) -> np.ndarray:
    maturity = np.asarray(maturity_years, dtype=float)
    yields = np.empty_like(maturity)

    near_zero_mask = maturity <= 1e-12
    yields[near_zero_mask] = x0

    positive_mask = ~near_zero_mask
    if np.any(positive_mask):
        positive_t = maturity[positive_mask]
        prices = cir_zero_coupon_price(positive_t, x0, kappa, theta, sigma)
        yields[positive_mask] = -np.log(prices) / positive_t

    return yields


def nss_zero_coupon_yield(
    maturity_years: np.ndarray | float,
    beta0: float,
    beta1: float,
    beta2: float,
    beta3: float,
    tau1: float,
    tau2: float,
) -> np.ndarray:
    maturity = np.asarray(maturity_years, dtype=float)
    x1 = maturity / tau1
    x2 = maturity / tau2

    loading1 = np.divide(1.0 - np.exp(-x1), x1, out=np.ones_like(maturity), where=np.abs(x1) > 1e-12)
    loading2 = loading1 - np.exp(-x1)
    loading3 = np.divide(1.0 - np.exp(-x2), x2, out=np.ones_like(maturity), where=np.abs(x2) > 1e-12) - np.exp(-x2)

    return (beta0 + beta1 * loading1 + beta2 * loading2 + beta3 * loading3) / 100.0


def fetch_nss_parameters(project_root: Path) -> pd.DataFrame:
    output_path = project_root / PART_TWO_NSS_PARAMS_PATH
    _mkdir_for(output_path)

    request = urllib.request.Request(
        FED_NOMINAL_YIELD_CURVE_URL,
        headers={"User-Agent": FED_USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        text = response.read().decode("utf-8", errors="ignore")

    df = pd.read_csv(io.StringIO(text), skiprows=9)
    df["Date"] = pd.to_datetime(df["Date"])

    row = df.loc[df["Date"] == PART_TWO_VALUATION_DATE]
    if row.empty:
        raise RuntimeError("The Federal Reserve nominal yield curve table does not contain 2026-02-27.")

    selected = row[["Date", "BETA0", "BETA1", "BETA2", "BETA3", "TAU1", "TAU2"]].copy()
    selected = selected.rename(columns={"Date": "date"})
    selected.to_csv(output_path, index=False)
    return selected


def save_observed_aa_yields(project_root: Path) -> pd.DataFrame:
    output_path = project_root / PART_TWO_AA_YIELDS_PATH
    _mkdir_for(output_path)

    df = pd.DataFrame(
        {
            "maturity_years": AA_MATURITY_YEARS,
            "aa_yield_pct": AA_YIELD_PCT,
            "aa_yield_decimal": AA_YIELD_PCT / 100.0,
        }
    )
    df.to_csv(output_path, index=False)
    return df


def fetch_fred_q1_benchmarks(project_root: Path) -> pd.DataFrame:
    output_path = project_root / PART_TWO_FRED_Q1_BENCHMARK_PATH
    _mkdir_for(output_path)

    merged = None
    for series_id, renamed_column in FRED_Q1_BENCHMARK_SERIES.items():
        df = pd.read_csv(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}")
        df = df.rename(columns={"observation_date": "date", series_id: renamed_column})
        df["date"] = pd.to_datetime(df["date"])
        df[renamed_column] = pd.to_numeric(df[renamed_column], errors="coerce")
        df = df.loc[df["date"].between("2026-02-01", "2026-02-28")].copy()

        if merged is None:
            merged = df
        else:
            merged = merged.merge(df, on="date", how="outer")

    if merged is None:
        raise RuntimeError("Failed to download the Part Two FRED benchmark zero-coupon series.")

    merged = merged.sort_values("date")
    merged.to_csv(output_path, index=False)
    return merged


def build_q1_term_structures(
    project_root: Path,
    nss_parameters: pd.DataFrame,
    observed_aa_yields: pd.DataFrame,
) -> pd.DataFrame:
    output_path = project_root / PART_TWO_TERM_STRUCTURES_PATH
    _mkdir_for(output_path)

    params = nss_parameters.iloc[0]
    maturities = observed_aa_yields["maturity_years"].to_numpy(dtype=float)
    risk_free_decimal = nss_zero_coupon_yield(
        maturities,
        beta0=float(params["BETA0"]),
        beta1=float(params["BETA1"]),
        beta2=float(params["BETA2"]),
        beta3=float(params["BETA3"]),
        tau1=float(params["TAU1"]),
        tau2=float(params["TAU2"]),
    )

    result = observed_aa_yields.copy()
    result["valuation_date"] = PART_TWO_VALUATION_DATE.strftime("%Y-%m-%d")
    result["risk_free_yield_decimal"] = risk_free_decimal
    result["risk_free_yield_pct"] = risk_free_decimal * 100.0
    result["credit_spread_decimal"] = result["aa_yield_decimal"] - result["risk_free_yield_decimal"]
    result["credit_spread_pct"] = result["credit_spread_decimal"] * 100.0
    result["credit_spread_bps"] = result["credit_spread_decimal"] * 10_000.0
    result = result[
        [
            "valuation_date",
            "maturity_years",
            "risk_free_yield_pct",
            "aa_yield_pct",
            "credit_spread_pct",
            "credit_spread_bps",
            "risk_free_yield_decimal",
            "aa_yield_decimal",
            "credit_spread_decimal",
        ]
    ]
    result.to_csv(output_path, index=False)
    return result


def build_q1_source_validation(project_root: Path, term_structures: pd.DataFrame, fred_benchmarks: pd.DataFrame) -> pd.DataFrame:
    output_path = project_root / PART_TWO_Q1_VALIDATION_PATH
    _mkdir_for(output_path)

    benchmark_row = fred_benchmarks.loc[fred_benchmarks["date"] == PART_TWO_VALUATION_DATE]
    if benchmark_row.empty:
        raise RuntimeError("The FRED benchmark series do not contain 2026-02-27.")

    row = benchmark_row.iloc[0]
    term_lookup = term_structures.set_index("maturity_years")
    validation = pd.DataFrame(
        [
            {
                "date": PART_TWO_VALUATION_DATE.strftime("%Y-%m-%d"),
                "maturity_years": 1.0,
                "stl_fed_fred_yield_pct": float(row["fred_zero_coupon_1y_pct"]),
                "board_nss_yield_pct": float(term_lookup.loc[1.0, "risk_free_yield_pct"]),
            },
            {
                "date": PART_TWO_VALUATION_DATE.strftime("%Y-%m-%d"),
                "maturity_years": 5.0,
                "stl_fed_fred_yield_pct": float(row["fred_zero_coupon_5y_pct"]),
                "board_nss_yield_pct": float(term_lookup.loc[5.0, "risk_free_yield_pct"]),
            },
            {
                "date": PART_TWO_VALUATION_DATE.strftime("%Y-%m-%d"),
                "maturity_years": 10.0,
                "stl_fed_fred_yield_pct": float(row["fred_zero_coupon_10y_pct"]),
                "board_nss_yield_pct": float(term_lookup.loc[10.0, "risk_free_yield_pct"]),
            },
        ]
    )
    validation["difference_bps"] = (
        (validation["stl_fed_fred_yield_pct"] - validation["board_nss_yield_pct"]) * 100.0
    )
    validation.to_csv(output_path, index=False)
    return validation


def _feller_penalty(kappa: float, theta: float, sigma: float) -> float:
    gap = sigma * sigma - 2.0 * kappa * theta
    if gap <= 0.0:
        return 0.0
    return 100.0 * gap * gap


def calibrate_risk_free_cir(project_root: Path, term_structures: pd.DataFrame) -> tuple[pd.DataFrame, RiskFreeCirCalibration]:
    output_path = project_root / PART_TWO_RISK_FREE_FIT_PATH
    _mkdir_for(output_path)

    maturities = term_structures["maturity_years"].to_numpy(dtype=float)
    observed = term_structures["risk_free_yield_decimal"].to_numpy(dtype=float)

    def objective(params: np.ndarray) -> float:
        r0, kappa_r, theta_r, sigma_r = params
        fitted = cir_zero_coupon_yield(maturities, r0, kappa_r, theta_r, sigma_r)
        mse = float(np.mean((fitted - observed) ** 2))
        return mse + _feller_penalty(kappa_r, theta_r, sigma_r)

    bounds = [
        (0.01, 0.08),
        (0.02, 2.0),
        (0.03, 0.12),
        (0.005, 0.10),
    ]
    result = differential_evolution(objective, bounds=bounds, seed=2, maxiter=300, polish=False)
    r0, kappa_r, theta_r, sigma_r = result.x

    fitted = cir_zero_coupon_yield(maturities, r0, kappa_r, theta_r, sigma_r)
    fit_df = pd.DataFrame(
        {
            "maturity_years": maturities,
            "observed_risk_free_yield_pct": observed * 100.0,
            "fitted_risk_free_yield_pct": fitted * 100.0,
            "error_bps": (fitted - observed) * 10_000.0,
        }
    )
    fit_df.to_csv(output_path, index=False)

    rmse_bps = float(np.sqrt(np.mean((fitted - observed) ** 2)) * 10_000.0)
    calibration = RiskFreeCirCalibration(
        r0=float(r0),
        kappa_r=float(kappa_r),
        theta_r=float(theta_r),
        sigma_r=float(sigma_r),
        rmse_bps=rmse_bps,
    )
    return fit_df, calibration


def defaultable_zero_coupon_price(
    maturity_years: np.ndarray | float,
    risk_free: RiskFreeCirCalibration,
    duffee: DuffeeCalibration,
) -> np.ndarray:
    maturity = np.asarray(maturity_years, dtype=float)
    transformed_short_rate = (1.0 + duffee.beta) * risk_free.r0
    transformed_theta = (1.0 + duffee.beta) * risk_free.theta_r
    transformed_sigma = risk_free.sigma_r * math.sqrt(1.0 + duffee.beta)

    risk_free_component = cir_zero_coupon_price(
        maturity,
        transformed_short_rate,
        risk_free.kappa_r,
        transformed_theta,
        transformed_sigma,
    )
    spread_component = cir_zero_coupon_price(
        maturity,
        duffee.s0,
        duffee.kappa_s,
        duffee.theta_s,
        duffee.sigma_s,
    )
    return np.exp(-duffee.alpha * maturity) * risk_free_component * spread_component


def defaultable_zero_coupon_yield(
    maturity_years: np.ndarray | float,
    risk_free: RiskFreeCirCalibration,
    duffee: DuffeeCalibration,
) -> np.ndarray:
    maturity = np.asarray(maturity_years, dtype=float)
    yields = np.empty_like(maturity)

    near_zero_mask = maturity <= 1e-12
    yields[near_zero_mask] = duffee.alpha + (1.0 + duffee.beta) * risk_free.r0 + duffee.s0

    positive_mask = ~near_zero_mask
    if np.any(positive_mask):
        t = maturity[positive_mask]
        prices = defaultable_zero_coupon_price(t, risk_free, duffee)
        yields[positive_mask] = -np.log(prices) / t

    return yields


def calibrate_duffee_model(
    project_root: Path,
    term_structures: pd.DataFrame,
    risk_free: RiskFreeCirCalibration,
) -> tuple[pd.DataFrame, pd.DataFrame, DuffeeCalibration]:
    fit_output_path = project_root / PART_TWO_DUFFEE_FIT_PATH
    curve_output_path = project_root / PART_TWO_DUFFEE_CURVE_PATH
    parameters_output_path = project_root / PART_TWO_PARAMETERS_PATH
    _mkdir_for(fit_output_path)
    _mkdir_for(curve_output_path)
    _mkdir_for(parameters_output_path)

    maturities = term_structures["maturity_years"].to_numpy(dtype=float)
    observed_aa = term_structures["aa_yield_decimal"].to_numpy(dtype=float)

    def objective(params: np.ndarray) -> float:
        s0, kappa_s, theta_s, sigma_s, alpha, beta = params
        candidate = DuffeeCalibration(
            s0=float(s0),
            kappa_s=float(kappa_s),
            theta_s=float(theta_s),
            sigma_s=float(sigma_s),
            alpha=float(alpha),
            beta=float(beta),
            rmse_bps=0.0,
        )
        fitted = defaultable_zero_coupon_yield(maturities, risk_free, candidate)
        mse = float(np.mean((fitted - observed_aa) ** 2))
        return mse + _feller_penalty(kappa_s, theta_s, sigma_s)

    bounds = [
        (1e-6, 0.10),
        (0.001, 10.0),
        (1e-6, 0.10),
        (0.0001, 0.50),
        (0.0, 0.05),
        (0.0, 0.20),
    ]
    result = differential_evolution(objective, bounds=bounds, seed=2, maxiter=300, polish=False)
    s0, kappa_s, theta_s, sigma_s, alpha, beta = result.x

    fitted_duffee = DuffeeCalibration(
        s0=float(s0),
        kappa_s=float(kappa_s),
        theta_s=float(theta_s),
        sigma_s=float(sigma_s),
        alpha=float(alpha),
        beta=float(beta),
        rmse_bps=0.0,
    )

    fitted_aa = defaultable_zero_coupon_yield(maturities, risk_free, fitted_duffee)
    fitted_risk_free = cir_zero_coupon_yield(
        maturities,
        risk_free.r0,
        risk_free.kappa_r,
        risk_free.theta_r,
        risk_free.sigma_r,
    )
    rmse_bps = float(np.sqrt(np.mean((fitted_aa - observed_aa) ** 2)) * 10_000.0)
    fitted_duffee = DuffeeCalibration(
        s0=fitted_duffee.s0,
        kappa_s=fitted_duffee.kappa_s,
        theta_s=fitted_duffee.theta_s,
        sigma_s=fitted_duffee.sigma_s,
        alpha=fitted_duffee.alpha,
        beta=fitted_duffee.beta,
        rmse_bps=rmse_bps,
    )

    fit_df = pd.DataFrame(
        {
            "maturity_years": maturities,
            "observed_aa_yield_pct": observed_aa * 100.0,
            "fitted_aa_yield_pct": fitted_aa * 100.0,
            "observed_credit_spread_bps": (observed_aa - term_structures["risk_free_yield_decimal"].to_numpy(dtype=float)) * 10_000.0,
            "fitted_credit_spread_bps": (fitted_aa - fitted_risk_free) * 10_000.0,
            "error_bps": (fitted_aa - observed_aa) * 10_000.0,
        }
    )
    fit_df.to_csv(fit_output_path, index=False)

    curve_grid = np.linspace(0.0, 30.0, 601)
    continuous_curve = pd.DataFrame(
        {
            "maturity_years": curve_grid,
            "fitted_risk_free_yield_pct": cir_zero_coupon_yield(
                curve_grid,
                risk_free.r0,
                risk_free.kappa_r,
                risk_free.theta_r,
                risk_free.sigma_r,
            )
            * 100.0,
            "fitted_duffee_yield_pct": defaultable_zero_coupon_yield(curve_grid, risk_free, fitted_duffee) * 100.0,
        }
    )
    continuous_curve["fitted_credit_spread_bps"] = (
        continuous_curve["fitted_duffee_yield_pct"] - continuous_curve["fitted_risk_free_yield_pct"]
    ) * 100.0
    continuous_curve.to_csv(curve_output_path, index=False)

    parameter_df = pd.DataFrame(
        [
            {
                "valuation_date": PART_TWO_VALUATION_DATE.strftime("%Y-%m-%d"),
                "risk_free_r0": risk_free.r0,
                "risk_free_kappa_r": risk_free.kappa_r,
                "risk_free_theta_r": risk_free.theta_r,
                "risk_free_sigma_r": risk_free.sigma_r,
                "risk_free_rmse_bps": risk_free.rmse_bps,
                "duffee_s0": fitted_duffee.s0,
                "duffee_kappa_s": fitted_duffee.kappa_s,
                "duffee_theta_s": fitted_duffee.theta_s,
                "duffee_sigma_s": fitted_duffee.sigma_s,
                "duffee_alpha": fitted_duffee.alpha,
                "duffee_beta": fitted_duffee.beta,
                "duffee_rmse_bps": fitted_duffee.rmse_bps,
            }
        ]
    )
    parameter_df.to_csv(parameters_output_path, index=False)

    return fit_df, continuous_curve, fitted_duffee


def price_noncallable_bond_closed_form(
    risk_free: RiskFreeCirCalibration,
    duffee: DuffeeCalibration,
    face_value: float,
    coupon_rate: float,
    maturity_years: float,
    coupon_frequency: int,
) -> float:
    coupon_amount = face_value * coupon_rate / coupon_frequency
    payment_times = np.arange(1, int(round(maturity_years * coupon_frequency)) + 1, dtype=float) / coupon_frequency
    discount_factors = defaultable_zero_coupon_price(payment_times, risk_free, duffee)
    return float(np.sum(coupon_amount * discount_factors) + face_value * discount_factors[-1])


def _bilinear_grid_value(
    grid_values: np.ndarray,
    r_value: float,
    s_value: float,
    dr: float,
    ds: float,
) -> float:
    nr, ns = grid_values.shape
    r_position = float(np.clip(r_value / dr, 0.0, nr - 1))
    s_position = float(np.clip(s_value / ds, 0.0, ns - 1))

    i0 = int(math.floor(r_position))
    j0 = int(math.floor(s_position))
    i1 = min(i0 + 1, nr - 1)
    j1 = min(j0 + 1, ns - 1)

    wr = r_position - i0
    ws = s_position - j0

    return float(
        (1.0 - wr) * (1.0 - ws) * grid_values[i0, j0]
        + wr * (1.0 - ws) * grid_values[i1, j0]
        + (1.0 - wr) * ws * grid_values[i0, j1]
        + wr * ws * grid_values[i1, j1]
    )


def price_callable_bond_explicit_fd(
    risk_free: RiskFreeCirCalibration,
    duffee: DuffeeCalibration,
    face_value: float,
    coupon_rate: float,
    maturity_years: float,
    coupon_frequency: int,
    nr: int = 81,
    ns: int = 81,
    r_max: float = 0.20,
    s_max: float = 0.20,
    stability_fraction: float = 0.20,
) -> tuple[float, float, int, float]:
    coupon_amount = face_value * coupon_rate / coupon_frequency
    payment_times = np.arange(1, int(round(maturity_years * coupon_frequency)) + 1, dtype=float) / coupon_frequency

    dr = r_max / (nr - 1)
    ds = s_max / (ns - 1)
    r_grid = np.linspace(0.0, r_max, nr)
    s_grid = np.linspace(0.0, s_max, ns)
    r_mesh, s_mesh = np.meshgrid(r_grid, s_grid, indexing="ij")

    variance_r = (risk_free.sigma_r**2) * np.maximum(r_mesh, 0.0)
    variance_s = (duffee.sigma_s**2) * np.maximum(s_mesh, 0.0)
    discount_rate = duffee.alpha + (1.0 + duffee.beta) * r_mesh + s_mesh

    stability_scale = float(np.max(variance_r / (dr * dr) + variance_s / (ds * ds) + discount_rate))
    dt = stability_fraction / stability_scale
    time_steps = int(math.ceil(maturity_years / dt))
    dt = maturity_years / time_steps

    coupon_step_indices = {
        int(round(payment_time / dt))
        for payment_time in payment_times[:-1]
    }

    def apply_boundaries(values: np.ndarray, callable_flag: bool, call_cap_value: float) -> np.ndarray:
        if callable_flag:
            values[0, :] = np.minimum(call_cap_value, np.maximum(0.0, 2.0 * values[1, :] - values[2, :]))
            values[:, 0] = np.minimum(call_cap_value, np.maximum(0.0, 2.0 * values[:, 1] - values[:, 2]))
            values[0, 0] = min(call_cap_value, max(0.0, 0.5 * (values[1, 0] + values[0, 1])))
        else:
            values[0, :] = np.maximum(0.0, 2.0 * values[1, :] - values[2, :])
            values[:, 0] = np.maximum(0.0, 2.0 * values[:, 1] - values[:, 2])
            values[0, 0] = max(0.0, 0.5 * (values[1, 0] + values[0, 1]))

        values[-1, :] = 0.0
        values[:, -1] = 0.0
        return values

    def solve_grid(callable_flag: bool) -> float:
        values = np.full((nr, ns), face_value + coupon_amount, dtype=float)
        values = apply_boundaries(values, callable_flag, face_value + coupon_amount)

        for step in range(time_steps - 1, -1, -1):
            updated = values.copy()
            interior = values[1:-1, 1:-1]

            d_v_dr = (values[2:, 1:-1] - values[:-2, 1:-1]) / (2.0 * dr)
            d2_v_dr2 = (values[2:, 1:-1] - 2.0 * interior + values[:-2, 1:-1]) / (dr * dr)
            d_v_ds = (values[1:-1, 2:] - values[1:-1, :-2]) / (2.0 * ds)
            d2_v_ds2 = (values[1:-1, 2:] - 2.0 * interior + values[1:-1, :-2]) / (ds * ds)

            r_state = r_mesh[1:-1, 1:-1]
            s_state = s_mesh[1:-1, 1:-1]
            drift_r = risk_free.kappa_r * (risk_free.theta_r - r_state)
            drift_s = duffee.kappa_s * (duffee.theta_s - s_state)
            variance_r_state = (risk_free.sigma_r**2) * np.maximum(r_state, 0.0)
            variance_s_state = (duffee.sigma_s**2) * np.maximum(s_state, 0.0)
            discount_state = duffee.alpha + (1.0 + duffee.beta) * r_state + s_state

            generator_values = (
                0.5 * variance_r_state * d2_v_dr2
                + drift_r * d_v_dr
                + 0.5 * variance_s_state * d2_v_ds2
                + drift_s * d_v_ds
                - discount_state * interior
            )
            updated[1:-1, 1:-1] = interior + dt * generator_values

            call_cap_value = face_value
            if step in coupon_step_indices:
                updated += coupon_amount
                call_cap_value = face_value + coupon_amount

            updated = np.maximum(updated, 0.0)
            if callable_flag:
                updated = np.minimum(updated, call_cap_value)

            values = apply_boundaries(updated, callable_flag, call_cap_value)

        return _bilinear_grid_value(values, risk_free.r0, duffee.s0, dr, ds)

    callable_price = solve_grid(callable_flag=True)
    noncallable_fd_price = solve_grid(callable_flag=False)
    return callable_price, noncallable_fd_price, time_steps, dt


def solve_bond_ytm(price: float, face_value: float, coupon_rate: float, maturity_years: float, coupon_frequency: int) -> float:
    coupon_amount = face_value * coupon_rate / coupon_frequency
    payment_times = np.arange(1, int(round(maturity_years * coupon_frequency)) + 1, dtype=float) / coupon_frequency
    cashflows = np.full(payment_times.shape, coupon_amount, dtype=float)
    cashflows[-1] += face_value

    def objective(yield_to_maturity: float) -> float:
        per_period = yield_to_maturity / coupon_frequency
        discount_factors = (1.0 + per_period) ** (coupon_frequency * payment_times)
        return float(np.sum(cashflows / discount_factors) - price)

    return float(brentq(objective, 1e-8, 0.50))


def value_callable_and_noncallable_bonds(
    project_root: Path,
    risk_free: RiskFreeCirCalibration,
    duffee: DuffeeCalibration,
) -> BondValuationResult:
    valuation_output_path = project_root / PART_TWO_VALUATION_PATH
    ytm_output_path = project_root / PART_TWO_YTM_PATH
    _mkdir_for(valuation_output_path)
    _mkdir_for(ytm_output_path)

    face_value = 1_000_000.0
    coupon_rate = 0.04
    maturity_years = 5.0
    coupon_frequency = 2

    noncallable_price_closed_form = price_noncallable_bond_closed_form(
        risk_free=risk_free,
        duffee=duffee,
        face_value=face_value,
        coupon_rate=coupon_rate,
        maturity_years=maturity_years,
        coupon_frequency=coupon_frequency,
    )
    callable_price, noncallable_price_fd, time_steps, dt = price_callable_bond_explicit_fd(
        risk_free=risk_free,
        duffee=duffee,
        face_value=face_value,
        coupon_rate=coupon_rate,
        maturity_years=maturity_years,
        coupon_frequency=coupon_frequency,
    )

    callable_ytm = solve_bond_ytm(callable_price, face_value, coupon_rate, maturity_years, coupon_frequency)
    noncallable_ytm = solve_bond_ytm(noncallable_price_closed_form, face_value, coupon_rate, maturity_years, coupon_frequency)

    result = BondValuationResult(
        callable_price=float(callable_price),
        noncallable_price_closed_form=float(noncallable_price_closed_form),
        noncallable_price_fd=float(noncallable_price_fd),
        callable_ytm=float(callable_ytm),
        noncallable_ytm=float(noncallable_ytm),
        price_difference_usd=float(noncallable_price_closed_form - callable_price),
        ytm_difference_bps=float((callable_ytm - noncallable_ytm) * 10_000.0),
        grid_r_points=81,
        grid_s_points=81,
        time_steps=time_steps,
        dt_years=float(dt),
        r_max=0.20,
        s_max=0.20,
    )

    valuation_df = pd.DataFrame(
        [
            {
                "valuation_date": PART_TWO_VALUATION_DATE.strftime("%Y-%m-%d"),
                "face_value_usd": face_value,
                "coupon_rate": coupon_rate,
                "coupon_frequency": coupon_frequency,
                "maturity_years": maturity_years,
                "callable_price_usd": result.callable_price,
                "noncallable_price_closed_form_usd": result.noncallable_price_closed_form,
                "noncallable_price_fd_usd": result.noncallable_price_fd,
                "fd_minus_closed_form_usd": result.noncallable_price_fd - result.noncallable_price_closed_form,
                "non_coupon_call_cap_usd": face_value,
                "coupon_date_call_cap_usd": face_value + (face_value * coupon_rate / coupon_frequency),
                "grid_r_points": result.grid_r_points,
                "grid_s_points": result.grid_s_points,
                "time_steps": result.time_steps,
                "dt_years": result.dt_years,
                "r_max": result.r_max,
                "s_max": result.s_max,
            }
        ]
    )
    valuation_df.to_csv(valuation_output_path, index=False)

    ytm_df = pd.DataFrame(
        [
            {
                "valuation_date": PART_TWO_VALUATION_DATE.strftime("%Y-%m-%d"),
                "callable_price_usd": result.callable_price,
                "callable_ytm_decimal": result.callable_ytm,
                "callable_ytm_pct": result.callable_ytm * 100.0,
                "noncallable_price_usd": result.noncallable_price_closed_form,
                "noncallable_ytm_decimal": result.noncallable_ytm,
                "noncallable_ytm_pct": result.noncallable_ytm * 100.0,
                "ytm_pickup_bps": result.ytm_difference_bps,
                "price_discount_usd": result.price_difference_usd,
            }
        ]
    )
    ytm_df.to_csv(ytm_output_path, index=False)
    return result


def _save_q1_figure(project_root: Path, term_structures: pd.DataFrame) -> None:
    output_path = project_root / FIGURE_Q1_PATH
    _mkdir_for(output_path)

    fig, ax1 = plt.subplots(figsize=(10, 5))
    ax1.plot(
        term_structures["maturity_years"],
        term_structures["risk_free_yield_pct"],
        marker="o",
        linewidth=1.6,
        label="Risk-free zero-coupon yield",
    )
    ax1.plot(
        term_structures["maturity_years"],
        term_structures["aa_yield_pct"],
        marker="o",
        linewidth=1.6,
        label="Observed AA yield",
    )
    ax1.set_xlabel("Maturity (years)")
    ax1.set_ylabel("Yield (%)")
    ax1.legend(loc="upper left")

    ax2 = ax1.twinx()
    ax2.bar(
        term_structures["maturity_years"],
        term_structures["credit_spread_bps"],
        width=0.6,
        alpha=0.20,
        color="black",
        label="Credit spread",
    )
    ax2.set_ylabel("Credit spread (bps)")
    ax2.legend(loc="upper right")

    plt.title("Part Two Question 1: Risk-Free Curve, AA Curve, and Credit Spreads")
    plt.tight_layout()
    plt.savefig(output_path, dpi=180)
    plt.close()


def _save_q3_figure(
    project_root: Path,
    term_structures: pd.DataFrame,
    continuous_curve: pd.DataFrame,
    fit_df: pd.DataFrame,
) -> None:
    output_path = project_root / FIGURE_Q3_PATH
    _mkdir_for(output_path)

    plt.figure(figsize=(10, 5))
    plt.plot(
        continuous_curve["maturity_years"],
        continuous_curve["fitted_duffee_yield_pct"],
        linewidth=1.8,
        label="Fitted Duffee AA curve",
    )
    plt.plot(
        continuous_curve["maturity_years"],
        continuous_curve["fitted_risk_free_yield_pct"],
        linewidth=1.4,
        linestyle="--",
        label="Fitted CIR risk-free curve",
    )
    plt.scatter(
        term_structures["maturity_years"],
        term_structures["aa_yield_pct"],
        s=35,
        label="Observed AA yields",
        zorder=3,
    )
    plt.scatter(
        fit_df["maturity_years"],
        fit_df["fitted_aa_yield_pct"],
        s=25,
        label="Fitted AA nodes",
        zorder=3,
    )
    plt.xlim(0.0, 30.0)
    plt.xlabel("Maturity (years)")
    plt.ylabel("Yield (%)")
    plt.title("Part Two Question 3: Duffee Calibration")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=180)
    plt.close()


def run_part_two(project_root: Path) -> dict[str, str]:
    nss_parameters = fetch_nss_parameters(project_root)
    observed_aa_yields = save_observed_aa_yields(project_root)
    fred_benchmarks = fetch_fred_q1_benchmarks(project_root)
    term_structures = build_q1_term_structures(project_root, nss_parameters, observed_aa_yields)
    _q1_validation = build_q1_source_validation(project_root, term_structures, fred_benchmarks)
    _save_q1_figure(project_root, term_structures)

    _risk_free_fit_df, risk_free = calibrate_risk_free_cir(project_root, term_structures)
    duffee_fit_df, continuous_curve, duffee = calibrate_duffee_model(project_root, term_structures, risk_free)
    _save_q3_figure(project_root, term_structures, continuous_curve, duffee_fit_df)

    bond_valuation = value_callable_and_noncallable_bonds(project_root, risk_free, duffee)

    return {
        "nss_parameters_path": str(project_root / PART_TWO_NSS_PARAMS_PATH),
        "fred_benchmark_path": str(project_root / PART_TWO_FRED_Q1_BENCHMARK_PATH),
        "term_structures_path": str(project_root / PART_TWO_TERM_STRUCTURES_PATH),
        "q1_validation_path": str(project_root / PART_TWO_Q1_VALIDATION_PATH),
        "risk_free_fit_path": str(project_root / PART_TWO_RISK_FREE_FIT_PATH),
        "duffee_fit_path": str(project_root / PART_TWO_DUFFEE_FIT_PATH),
        "duffee_curve_path": str(project_root / PART_TWO_DUFFEE_CURVE_PATH),
        "parameters_path": str(project_root / PART_TWO_PARAMETERS_PATH),
        "bond_valuation_path": str(project_root / PART_TWO_VALUATION_PATH),
        "ytm_path": str(project_root / PART_TWO_YTM_PATH),
        "callable_price_usd": f"{bond_valuation.callable_price:.2f}",
        "noncallable_price_usd": f"{bond_valuation.noncallable_price_closed_form:.2f}",
        "callable_ytm_pct": f"{bond_valuation.callable_ytm * 100.0:.4f}",
        "noncallable_ytm_pct": f"{bond_valuation.noncallable_ytm * 100.0:.4f}",
    }
