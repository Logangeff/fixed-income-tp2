from __future__ import annotations

import io
import json
import math
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm

from fixed_income_tp2.question1 import run_question1


matplotlib.use("Agg")
import matplotlib.pyplot as plt


WRDS_MIN_SUPPORTED_PYTHON = (3, 8)
WRDS_MAX_SUPPORTED_PYTHON = (3, 12)
WRDS_CONFIG_PATH = Path("config/wrds.credentials.json")

PART_ONE_MARKET_CAP_PATH = Path("data/raw/part1_q2_jnj_market_cap_daily.csv")
PART_ONE_FRED_1Y_PATH = Path("data/raw/part1_q3_fred_1y_zero_coupon_daily.csv")
PART_ONE_FRED_Q5_BENCHMARK_PATH = Path("data/raw/part1_q5_fred_zero_coupon_benchmarks_daily.csv")
PART_ONE_ZERO_COUPON_PATH = Path("data/raw/part1_zero_coupon_yield_curve_daily.csv")
PART_ONE_ALIGNED_INPUTS_PATH = Path("data/processed/part1_q3_aligned_inputs.csv")
PART_ONE_ASSET_SERIES_PATH = Path("data/processed/part1_q3_asset_series.csv")
PART_ONE_ASSET_SUMMARY_PATH = Path("data/processed/part1_q3_asset_summary.csv")
PART_ONE_DEFAULT_FRONTIER_PATH = Path("data/processed/part1_q4_default_frontier.csv")
PART_ONE_SPREAD_CURVE_PATH = Path("data/processed/part1_q5_credit_spread_term_structure.csv")
PART_ONE_Q5_VALIDATION_PATH = Path("data/processed/part1_q5_risk_free_source_validation.csv")

FIGURE_Q2_PATH = Path("reports/figures/part1_q2_market_cap.png")
FIGURE_Q3_PATH = Path("reports/figures/part1_q3_asset_vs_equity.png")
FIGURE_Q4_PATH = Path("reports/figures/part1_q4_default_frontier.png")
FIGURE_Q5_PATH = Path("reports/figures/part1_q5_credit_spreads.png")

FED_NOMINAL_YIELD_CURVE_URL = "https://www.federalreserve.gov/data/yield-curve-tables/feds200628.csv"
FED_USER_AGENT = "fixed-income-tp2/1.0"
FRED_ONE_YEAR_ZERO_COUPON_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=THREEFY1"
FRED_Q5_BENCHMARK_SERIES = {
    "THREEFY1": "fred_zero_coupon_1y_pct",
    "THREEFY5": "fred_zero_coupon_5y_pct",
    "THREEFY10": "fred_zero_coupon_10y_pct",
}

TARGET_GVKEY = "006266"
TARGET_PERMCO = 21018
TARGET_PERMNO = 22111
TARGET_IID = "01"


@dataclass(frozen=True)
class AssetEstimationResult:
    iterations: int
    asset_volatility_annual: float
    asset_value_end_usd: float
    observation_count: int
    first_date: str
    last_date: str


def _load_wrds_config(project_root: Path) -> dict[str, str]:
    config_path = project_root / WRDS_CONFIG_PATH
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    if not config.get("wrds_username"):
        raise ValueError("config/wrds.credentials.json must include wrds_username.")
    return config


def _wrds_connection(project_root: Path):
    import sys

    current = sys.version_info[:2]
    if not (WRDS_MIN_SUPPORTED_PYTHON <= current <= WRDS_MAX_SUPPORTED_PYTHON):
        supported = ".".join(str(x) for x in WRDS_MAX_SUPPORTED_PYTHON)
        raise RuntimeError(
            "WRDS steps must run in the dedicated .venv-wrds environment. "
            f"Use Python {supported} or another supported WRDS interpreter."
        )

    try:
        import wrds
    except ImportError as exc:
        raise RuntimeError(
            "wrds is not installed in this interpreter. Activate .venv-wrds and try again."
        ) from exc

    config = _load_wrds_config(project_root)
    return wrds.Connection(wrds_username=config["wrds_username"])


