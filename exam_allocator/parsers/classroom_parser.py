"""
Excel classroom parser.
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

class ClassroomExcelParseError(Exception):
    """Raised when the classroom Excel workbook cannot be parsed."""

@dataclass
class ClassroomRecord:
    room_number: str
    capacity: int
    benches: int
    building: str

@dataclass
class ClassroomExtractionResult:
    source_file: str
    classrooms: list[ClassroomRecord]
    issues: list[str]

DEFAULT_CAPACITY = 45
DEFAULT_BENCHES = 15
DEFAULT_BUILDING = "Main Building"

def parse_classroom_excel(
    excel_path: str,
    default_capacity: int = DEFAULT_CAPACITY,
    default_benches: int = DEFAULT_BENCHES,
    default_building: str = DEFAULT_BUILDING,
) -> ClassroomExtractionResult:
    import pandas as pd
    import numpy as np
    
    path = Path(excel_path)

    if not path.exists():
        raise ClassroomExcelParseError(f"File not found: {excel_path}")

    # allow .xls and .xlsx types
    if path.suffix.lower() not in {".xlsx", ".xlsm", ".xls"}:
        raise ClassroomExcelParseError(
            f"Unsupported file type: {path.suffix}"
        )

    try:
        df = pd.read_excel(path)
    except Exception as exc:
        raise ClassroomExcelParseError(
            f"Could not open Excel workbook: {exc}"
        ) from exc

    df.columns = df.columns.astype(str).str.lower().str.strip()
    
    hall_cols = [c for c in df.columns if any(x in c for x in ['hall', 'room', 'class', 'name'])]
    cap_cols = [c for c in df.columns if any(x in c for x in ['student', 'capacit'])]
    bench_cols = [c for c in df.columns if any(x in c for x in ['bench'])]
    
    if not hall_cols:
        if len(df.columns) > 1:
            hall_cols = [df.columns[1]]
        elif len(df.columns) == 1:
            hall_cols = [df.columns[0]]
        else:
            raise ClassroomExcelParseError("Could not find a column for 'Hall No' or 'Room No'.")

    hall_col = hall_cols[0]
    
    classrooms: list[ClassroomRecord] = []
    issues: list[str] = []

    for idx, row in df.iterrows():
        room_val = row[hall_col]
        if pd.isna(room_val):
            continue
            
        room_str = str(room_val).strip()
        if not room_str or room_str.lower() in {'nan', 'none'}:
            continue
            
        if room_str.lower() in {'class room', 'classroom', 'room', 'room number', 'hall no'}:
            continue
            
        if any(c.room_number == room_str for c in classrooms):
            issues.append(f"Duplicate classroom '{room_str}'. Skipped.")
            continue
            
        # capacity
        capacity = default_capacity
        if cap_cols:
            val = row[cap_cols[0]]
            if pd.notna(val):
                try:
                    capacity = int(float(val))
                except ValueError:
                    pass

        # benches
        benches = default_benches
        if bench_cols:
            val = row[bench_cols[0]]
            if pd.notna(val):
                try:
                    benches = int(float(val))
                except ValueError:
                    pass

        classrooms.append(
            ClassroomRecord(
                room_number=room_str,
                capacity=capacity,
                benches=benches,
                building=default_building
            )
        )

    if not classrooms:
        raise ClassroomExcelParseError("No valid classrooms were found in the workbook.")

    return ClassroomExtractionResult(
        source_file=path.name,
        classrooms=classrooms,
        issues=issues,
    )
