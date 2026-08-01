# io_layer/input/classroom_parser.py
"""
Parses the TKM College classroom list Excel file into Classroom objects.

The Excel has a multi-column layout with sections for different blocks
(Main Block, Chemical Block, Workshop Block, Mechanical Block, etc.)
Each section has columns: Sl No | Hall No | cctv | Remarks

We extract all Hall No values and create Classroom objects using the
default dimensions from config.py (since the Excel doesn't have row/bench data).
"""

import logging
from pathlib import Path

import openpyxl

from engine.models.classroom import Classroom
from engine.config import (
    DEFAULT_ROWS,
    DEFAULT_BENCHES_PER_ROW,
    DEFAULT_SEATS_PER_BENCH,
)

logger = logging.getLogger(__name__)


class ClassroomParser:
    """
    Parses the classroom list Excel into Classroom objects.

    Usage
    -----
    classrooms = ClassroomParser().parse("resources/Classroom List.xlsx")
    """

    def parse(
        self,
        filepath: str | Path,
        rows: int              = DEFAULT_ROWS,
        benches_per_row: int   = DEFAULT_BENCHES_PER_ROW,
        seats_per_bench: int   = DEFAULT_SEATS_PER_BENCH,
    ) -> list[Classroom]:

        filepath = Path(filepath)
        logger.info("Parsing classroom Excel: %s", filepath.name)

        wb = openpyxl.load_workbook(filepath, data_only=True)
        ws = wb.active

        classrooms: list[Classroom] = []
        seen: set[str] = set()

        for row in ws.iter_rows(values_only=True):
            for cell in row:
                if cell is None:
                    continue

                val = str(cell).strip()

                if val.lower() in {
                    "sl no", "hall no", "cctv", "remarks",
                    "main block", "chemical block", "workshop block",
                    "mechanical block", "architecture studio's",
                    "class room", "class", "sl no.", "",
                }:
                    continue

                if val.isdigit() and int(val) < 100:
                    continue

                if val.lower() in {"yes", "no"}:
                    continue

                if val not in seen:
                    seen.add(val)
                    classrooms.append(
                        Classroom(
                            room_no         = val,
                            rows            = rows,
                            benches_per_row = benches_per_row,
                            seats_per_bench = seats_per_bench,
                        )
                    )

        logger.info("Parsed %d classrooms from %s", len(classrooms), filepath.name)
        return classrooms