def fetch_crsp_market_cap(project_root: Path) -> Path:
    output_path = project_root / PART_ONE_MARKET_CAP_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)

    query = f"""
        select
            dlycaldt as date,
            count(distinct permno) as permno_count,
            sum(abs(dlyprc) * shrout * 1000.0) as market_cap_usd,
            sum(dlycap * 1000.0) as crsp_dlycap_usd,
            sum(shrout * 1000.0) as shares_outstanding,
            avg(abs(dlyprc)) as average_price_usd
        from crsp.dsf_v2
        where permco = {TARGET_PERMCO}
          and dlycaldt between '2025-01-01' and '2025-12-31'
        group by dlycaldt
        order by dlycaldt
    """

    with _wrds_connection(project_root) as db:
        df = db.raw_sql(query, date_cols=["date"])

    if df.empty:
        raise RuntimeError("CRSP query returned no rows for Johnson & Johnson in 2025.")

    df["market_cap_usd"] = df["market_cap_usd"].astype(float)
    df["crsp_dlycap_usd"] = df["crsp_dlycap_usd"].astype(float)
    df["shares_outstanding"] = df["shares_outstanding"].astype(float)
    df["average_price_usd"] = df["average_price_usd"].astype(float)
    df.to_csv(output_path, index=False)
    return output_path


