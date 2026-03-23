from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fixed_income_tp2.wrds_compustat import fetch_compustat_jnj_debt


if __name__ == "__main__":
    config_path = PROJECT_ROOT / "config" / "wrds.credentials.json"
    output_path = PROJECT_ROOT / "data" / "raw" / "compustat_jnj_debt_quarterly.csv"

    if not config_path.exists():
        raise SystemExit(
            "Missing config/wrds.credentials.json. Copy config/wrds.credentials.example.json first."
        )

    csv_path = fetch_compustat_jnj_debt(config_path=config_path, output_path=output_path)
    print(f"Saved WRDS Compustat extract to: {csv_path}")
