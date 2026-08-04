# io_layer/input/classroom_parser.py
"""
Parses the TKM College classroom list Excel file into Classroom objects.

The actual class.xlsx has a single column layout:
  Row 1 (header): "Class Room"
  Row 2+:         room numbers (integers like 101 or strings like "M203", "H205")

No bench/capacity columns are present — defaults from config.py are used.
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

# Header / label cells to skip (compared case-insensitively)
_SKIP_LABELS = {"class room", "hall no", "hall no.", "room no", "room no.", ""}


class ClassroomParser:
    """
    Parses the classroom list Excel into Classroom objects.

    Supports the single-column format:
      Column A, row 1 = header ("Class Room")
      Column A, rows 2+ = room identifiers (101, M203, H205, …)

    Usage
    -----
    classrooms = ClassroomParser().parse("resources/class.xlsx")
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

        for row in ws.iter_rows(min_row=2, values_only=True):   # skip header
            val = row[0]                                         # column A only
            if val is None:
                continue
            room_no = str(val).strip()
            if not room_no or room_no.lower() in _SKIP_LABELS:
                continue
            if room_no not in seen:
                seen.add(room_no)
                classrooms.append(
                    Classroom(
                        room_no         = room_no,
                        rows            = rows,
                        benches_per_row = benches_per_row,
                        seats_per_bench = seats_per_bench,
                    )
                )

        logger.info("Parsed %d classrooms from %s", len(classrooms), filepath.name)
        return classrooms
