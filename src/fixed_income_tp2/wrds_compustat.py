from __future__ import annotations

import json
import sys
from pathlib import Path


MIN_SUPPORTED_PYTHON = (3, 8)
MAX_SUPPORTED_PYTHON = (3, 12)


def _load_config(config_path: Path) -> dict[str, str]:
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)

    required_keys = {
        "wrds_username",
        "compustat_library",
        "compustat_table",
        "gvkey",
        "start_date",
        "end_date",
    }
    missing = [key for key in sorted(required_keys) if not config.get(key)]
    if missing:
        missing_list = ", ".join(missing)
        raise ValueError(f"{config_path.name} is missing required values: {missing_list}")
    return config


def _assert_supported_python() -> None:
    current = sys.version_info[:2]
    if MIN_SUPPORTED_PYTHON <= current <= MAX_SUPPORTED_PYTHON:
        return

    minimum = ".".join(str(part) for part in MIN_SUPPORTED_PYTHON)
    maximum = ".".join(str(part) for part in MAX_SUPPORTED_PYTHON)
    current_label = ".".join(str(part) for part in current)
    raise RuntimeError(
        "The official WRDS Python package is documented for Python "
        f"{minimum} through {maximum}, but this interpreter is {current_label}. "
        "Use a separate Python 3.12 virtual environment for the WRDS download step."
    )


def fetch_compustat_jnj_debt(config_path: Path, output_path: Path) -> Path:
    _assert_supported_python()

    try:
        import wrds
    except ImportError as exc:
        raise RuntimeError(
            "The wrds package is not installed in this environment. "
            "Create a Python 3.12 virtual environment and run "
            "`python -m pip install -U pip wheel wrds pandas`."
        ) from exc

    config = _load_config(config_path)

    sql = f"""
        select
            gvkey,
            datadate,
            fyearq,
            fqtr,
            dlcq,
            dlttq
        from {config['compustat_library']}.{config['compustat_table']}
        where gvkey = %(gvkey)s
          and datadate between %(start_date)s and %(end_date)s
          and indfmt = 'INDL'
          and datafmt = 'STD'
          and consol = 'C'
          and popsrc = 'D'
        order by datadate
    """

    params = {
        "gvkey": config["gvkey"],
        "start_date": config["start_date"],
        "end_date": config["end_date"],
    }

    with wrds.Connection(wrds_username=config["wrds_username"]) as db:
        frame = db.raw_sql(sql, params=params, date_cols=["datadate"])

    if frame.empty:
        raise RuntimeError(
            "WRDS returned no rows. Check that your account has Compustat access and that the query filters are valid."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False)
    return output_path

