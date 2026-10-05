"""
Excel student-list parser.

Reads the Students.xlsx workbook used by the exam seat allocation demo.

The workbook contains:
    - "Master Overview" sheet
    - One sheet per class

Each class sheet contains:
    - Class name
    - Semester
    - Duration
    - Student count information
    - Student roster

This module only parses and normalizes the Excel file.
It does not access the Django database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from openpyxl import load_workbook


class StudentExcelParseError(Exception):
    """Raised when the student Excel workbook cannot be parsed."""


@dataclass
class StudentRecord:
    sl_no: str
    admission_no: str
    roll_number: str
    uni_reg_no: str
    name: str
    gender: str
    class_name: str
    semester: int
    academic_year: str


@dataclass
class ClassRecord:
    class_name: str
    semester: int
    academic_year: str
    department_name: str
    students: list[StudentRecord] = field(default_factory=list)


@dataclass
class StudentExtractionResult:
    source_file: str
    classes: list[ClassRecord]
    students: list[StudentRecord]
    issues: list[str] = field(default_factory=list)


ROSTER_HEADER = [
    "Sl. No.",
    "Admission No",
    "Roll No",
    "Uni Reg No",
    "Student Name",
    "Gender",
]

MASTER_SHEET_NAME = "Master Overview"


def parse_student_excel(excel_path: str) -> StudentExtractionResult:
    """
    Parse a Students.xlsx workbook.

    Returns normalized class and student records.
    """

    path = Path(excel_path)

    if not path.exists():
        raise StudentExcelParseError(
            f"File not found: {excel_path}"
        )

    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise StudentExcelParseError(
            f"Unsupported file type: {path.suffix}"
        )

    try:
        workbook = load_workbook(
            filename=path,
            read_only=True,
            data_only=True,
        )
    except Exception as exc:
        raise StudentExcelParseError(
            f"Could not open Excel workbook: {exc}"
        ) from exc

    classes: list[ClassRecord] = []
    students: list[StudentRecord] = []
    issues: list[str] = []

    try:
        for worksheet in workbook.worksheets:

            # The overview is useful for humans but the individual
            # class sheets contain the actual student records.
            if worksheet.title.strip() == MASTER_SHEET_NAME:
                continue

            try:
                class_record, class_students, class_issues = (
                    _parse_class_sheet(worksheet)
                )

                classes.append(class_record)
                students.extend(class_students)
                issues.extend(class_issues)

            except StudentExcelParseError as exc:
                issues.append(
                    f"Sheet '{worksheet.title}': {exc}"
                )

    finally:
        workbook.close()

    if not classes:
        raise StudentExcelParseError(
            "No class sheets containing student data were found."
        )

    return StudentExtractionResult(
        source_file=path.name,
        classes=classes,
        students=students,
        issues=issues,
    )


def _parse_class_sheet(worksheet):
    rows = list(worksheet.iter_rows(values_only=True))
    if not rows:
        raise StudentExcelParseError("Sheet is empty.")

    header_index = None
    headers = []
    
    for i, row in enumerate(rows):
        row_strs = [str(x).strip().lower() if x is not None else "" for x in row]
        if "roll no" in row_strs and "student name" in row_strs:
            header_index = i
            headers = row_strs
            break
            
    if header_index is None:
        raise StudentExcelParseError("Could not find student roster header.")
        
    idx_cls = headers.index("class / batch") if "class / batch" in headers else -1
    idx_dept = headers.index("department") if "department" in headers else -1
    idx_sem = headers.index("semester") if "semester" in headers else -1
    
    idx_slno = headers.index("sl no") if "sl no" in headers else -1
    idx_adm = headers.index("admission no") if "admission no" in headers else -1
    idx_roll = headers.index("roll no") if "roll no" in headers else -1
    idx_reg = headers.index("university reg no") if "university reg no" in headers else -1
    idx_name = headers.index("student name") if "student name" in headers else -1
    idx_gender = headers.index("gender") if "gender" in headers else -1

    if idx_roll == -1 or idx_name == -1:
        raise StudentExcelParseError("Required columns (Roll No, Student Name) not found.")

    student_rows = rows[header_index + 1 :]
    students: list[StudentRecord] = []
    issues: list[str] = []
    seen_roll_numbers: dict[str, int] = {}
    
    class_names = set()
    departments = set()
    semesters = set()
    
    for row_number, row in enumerate(student_rows, start=header_index + 2):
        if not any(x is not None and str(x).strip() for x in row):
            continue
            
        def safe_get(idx):
            if idx != -1 and idx < len(row):
                return _clean_value(row[idx])
            return ""

        cls_val = safe_get(idx_cls)
        dept_val = safe_get(idx_dept)
        sem_val_str = safe_get(idx_sem)
        from exam_allocator.services.registration_service import parse_semester_flexible
        sem_val = parse_semester_flexible(sem_val_str) or parse_semester_flexible(cls_val) or 0
            
        sl_no = safe_get(idx_slno)
        adm_no = safe_get(idx_adm)
        roll_no = safe_get(idx_roll)
        reg_no = safe_get(idx_reg)
        name = safe_get(idx_name)
        gender = safe_get(idx_gender)
        
        if not roll_no:
            roll_no = (reg_no or adm_no).strip()
        if not roll_no:
            continue
            
        if not name:
            issues.append(f"Row {row_number} has no student name.")
            continue
            
        if roll_no in seen_roll_numbers:
            issues.append(f"Duplicate roll number '{roll_no}' at row {row_number}.")
        else:
            seen_roll_numbers[roll_no] = row_number
            
        if cls_val: class_names.add(cls_val)
        if dept_val: departments.add(dept_val)
        if sem_val: semesters.add(sem_val)
        
        st = StudentRecord(
            sl_no=sl_no,
            admission_no=adm_no,
            roll_number=roll_no,
            uni_reg_no=reg_no,
            name=name,
            gender=gender,
            class_name=cls_val,
            semester=sem_val,
            academic_year="" # No academic year in new format
        )
        students.append(st)
        
    final_cls = list(class_names)[0] if class_names else "Unknown"
    final_dept = list(departments)[0] if departments else "Unknown"
    final_sem = list(semesters)[0] if semesters else 0
    
    class_record = ClassRecord(
        class_name=final_cls,
        semester=final_sem,
        academic_year="",
        department_name=final_dept,
        students=students,
    )

    return class_record, students, issues


def _clean_value(value) -> str:
    """
    Convert Excel values to clean strings.

    This is deliberately conservative so we don't accidentally
    modify roll numbers or names.
    """

    if value is None:
        return ""

    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))

    return str(value).strip()