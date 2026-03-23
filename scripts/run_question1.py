from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fixed_income_tp2.question1 import run_question1


if __name__ == "__main__":
    result = run_question1(PROJECT_ROOT)
    print(f"Question 1 source: {result['source']}")
    print(f"Quarterly output: {result['quarterly_output']}")
    print(f"Daily output: {result['daily_output']}")
