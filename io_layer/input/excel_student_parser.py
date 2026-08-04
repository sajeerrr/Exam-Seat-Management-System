# io_layer/input/excel_student_parser.py
"""
Parses the consolidated TKM College student Excel workbook into Student objects.

Expected workbook layout (TKMCE_All_Classes_Separate_Student_Lists.xlsx):
  Sheet 'Master Overview' – summary table, skipped automatically.
  Every other sheet  – one class, with the structure:

    Row 1  : College / Department header (merged cell)
    Row 2  : blank
    Row 3  : 'Class Name: CE 2K23A'  |  …  |  'Semester: S6 (VIth Semester)'
    Row 4  : 'Total Students: 75'   |  …
    Row 5  : blank
    Row 6  : Sl. No. | Admission No | Roll No | Uni Reg No | Student Name | Gender
    Row 7+ : student data rows

The parser infers department, section, and semester from the sheet's header.
Subject code, exam date, and session are injected later by SessionFilter.
"""

import logging
import re
from pathlib import Path

import openpyxl

from engine.models.student import Student

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

# Sheets to skip entirely
_SKIP_SHEETS = {"master overview"}

# Roman numeral → integer
_ROMAN = {
    "I": 1, "II": 2, "III": 3, "IV": 4,
    "V": 5, "VI": 6, "VII": 7, "VIII": 8,
    "IX": 9, "X": 10,
}

# Regex: trailing section letter from class name, e.g. "CE 2K23A" → "A"
_SECTION_RE = re.compile(r"([A-Z])$")

# Maps abbreviated dept prefix → canonical engine dept code
_DEPT_MAP = {
    "CE": "CE", "ME": "ME", "EE": "EE", "EC": "EC",
    "CS": "CS", "CH": "CH", "EL": "EL",
    "B.ARCH": "AR", "ARCH": "AR",
    "EEE": "EEE",
}

# Column indices (0-based) inside the student table
_COL_ROLL  = 2   # Roll No       (e.g. B23CEA01)
_COL_REG   = 3   # Uni Reg No    (e.g. TKM23CE001)
_COL_NAME  = 4   # Student Name
_COL_GENDER = 5  # Gender


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_semester(raw: str) -> int:
    """Convert 'S6 (VIth Semester)' or 'VIth Semester' → 6."""
    raw = raw.strip().upper()
    # Try 'VIth Semester' style first
    for roman, value in sorted(_ROMAN.items(), key=lambda x: -len(x[0])):
        if roman in raw:
            return value
    return 0


def _parse_class_name(class_name: str) -> tuple[str, str]:
    """
    Parse 'CE 2K23A' → ('CE', 'A').
    Parse 'B.Arch 2K22 A' → ('AR', 'A').
    Returns (department_code, section).
    """
    class_name = class_name.strip()
    match = _SECTION_RE.search(class_name)
    section = match.group(1) if match else "A"
    dept_raw = class_name.split()[0].upper()
    department = _DEPT_MAP.get(dept_raw, dept_raw)
    return department, section


def _extract_value(cell_text: str, prefix: str) -> str:
    """
    From 'Class Name: CE 2K23A' with prefix='Class Name:' → 'CE 2K23A'.
    Case-insensitive prefix match.
    """
    text = str(cell_text or "").strip()
    if text.lower().startswith(prefix.lower()):
        return text[len(prefix):].strip()
    return ""


# ── Main Parser ────────────────────────────────────────────────────────────────

class ExcelStudentParser:
    """
    Parses the consolidated TKMCE student Excel workbook.

    Usage
    -----
    students = ExcelStudentParser().parse(
        "resources/TKMCE_All_Classes_Separate_Student_Lists.xlsx"
    )
    """

    def parse(self, filepath: str | Path) -> list[Student]:
        filepath = Path(filepath)
        logger.info("Parsing student Excel: %s", filepath.name)

        wb = openpyxl.load_workbook(filepath, data_only=True)
        all_students: list[Student] = []

        for sheet_name in wb.sheetnames:
            if sheet_name.strip().lower() in _SKIP_SHEETS:
                logger.debug("Skipping sheet: %s", sheet_name)
                continue

            students = self._parse_sheet(wb[sheet_name], sheet_name)
            all_students.extend(students)

        logger.info(
            "Total students loaded from Excel: %d across %d sheets",
            len(all_students),
            len(wb.sheetnames) - 1,   # minus Master Overview
        )
        return all_students

    # ── Sheet-level parser ─────────────────────────────────────────────────────

    def _parse_sheet(self, ws, sheet_name: str) -> list[Student]:
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []

        # ── Extract metadata from header block (rows 1-6) ──────────────────────
        class_name = ""
        semester_str = ""

        for row in rows[:6]:
            for cell in row:
                if cell is None:
                    continue
                text = str(cell).strip()
                if text.lower().startswith("class name:"):
                    class_name = _extract_value(text, "Class Name:")
                elif text.lower().startswith("semester:"):
                    semester_str = _extract_value(text, "Semester:")

        if not class_name:
            # Fallback: use sheet name itself, e.g. 'CE 2K23 A (S6)' → 'CE 2K23A'
            class_name = re.sub(r"\s*\(.*?\)", "", sheet_name).replace(" ", "")
            logger.warning(
                "Sheet '%s': no 'Class Name:' header found; inferred '%s'",
                sheet_name, class_name,
            )

        department, section = _parse_class_name(class_name)
        semester = _parse_semester(semester_str)

        logger.info(
            "Sheet %-25s → dept=%-5s  section=%s  semester=%d",
            f"'{sheet_name}'", department, section, semester,
        )

        # ── Find the student data header row ───────────────────────────────────
        data_start = None
        for idx, row in enumerate(rows):
            if row[0] is not None and str(row[0]).strip().lower() in {"sl. no.", "sl.no."}:
                data_start = idx + 1   # first student row
                break

        if data_start is None:
            logger.warning("Sheet '%s': student header not found — skipping.", sheet_name)
            return []

        # ── Parse student rows ─────────────────────────────────────────────────
        students: list[Student] = []
        for row in rows[data_start:]:
            # Blank / footer row guard
            if row[0] is None or str(row[0]).strip() == "":
                continue
            if not str(row[0]).strip().isdigit():
                continue          # not a serial-number row

            try:
                roll_no     = str(row[_COL_ROLL] or "").strip()
                register_no = str(row[_COL_REG]  or "").strip()
                name        = str(row[_COL_NAME] or "").strip()

                if not name or not register_no:
                    logger.debug("Skipping incomplete row: %s", row)
                    continue

                students.append(Student(
                    register_no  = register_no,
                    name         = name,
                    department   = department,
                    semester     = semester,
                    section      = section,
                    subject_code = "",
                    subject_name = "",
                    exam_date    = "",
                    session      = "",
                    roll_no      = roll_no,
                ))
            except (IndexError, AttributeError) as exc:
                logger.warning("Sheet '%s': skipping malformed row %s — %s", sheet_name, row, exc)

        logger.info(
            "  → %d students parsed from sheet '%s'", len(students), sheet_name
        )
        return students