def fetch_zero_coupon_yield_curve(project_root: Path) -> Path:
    output_path = project_root / PART_ONE_ZERO_COUPON_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)

    request = urllib.request.Request(
        FED_NOMINAL_YIELD_CURVE_URL,
        headers={"User-Agent": FED_USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        text = response.read().decode("utf-8", errors="ignore")

    df = pd.read_csv(io.StringIO(text), skiprows=9)
    df["Date"] = pd.to_datetime(df["Date"])
    zero_coupon_columns = [f"SVENY{i:02d}" for i in range(1, 31)]
    keep_columns = ["Date"] + zero_coupon_columns
    df = df[keep_columns].copy()
    df = df.loc[df["Date"].between("2025-01-01", "2026-01-31")].copy()
    df.to_csv(output_path, index=False)
    return output_path


def fetch_fred_one_year_zero_coupon(project_root: Path) -> Path:
    output_path = project_root / PART_ONE_FRED_1Y_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(FRED_ONE_YEAR_ZERO_COUPON_URL)
    df = df.rename(columns={"observation_date": "date", "THREEFY1": "fred_zero_coupon_1y_pct"})
    df["date"] = pd.to_datetime(df["date"])
    df["fred_zero_coupon_1y_pct"] = pd.to_numeric(df["fred_zero_coupon_1y_pct"], errors="coerce")
    df = df.loc[df["date"].between("2025-01-01", "2026-01-31")].copy()
    df.to_csv(output_path, index=False)
    return output_path


def fetch_fred_q5_benchmarks(project_root: Path) -> Path:
    output_path = project_root / PART_ONE_FRED_Q5_BENCHMARK_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)

    merged = None
    for series_id, renamed_column in FRED_Q5_BENCHMARK_SERIES.items():
        df = pd.read_csv(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}")
        df = df.rename(columns={"observation_date": "date", series_id: renamed_column})
        df["date"] = pd.to_datetime(df["date"])
        df[renamed_column] = pd.to_numeric(df[renamed_column], errors="coerce")
        df = df.loc[df["date"].between("2025-01-01", "2026-01-31")].copy()

        if merged is None:
            merged = df
        else:
            merged = merged.merge(df, on="date", how="outer")

    if merged is None:
        raise RuntimeError("Failed to build the FRED benchmark zero-coupon series for Question 5.")

    merged = merged.sort_values("date")
    merged.to_csv(output_path, index=False)
    return output_path


def build_q3_inputs(project_root: Path) -> pd.DataFrame:
    q1_daily = pd.read_csv(project_root / "data/processed/question1_jnj_daily_default_point.csv")
    q2_market_cap = pd.read_csv(project_root / PART_ONE_MARKET_CAP_PATH)
    fred_one_year = pd.read_csv(project_root / PART_ONE_FRED_1Y_PATH)

    q1_daily["date"] = pd.to_datetime(q1_daily["date"])
    q2_market_cap["date"] = pd.to_datetime(q2_market_cap["date"])
    fred_one_year["date"] = pd.to_datetime(fred_one_year["date"])

    fred_one_year = fred_one_year[["date", "fred_zero_coupon_1y_pct"]].dropna()

    aligned = q2_market_cap.merge(fred_one_year, on="date", how="inner")
    aligned = aligned.merge(q1_daily[["date", "l_usd"]], on="date", how="inner")
    aligned = aligned.rename(
        columns={
            "market_cap_usd": "equity_value_usd",
            "l_usd": "default_point_usd",
            "fred_zero_coupon_1y_pct": "risk_free_zero_coupon_1y_pct",
        }
    )
    aligned["risk_free_zero_coupon_1y"] = aligned["risk_free_zero_coupon_1y_pct"] / 100.0
    aligned = aligned[
        [
            "date",
            "permno_count",
            "equity_value_usd",
            "crsp_dlycap_usd",
            "shares_outstanding",
            "average_price_usd",
            "default_point_usd",
            "risk_free_zero_coupon_1y_pct",
            "risk_free_zero_coupon_1y",
        ]
    ].copy()
    aligned.to_csv(project_root / PART_ONE_ALIGNED_INPUTS_PATH, index=False)
    return aligned


def _merton_equity_value(asset_value: float, default_point: float, rate: float, sigma_a: float, horizon: float) -> float:
    sigma_sqrt_t = sigma_a * math.sqrt(horizon)
    d1 = (math.log(asset_value / default_point) + (rate + 0.5 * sigma_a**2) * horizon) / sigma_sqrt_t
    d2 = d1 - sigma_sqrt_t
    return asset_value * norm.cdf(d1) - default_point * math.exp(-rate * horizon) * norm.cdf(d2)


def _solve_asset_value(equity_value: float, default_point: float, rate: float, sigma_a: float, horizon: float) -> float:
    sigma_a = max(sigma_a, 1e-6)

    def objective(asset_value: float) -> float:
        return _merton_equity_value(asset_value, default_point, rate, sigma_a, horizon) - equity_value

    lower = max(equity_value, 1.0)
    upper = max(equity_value + default_point, lower * 2.0)
    f_lower = objective(lower)
    f_upper = objective(upper)

    expansion_count = 0
    while f_upper <= 0:
        upper *= 2.0
        f_upper = objective(upper)
        expansion_count += 1
        if expansion_count > 50:
            raise RuntimeError("Failed to bracket the asset value root in the Merton step.")

    if f_lower > 0:
        lower = max(lower * 0.5, 1.0)
        f_lower = objective(lower)

    return brentq(objective, lower, upper, maxiter=200)


def estimate_asset_process(aligned_inputs: pd.DataFrame) -> tuple[pd.DataFrame, AssetEstimationResult]:
    horizon = 1.0
    tolerance = 1e-6
    max_iterations = 100

    aligned = aligned_inputs.copy()
    equity_returns = np.log(aligned["equity_value_usd"]).diff().dropna()
    sigma_a = float(equity_returns.std(ddof=1) * np.sqrt(252))
    sigma_a = max(sigma_a, 0.05)

    asset_values = None
    for iteration in range(1, max_iterations + 1):
        solved_values = []
        for row in aligned.itertuples(index=False):
            solved_value = _solve_asset_value(
                equity_value=float(row.equity_value_usd),
                default_point=float(row.default_point_usd),
                rate=float(row.risk_free_zero_coupon_1y),
                sigma_a=sigma_a,
                horizon=horizon,
            )
            solved_values.append(solved_value)

        asset_values = pd.Series(solved_values, index=aligned.index, name="asset_value_usd")
        asset_returns = np.log(asset_values).diff().dropna()
        sigma_new = float(asset_returns.std(ddof=1) * np.sqrt(252))
        if abs(sigma_new - sigma_a) < tolerance:
            sigma_a = sigma_new
            break
        sigma_a = sigma_new

    if asset_values is None:
        raise RuntimeError("Asset value iteration did not produce a valid series.")

    aligned["asset_value_usd"] = asset_values
    aligned["asset_return_log"] = np.log(aligned["asset_value_usd"]).diff()

    result = AssetEstimationResult(
        iterations=iteration,
        asset_volatility_annual=sigma_a,
        asset_value_end_usd=float(aligned.iloc[-1]["asset_value_usd"]),
        observation_count=len(aligned),
        first_date=aligned.iloc[0]["date"].strftime("%Y-%m-%d"),
        last_date=aligned.iloc[-1]["date"].strftime("%Y-%m-%d"),
    )
    return aligned, result


def build_default_frontier(project_root: Path) -> pd.DataFrame:
    q1_quarterly = pd.read_csv(project_root / "data/raw/question1_jnj_quarterly_debt_series.csv")
    end_2025 = q1_quarterly.loc[q1_quarterly["quarter"] == "2025Q4"].iloc[0]

    one_year_default_point = float(end_2025["l_usd"])
    twenty_year_default_point = float(end_2025["dlttq_usd"])
    slope = (twenty_year_default_point - one_year_default_point) / (20.0 - 1.0)

    maturities = np.arange(0.0, 30.0 + 0.25, 0.25)
    frontier = pd.DataFrame({"maturity_years": maturities})
    frontier["default_point_usd"] = one_year_default_point + slope * (frontier["maturity_years"] - 1.0)
    frontier["default_point_billion_usd"] = frontier["default_point_usd"] / 1_000_000_000
    frontier.to_csv(project_root / PART_ONE_DEFAULT_FRONTIER_PATH, index=False)
    return frontier


def build_credit_spread_curve(
    project_root: Path,
    asset_result: AssetEstimationResult,
    frontier: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.Timestamp, pd.DataFrame]:
    zero_curve = pd.read_csv(project_root / PART_ONE_ZERO_COUPON_PATH)
    zero_curve["Date"] = pd.to_datetime(zero_curve["Date"])
    fred_benchmarks = pd.read_csv(project_root / PART_ONE_FRED_Q5_BENCHMARK_PATH)
    fred_benchmarks["date"] = pd.to_datetime(fred_benchmarks["date"])

    first_trading_day_2026 = zero_curve.loc[
        (zero_curve["Date"] >= pd.Timestamp("2026-01-01")) & zero_curve["SVENY01"].notna(),
        "Date",
    ].min()
    curve_row = zero_curve.loc[zero_curve["Date"] == first_trading_day_2026].iloc[0]

    maturity_nodes = np.arange(1, 31, 1, dtype=float)
    risk_free_nodes = np.array([float(curve_row[f"SVENY{i:02d}"]) / 100.0 for i in range(1, 31)])

    maturities = np.arange(1.0, 30.0 + 0.25, 0.25)
    risk_free_curve = np.interp(maturities, maturity_nodes, risk_free_nodes)
    default_point_curve = np.interp(
        maturities,
        frontier["maturity_years"].to_numpy(),
        frontier["default_point_usd"].to_numpy(),
    )

    asset_value_0 = asset_result.asset_value_end_usd
    sigma_a = asset_result.asset_volatility_annual

    risky_prices = []
    risky_yields = []
    credit_spreads = []
    for maturity, default_point, rate in zip(maturities, default_point_curve, risk_free_curve):
        sigma_sqrt_t = sigma_a * math.sqrt(maturity)
        d1 = (math.log(asset_value_0 / default_point) + (rate + 0.5 * sigma_a**2) * maturity) / sigma_sqrt_t
        d2 = d1 - sigma_sqrt_t
        risky_price = (
            asset_value_0 * norm.cdf(-d1) + default_point * math.exp(-rate * maturity) * norm.cdf(d2)
        )
        risky_yield = -math.log(risky_price / default_point) / maturity
        credit_spread = risky_yield - rate

        risky_prices.append(risky_price)
        risky_yields.append(risky_yield)
        credit_spreads.append(credit_spread)

    spread_curve = pd.DataFrame(
        {
            "maturity_years": maturities,
            "default_point_usd": default_point_curve,
            "risk_free_yield_pct": risk_free_curve * 100.0,
            "risky_yield_pct": np.array(risky_yields) * 100.0,
            "credit_spread_pct": np.array(credit_spreads) * 100.0,
            "credit_spread_bps": np.array(credit_spreads) * 10_000.0,
            "risky_zero_coupon_price": risky_prices,
        }
    )
    spread_curve.to_csv(project_root / PART_ONE_SPREAD_CURVE_PATH, index=False)

    validation_row = fred_benchmarks.loc[fred_benchmarks["date"] == first_trading_day_2026].iloc[0]
    validation = pd.DataFrame(
        [
            {
                "date": first_trading_day_2026.strftime("%Y-%m-%d"),
                "maturity_years": 1,
                "stl_fed_fred_yield_pct": float(validation_row["fred_zero_coupon_1y_pct"]),
                "board_curve_yield_pct": float(curve_row["SVENY01"]),
            },
            {
                "date": first_trading_day_2026.strftime("%Y-%m-%d"),
                "maturity_years": 5,
                "stl_fed_fred_yield_pct": float(validation_row["fred_zero_coupon_5y_pct"]),
                "board_curve_yield_pct": float(curve_row["SVENY05"]),
            },
            {
                "date": first_trading_day_2026.strftime("%Y-%m-%d"),
                "maturity_years": 10,
                "stl_fed_fred_yield_pct": float(validation_row["fred_zero_coupon_10y_pct"]),
                "board_curve_yield_pct": float(curve_row["SVENY10"]),
            },
        ]
    )
    validation["difference_bps"] = (
        (validation["stl_fed_fred_yield_pct"] - validation["board_curve_yield_pct"]) * 100.0
    )
    validation.to_csv(project_root / PART_ONE_Q5_VALIDATION_PATH, index=False)

    return spread_curve, first_trading_day_2026, validation


def _save_q2_figure(project_root: Path, market_cap: pd.DataFrame) -> None:
    figure_path = project_root / FIGURE_Q2_PATH
    figure_path.parent.mkdir(parents=True, exist_ok=True)

    plt.figure(figsize=(10, 5))
    plt.plot(market_cap["date"], market_cap["market_cap_usd"] / 1_000_000_000, linewidth=1.5)
    plt.title("Johnson & Johnson Daily Market Capitalization (2025)")
    plt.ylabel("USD billions")
    plt.xlabel("Date")
    plt.tight_layout()
    plt.savefig(figure_path, dpi=180)
    plt.close()


def _save_q3_figure(project_root: Path, asset_series: pd.DataFrame) -> None:
    figure_path = project_root / FIGURE_Q3_PATH
    figure_path.parent.mkdir(parents=True, exist_ok=True)

    plt.figure(figsize=(10, 5))
    plt.plot(asset_series["date"], asset_series["equity_value_usd"] / 1_000_000_000, label="Equity value")
    plt.plot(asset_series["date"], asset_series["asset_value_usd"] / 1_000_000_000, label="Estimated asset value")
    plt.title("Question 3: Equity Value vs Estimated Asset Value")
    plt.ylabel("USD billions")
    plt.xlabel("Date")
    plt.legend()
    plt.tight_layout()
    plt.savefig(figure_path, dpi=180)
    plt.close()


def _save_q4_figure(project_root: Path, frontier: pd.DataFrame) -> None:
    figure_path = project_root / FIGURE_Q4_PATH
    figure_path.parent.mkdir(parents=True, exist_ok=True)

    plt.figure(figsize=(9, 5))
    plt.plot(frontier["maturity_years"], frontier["default_point_billion_usd"], linewidth=1.6)
    plt.title("Question 4: Default Frontier")
    plt.ylabel("Default point (USD billions)")
    plt.xlabel("Maturity (years)")
    plt.tight_layout()
    plt.savefig(figure_path, dpi=180)
    plt.close()


def _save_q5_figure(project_root: Path, spread_curve: pd.DataFrame) -> None:
    figure_path = project_root / FIGURE_Q5_PATH
    figure_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax1 = plt.subplots(figsize=(10, 5))
    ax1.plot(spread_curve["maturity_years"], spread_curve["risk_free_yield_pct"], label="Risk-free yield")
    ax1.plot(spread_curve["maturity_years"], spread_curve["risky_yield_pct"], label="Merton risky yield")
    ax1.set_xlabel("Maturity (years)")
    ax1.set_ylabel("Yield (%)")
    ax1.legend(loc="upper left")

    ax2 = ax1.twinx()
    ax2.plot(
        spread_curve["maturity_years"],
        spread_curve["credit_spread_bps"],
        color="black",
        linestyle="--",
        label="Credit spread",
    )
    ax2.set_ylabel("Credit spread (bps)")
    ax2.legend(loc="upper right")

    plt.title("Question 5: Risk-Free Curve, Risky Curve, and Credit Spread")
    plt.tight_layout()
    plt.savefig(figure_path, dpi=180)
    plt.close()


def run_part_one(project_root: Path) -> dict[str, str]:
    run_question1(project_root)

    fetch_crsp_market_cap(project_root)
    fetch_fred_one_year_zero_coupon(project_root)
    fetch_fred_q5_benchmarks(project_root)
    fetch_zero_coupon_yield_curve(project_root)

    aligned_inputs = build_q3_inputs(project_root)
    asset_series, asset_result = estimate_asset_process(aligned_inputs)
    asset_series.to_csv(project_root / PART_ONE_ASSET_SERIES_PATH, index=False)

    asset_summary = pd.DataFrame(
        [
            {
                "iterations": asset_result.iterations,
                "asset_volatility_annual": asset_result.asset_volatility_annual,
                "asset_volatility_pct": asset_result.asset_volatility_annual * 100.0,
                "asset_value_end_usd": asset_result.asset_value_end_usd,
                "asset_value_end_billion_usd": asset_result.asset_value_end_usd / 1_000_000_000,
                "observation_count": asset_result.observation_count,
                "first_date": asset_result.first_date,
                "last_date": asset_result.last_date,
            }
        ]
    )
    asset_summary.to_csv(project_root / PART_ONE_ASSET_SUMMARY_PATH, index=False)

    frontier = build_default_frontier(project_root)
    spread_curve, first_trading_day_2026, _validation = build_credit_spread_curve(
        project_root, asset_result, frontier
    )

    market_cap = pd.read_csv(project_root / PART_ONE_MARKET_CAP_PATH, parse_dates=["date"])
    asset_series_for_plot = pd.read_csv(project_root / PART_ONE_ASSET_SERIES_PATH, parse_dates=["date"])
    _save_q2_figure(project_root, market_cap)
    _save_q3_figure(project_root, asset_series_for_plot)
    _save_q4_figure(project_root, frontier)
    _save_q5_figure(project_root, spread_curve)

    return {
        "market_cap_path": str(project_root / PART_ONE_MARKET_CAP_PATH),
        "fred_one_year_path": str(project_root / PART_ONE_FRED_1Y_PATH),
        "zero_coupon_path": str(project_root / PART_ONE_ZERO_COUPON_PATH),
        "aligned_inputs_path": str(project_root / PART_ONE_ALIGNED_INPUTS_PATH),
        "asset_series_path": str(project_root / PART_ONE_ASSET_SERIES_PATH),
        "asset_summary_path": str(project_root / PART_ONE_ASSET_SUMMARY_PATH),
        "default_frontier_path": str(project_root / PART_ONE_DEFAULT_FRONTIER_PATH),
        "spread_curve_path": str(project_root / PART_ONE_SPREAD_CURVE_PATH),
        "q5_validation_path": str(project_root / PART_ONE_Q5_VALIDATION_PATH),
        "first_trading_day_2026": first_trading_day_2026.strftime("%Y-%m-%d"),
    }
