"""
PDF student-list parser.

Reads the PDF files uploaded for student lists.
Assumes one class per PDF file.
"""

from __future__ import annotations

import re
from pathlib import Path

import fitz  # PyMuPDF

from .student_parser import ClassRecord, StudentExtractionResult, StudentRecord


class StudentPDFParseError(Exception):
    """Raised when the student PDF cannot be parsed."""


def parse_student_pdf(pdf_path: str) -> StudentExtractionResult:
    """
    Parse a student list PDF file.

    Returns normalized class and student records.
    """
    path = Path(pdf_path)

    if not path.exists():
        raise StudentPDFParseError(f"File not found: {pdf_path}")

    if path.suffix.lower() != ".pdf":
        raise StudentPDFParseError(f"Unsupported file type: {path.suffix}")

    try:
        doc = fitz.open(path)
    except Exception as exc:
        raise StudentPDFParseError(f"Could not open PDF: {exc}") from exc

    issues: list[str] = []

    class_name = ""
    semester_str = ""
    semester = 0
    academic_year = ""
    department_name = ""
    
    students: list[StudentRecord] = []
    
    lines = []
    try:
        for page in doc:
            text = page.get_text()
            for line in text.split("\n"):
                clean_line = line.strip()
                if clean_line:
                    lines.append(clean_line)
    finally:
        doc.close()

    i = 0
    while i < len(lines):
        line = lines[i]

        # Extract Header info
        if line == "Department Name" and i + 1 < len(lines):
            department_name = lines[i+1]
            i += 2
            continue
        if line == "Class Name" and i + 1 < len(lines):
            class_name = lines[i+1]
            i += 2
            continue
        if line == "Course Duration" and i + 1 < len(lines):
            academic_year = lines[i+1].replace(" ", "")
            i += 2
            continue
        if line == "Current Semester" and i + 1 < len(lines):
            semester_str = lines[i+1]
            sem_lower = semester_str.lower()
            if "iind" in sem_lower or "2nd" in sem_lower:
                semester = 2
            elif "iiird" in sem_lower or "3rd" in sem_lower:
                semester = 3
            elif "ivth" in sem_lower or "4th" in sem_lower:
                semester = 4
            elif "vth" in sem_lower or "5th" in sem_lower:
                semester = 5
            elif "vith" in sem_lower or "6th" in sem_lower:
                semester = 6
            elif "viith" in sem_lower or "7th" in sem_lower:
                semester = 7
            elif "viiith" in sem_lower or "8th" in sem_lower:
                semester = 8
            elif "ixth" in sem_lower or "9th" in sem_lower:
                semester = 9
            elif "xth" in sem_lower or "10th" in sem_lower:
                semester = 10
            elif "ist" in sem_lower or "1st" in sem_lower:
                semester = 1
            else:
                sem_match = re.search(r"(\d+)", semester_str)
                if sem_match:
                    semester = int(sem_match.group(1))
                else:
                    semester = 1
            i += 2
            continue

        # Check for Student Row
        if i + 5 < len(lines) and re.match(r"^\d+$", line) and lines[i+5] in ["Male", "Female"]:
            sl_no = line
            admission_no = lines[i+1]
            roll_number = lines[i+2]
            uni_reg_no = lines[i+3]
            name = lines[i+4]
            gender = lines[i+5]
            
            student = StudentRecord(
                sl_no=sl_no,
                admission_no=admission_no,
                roll_number=roll_number,
                uni_reg_no=uni_reg_no,
                name=name,
                gender=gender,
                class_name=class_name,
                semester=semester,
                academic_year=academic_year,
            )
            students.append(student)
            i += 6
            continue
            
        i += 1

    if not class_name:
        issues.append("Could not find class name.")
    
    if not students:
        issues.append("No students found in the file.")
        
    class_record = ClassRecord(
        class_name=class_name,
        semester=semester,
        academic_year=academic_year,
        department_name=department_name,
        students=students,
    )

    return StudentExtractionResult(
        source_file=path.name,
        classes=[class_record],
        students=students,
        issues=issues,
    )
