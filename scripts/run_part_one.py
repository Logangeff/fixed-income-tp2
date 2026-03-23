from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fixed_income_tp2.part_one import run_part_one


if __name__ == "__main__":
    result = run_part_one(PROJECT_ROOT)
    for key, value in result.items():
        print(f"{key}: {value}")
