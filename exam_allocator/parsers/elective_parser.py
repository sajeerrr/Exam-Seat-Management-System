"""
Elective list parser module.

Supports parsing elective student lists in Excel (.xlsx, .xlsm) and PDF formats.
Extracts departments, elective groups, subjects, and student enrollments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from openpyxl import load_workbook

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


class ElectiveExcelParseError(Exception):
    """Raised when elective files cannot be parsed."""


@dataclass
class ElectiveStudentRecord:
    roll_number: str
    student_name: str
    gender: str = ""
    uni_reg_no: str = ""


@dataclass
class ElectiveSubjectRecord:
    subject_code: str
    subject_name: str
    students: list[ElectiveStudentRecord] = field(default_factory=list)


@dataclass
class ElectiveGroupRecord:
    department_code: str
    department_name: str
    elective_label: str  # e.g., "Elective 1", "Professional Elective"
    subjects: list[ElectiveSubjectRecord] = field(default_factory=list)


@dataclass
class ElectiveExtractionResult:
    source_file: str
    groups: list[ElectiveGroupRecord]
    issues: list[str] = field(default_factory=list)


def parse_elective_file(file_path: str) -> ElectiveExtractionResult:
    """
    Parse an elective file (Excel or PDF) and return normalized extraction results.
    """
    path = Path(file_path)
    if not path.exists():
        raise ElectiveExcelParseError(f"File not found: {file_path}")

    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return _parse_elective_excel(path)
    elif suffix == ".pdf":
        return _parse_elective_pdf(path)
    else:
        raise ElectiveExcelParseError(f"Unsupported file format: {suffix}")


def _parse_elective_excel(path: Path) -> ElectiveExtractionResult:
    try:
        workbook = load_workbook(filename=path, read_only=True, data_only=True)
    except Exception as exc:
        raise ElectiveExcelParseError(f"Could not open Excel workbook: {exc}") from exc

    groups: list[ElectiveGroupRecord] = []
    issues: list[str] = []

    try:
        for worksheet in workbook.worksheets:
            if worksheet.title.strip().lower() in {"master overview", "overview"}:
                continue

            try:
                sheet_groups, sheet_issues = _parse_elective_sheet(worksheet)
                groups.extend(sheet_groups)
                issues.extend(sheet_issues)
            except Exception as exc:
                issues.append(f"Sheet '{worksheet.title}': {exc}")
    finally:
        workbook.close()

    if not groups:
        raise ElectiveExcelParseError("No elective groups or subjects found in Excel workbook.")

    return ElectiveExtractionResult(
        source_file=path.name,
        groups=groups,
        issues=issues,
    )


def _parse_elective_sheet(worksheet):
    rows = list(worksheet.iter_rows(values_only=True))
    if not rows:
        return [], ["Sheet is empty."]

    # Simple heuristic to extract elective data from Excel sheets
    # Can handle tables structured with Subject Code, Subject Name, Roll No, Student Name
    dept_code = worksheet.title.strip()
    elective_label = "Elective"

    subjects_dict: dict[str, ElectiveSubjectRecord] = {}
    issues: list[str] = []

    header_idx = None
    headers = []
    for i, row in enumerate(rows):
        row_strs = [str(x).strip().lower() if x is not None else "" for x in row]
        if "roll no" in row_strs or "student name" in row_strs or "subject code" in row_strs:
            header_idx = i
            headers = row_strs
            break

    if header_idx is None:
        # Fallback: treat rows as simple list
        header_idx = 0
        headers = ["roll no", "student name", "subject code", "subject name"]

    idx_roll = headers.index("roll no") if "roll no" in headers else (-1 if "roll no" not in headers else 0)
    idx_name = headers.index("student name") if "student name" in headers else 1
    idx_code = headers.index("subject code") if "subject code" in headers else (headers.index("course code") if "course code" in headers else -1)
    idx_subname = headers.index("subject name") if "subject name" in headers else -1

    for r_num, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        if not any(x is not None and str(x).strip() for x in row):
            continue

        def get_val(idx):
            if idx != -1 and idx < len(row) and row[idx] is not None:
                return str(row[idx]).strip()
            return ""

        roll = get_val(idx_roll)
        name = get_val(idx_name)
        code = get_val(idx_code) or "ELECTIVE-SUB"
        subname = get_val(idx_subname) or code

        if not roll or not name:
            continue

        if code not in subjects_dict:
            subjects_dict[code] = ElectiveSubjectRecord(
                subject_code=code,
                subject_name=subname,
                students=[]
            )

        subjects_dict[code].students.append(
            ElectiveStudentRecord(roll_number=roll, student_name=name)
        )

    group = ElectiveGroupRecord(
        department_code=dept_code,
        department_name=dept_code,
        elective_label=elective_label,
        subjects=list(subjects_dict.values())
    )

    return [group], issues


def _parse_elective_pdf(path: Path) -> ElectiveExtractionResult:
    if fitz is None:
        raise ElectiveExcelParseError("PyMuPDF (fitz) is required to parse PDF elective files.")

    try:
        doc = fitz.open(str(path))
    except Exception as exc:
        raise ElectiveExcelParseError(f"Could not open PDF file: {exc}") from exc

    text_content = ""
    for page in doc:
        text_content += page.get_text() + "\n"
    doc.close()

    # Basic PDF text parsing heuristic for elective lists
    subjects_dict: dict[str, ElectiveSubjectRecord] = {}
    current_subject = "GENERAL-ELECTIVE"
    current_subname = "General Elective Subject"

    lines = text_content.splitlines()
    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue

        # Check if line looks like a subject heading
        if "subject" in line_str.lower() or "course:" in line_str.lower():
            current_subject = line_str[:30]
            current_subname = line_str
            continue

        # Check for roll number pattern (e.g., numbers/alphanumerics like KKE23CS001)
        match = re.match(r"^([A-Z0-9\-]+)\s+(.+)$", line_str)
        if match:
            roll = match.group(1)
            name = match.group(2)
            if len(roll) >= 4 and not roll.lower().startswith("page"):
                if current_subject not in subjects_dict:
                    subjects_dict[current_subject] = ElectiveSubjectRecord(
                        subject_code=current_subject,
                        subject_name=current_subname,
                        students=[]
                    )
                subjects_dict[current_subject].students.append(
                    ElectiveStudentRecord(roll_number=roll, student_name=name)
                )

    if not subjects_dict:
        # Fallback if no structured rows matched
        subjects_dict["ELECTIVE-1"] = ElectiveSubjectRecord(
            subject_code="ELECTIVE-1",
            subject_name="Elective Subject 1",
            students=[]
        )

    group = ElectiveGroupRecord(
        department_code="GEN",
        department_name="General Department",
        elective_label="Elective Group",
        subjects=list(subjects_dict.values())
    )

    return ElectiveExtractionResult(
        source_file=path.name,
        groups=[group],
        issues=[]
    )
