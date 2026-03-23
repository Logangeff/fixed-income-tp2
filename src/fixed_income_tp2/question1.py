from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


COMPUSTAT_INPUT_NAME = "compustat_jnj_debt_quarterly.csv"
REQUIRED_QUARTERS = {
    "2024Q4": {"statement_date": date(2024, 12, 31)},
    "2025Q1": {"statement_date": date(2025, 3, 31)},
    "2025Q2": {"statement_date": date(2025, 6, 30)},
    "2025Q3": {"statement_date": date(2025, 9, 30)},
    "2025Q4": {"statement_date": date(2025, 12, 31)},
}


@dataclass(frozen=True)
class QuarterlyDebtObservation:
    quarter: str
    statement_date: date
    dlcq_usd: float
    dlttq_usd: float
    source: str
    field_mapping: str

    @property
    def l_usd(self) -> float:
        return self.dlcq_usd + 0.5 * self.dlttq_usd

    @property
    def dlcq_billion_usd(self) -> float:
        return self.dlcq_usd / 1_000_000_000

    @property
    def dlttq_billion_usd(self) -> float:
        return self.dlttq_usd / 1_000_000_000

    @property
    def l_billion_usd(self) -> float:
        return self.l_usd / 1_000_000_000


def _coerce_float(value: str | None) -> float:
    if value is None:
        raise ValueError("Expected a numeric value, received None.")
    cleaned = value.replace(",", "").replace("$", "").strip()
    if not cleaned:
        raise ValueError("Expected a numeric value, received an empty string.")
    return float(cleaned)


def _quarter_from_date(statement_date: date) -> str:
    month_to_quarter = {3: "Q1", 6: "Q2", 9: "Q3", 12: "Q4"}
    try:
        quarter_suffix = month_to_quarter[statement_date.month]
    except KeyError as exc:
        raise ValueError(f"Unsupported statement month: {statement_date.month}") from exc
    return f"{statement_date.year}{quarter_suffix}"


def _parse_date(value: str) -> date:
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def load_compustat_observations(csv_path: Path) -> list[QuarterlyDebtObservation]:
    selected: dict[str, QuarterlyDebtObservation] = {}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = {"dlcq", "dlttq"} - {name.lower() for name in (reader.fieldnames or [])}
        if missing:
            missing_list = ", ".join(sorted(missing))
            raise ValueError(f"{csv_path.name} is missing required columns: {missing_list}")

        for row in reader:
            normalized = {key.lower(): value for key, value in row.items() if key is not None}
            date_value = normalized.get("statement_date") or normalized.get("datadate") or normalized.get("date")
            quarter_value = normalized.get("quarter")

            if date_value:
                statement_date = _parse_date(date_value)
                quarter = quarter_value.strip() if quarter_value else _quarter_from_date(statement_date)
            elif quarter_value:
                quarter = quarter_value.strip()
                statement_date = REQUIRED_QUARTERS[quarter]["statement_date"]
            else:
                raise ValueError(
                    f"{csv_path.name} needs either a quarter column or a statement_date/datadate/date column."
                )

            if quarter not in REQUIRED_QUARTERS:
                continue

            # WRDS Compustat exports quarterly debt values in millions of USD.
            dlcq_musd = _coerce_float(normalized["dlcq"])
            dlttq_musd = _coerce_float(normalized["dlttq"])

            selected[quarter] = QuarterlyDebtObservation(
                quarter=quarter,
                statement_date=statement_date,
                dlcq_usd=dlcq_musd * 1_000_000,
                dlttq_usd=dlttq_musd * 1_000_000,
                source="Compustat export",
                field_mapping="DLCQ = Compustat DLCQ; DLTTQ = Compustat DLTTQ",
            )

    missing_quarters = [quarter for quarter in REQUIRED_QUARTERS if quarter not in selected]
    if missing_quarters:
        missing_list = ", ".join(missing_quarters)
        raise ValueError(f"{csv_path.name} does not contain all required quarters: {missing_list}")

    return [selected[quarter] for quarter in REQUIRED_QUARTERS]


def choose_question1_source(project_root: Path) -> list[QuarterlyDebtObservation]:
    compustat_path = project_root / "data" / "raw" / COMPUSTAT_INPUT_NAME
    if not compustat_path.exists():
        raise FileNotFoundError(
            "Missing data/raw/compustat_jnj_debt_quarterly.csv. "
            "Run scripts/fetch_wrds_compustat_q1.py first."
        )
    return load_compustat_observations(compustat_path)


def interpolate_daily_default_point(
    observations: list[QuarterlyDebtObservation],
) -> list[dict[str, str | float]]:
    daily_rows: list[dict[str, str | float]] = []
    for start, end in zip(observations, observations[1:]):
        span_days = (end.statement_date - start.statement_date).days
        if span_days <= 0:
            raise ValueError("Quarter observations must be strictly increasing in time.")

        for offset in range(span_days):
            current_date = start.statement_date + timedelta(days=offset)
            weight = offset / span_days
            l_usd = start.l_usd + weight * (end.l_usd - start.l_usd)
            daily_rows.append(
                {
                    "date": current_date.isoformat(),
                    "l_usd": round(l_usd, 2),
                    "l_billion_usd": round(l_usd / 1_000_000_000, 6),
                    "interpolation_start_quarter": start.quarter,
                    "interpolation_end_quarter": end.quarter,
                }
            )

    final_observation = observations[-1]
    daily_rows.append(
        {
            "date": final_observation.statement_date.isoformat(),
            "l_usd": round(final_observation.l_usd, 2),
            "l_billion_usd": round(final_observation.l_billion_usd, 6),
            "interpolation_start_quarter": final_observation.quarter,
            "interpolation_end_quarter": final_observation.quarter,
        }
    )
    return daily_rows


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str | float]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_question1(project_root: Path) -> dict[str, str]:
    observations = choose_question1_source(project_root)
    observations.sort(key=lambda item: item.statement_date)

    quarterly_rows = [
        {
            "quarter": observation.quarter,
            "statement_date": observation.statement_date.isoformat(),
            "dlcq_usd": int(observation.dlcq_usd),
            "dlttq_usd": int(observation.dlttq_usd),
            "l_usd": int(observation.l_usd),
            "dlcq_billion_usd": round(observation.dlcq_billion_usd, 3),
            "dlttq_billion_usd": round(observation.dlttq_billion_usd, 3),
            "l_billion_usd": round(observation.l_billion_usd, 3),
            "source": observation.source,
            "field_mapping": observation.field_mapping,
        }
        for observation in observations
    ]
    daily_rows = interpolate_daily_default_point(observations)

    raw_output = project_root / "data" / "raw" / "question1_jnj_quarterly_debt_series.csv"
    processed_output = project_root / "data" / "processed" / "question1_jnj_daily_default_point.csv"

    _write_csv(
        raw_output,
        [
            "quarter",
            "statement_date",
            "dlcq_usd",
            "dlttq_usd",
            "l_usd",
            "dlcq_billion_usd",
            "dlttq_billion_usd",
            "l_billion_usd",
            "source",
            "field_mapping",
        ],
        quarterly_rows,
    )
    _write_csv(
        processed_output,
        [
            "date",
            "l_usd",
            "l_billion_usd",
            "interpolation_start_quarter",
            "interpolation_end_quarter",
        ],
        daily_rows,
    )

    return {
        "source": observations[0].source,
        "quarterly_output": str(raw_output),
        "daily_output": str(processed_output),
    }
