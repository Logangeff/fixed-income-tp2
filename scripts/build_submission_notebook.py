from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = PROJECT_ROOT / "FINA_60201_TP2_Submission.ipynb"
REPORT_PATH = PROJECT_ROOT / "reports/assignment_report.md"

SOURCE_FILES = [
    Path("config/wrds.credentials.example.json"),
    Path("scripts/fetch_wrds_compustat_q1.py"),
    Path("scripts/run_question1.py"),
    Path("scripts/run_part_one.py"),
    Path("scripts/run_part_two.py"),
    Path("src/fixed_income_tp2/__init__.py"),
    Path("src/fixed_income_tp2/wrds_compustat.py"),
    Path("src/fixed_income_tp2/question1.py"),
    Path("src/fixed_income_tp2/part_one.py"),
    Path("src/fixed_income_tp2/part_two.py"),
]


def markdown_cell(source: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": source,
    }


def code_cell(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source,
    }


def split_report_sections(report_text: str) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []

    for line in report_text.splitlines():
        if (line.startswith("## ") or line.startswith("### ")) and current:
            chunks.append("\n".join(current).strip() + "\n")
            current = [line]
        else:
            current.append(line)

    if current:
        chunks.append("\n".join(current).strip() + "\n")
    return chunks


def build_notebook() -> dict:
    report_text = REPORT_PATH.read_text(encoding="utf-8")
    report_sections = split_report_sections(report_text)

    cells: list[dict] = [
        markdown_cell(
            "# FINA 60201A - TP 2 Submission Notebook\n\n"
            "This notebook is the standalone submission version of the project. "
            "It mirrors the written report and embeds the project code directly so the notebook can be read on its own.\n\n"
            "Notes:\n"
            "- WRDS-dependent cells still require valid school access.\n"
            "- Generated `data/` files are not committed to the repository, so rerunning the workflows will regenerate them locally.\n"
            "- The original assignment and theory PDFs are stored in `docs/`.\n"
        ),
        markdown_cell(
            "## How To Use This Notebook\n\n"
            "1. Read the report sections below for the written answers.\n"
            "2. Review the embedded code sections for the full implementation.\n"
            "3. If needed, run the helper cells at the end to regenerate Question 1, Part One, or Part Two.\n"
        ),
    ]

    cells.extend(markdown_cell(section) for section in report_sections)

    cells.append(
        markdown_cell(
            "## Embedded Project Code\n\n"
            "The following cells contain the project code exactly as implemented in the repository. "
            "Keeping the code here makes the notebook a self-contained submission artifact."
        )
    )

    for relative_path in SOURCE_FILES:
        file_text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        cells.append(markdown_cell(f"### File: `{relative_path.as_posix()}`"))
        if relative_path.suffix == ".json":
            cells.append(code_cell(file_text))
        else:
            cells.append(code_cell(file_text))

    cells.append(
        markdown_cell(
            "## Optional Runner Cells\n\n"
            "These cells are included for convenience if you want to regenerate outputs directly from the notebook."
        )
    )
    cells.append(
        code_cell(
            "from pathlib import Path\n\n"
            "PROJECT_ROOT = Path.cwd()\n"
            "PROJECT_ROOT\n"
        )
    )
    cells.append(
        code_cell(
            "# Uncomment these lines one at a time if you want to rerun the workflows.\n"
            "# from fixed_income_tp2.question1 import run_question1\n"
            "# from fixed_income_tp2.part_one import run_part_one\n"
            "# from fixed_income_tp2.part_two import run_part_two\n"
            "# run_question1(PROJECT_ROOT)\n"
            "# run_part_one(PROJECT_ROOT)\n"
            "# run_part_two(PROJECT_ROOT)\n"
        )
    )

    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
                "version": "3.10",
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def main() -> None:
    notebook = build_notebook()
    NOTEBOOK_PATH.write_text(json.dumps(notebook, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
