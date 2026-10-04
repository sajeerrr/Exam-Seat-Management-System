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
    
    lines: list[str] = []
    table_students: list[StudentRecord] = []

    try:
        # 1. Extract text lines for metadata
        for page in doc:
            text = page.get_text()
            for line in text.split("\n"):
                clean_line = line.strip()
                if clean_line:
                    lines.append(clean_line)

        # 2. Extract students using table finder
        col_map = {"sl": 0, "adm": 1, "roll": 2, "reg": 3, "name": 4, "gender": 5}
        for page in doc:
            try:
                tf = page.find_tables()
                for t in tf.tables:
                    for r in t.extract():
                        if not r or len(r) < 4:
                            continue
                        row_str = [str(c or "").strip().lower() for c in r]
                        # Check if this row is a header row
                        if any("admission" in c for c in row_str) and any("name" in c for c in row_str):
                            for idx, c in enumerate(row_str):
                                if "sl" in c:
                                    col_map["sl"] = idx
                                elif "admission" in c:
                                    col_map["adm"] = idx
                                elif "roll" in c:
                                    col_map["roll"] = idx
                                elif "reg" in c or "university" in c:
                                    col_map["reg"] = idx
                                elif "name" in c:
                                    col_map["name"] = idx
                                elif "gender" in c:
                                    col_map["gender"] = idx
                            continue

                        # Check if this is a student row (sl_no is a positive integer)
                        sl_idx = col_map.get("sl", 0)
                        if sl_idx < len(r):
                            c_sl = str(r[sl_idx] or "").strip()
                            if c_sl.isdigit():
                                adm = str(r[col_map["adm"]] or "").strip() if col_map["adm"] < len(r) else ""
                                roll = str(r[col_map["roll"]] or "").strip() if col_map["roll"] < len(r) else ""
                                reg = str(r[col_map["reg"]] or "").strip() if col_map["reg"] < len(r) else ""
                                name = str(r[col_map["name"]] or "").replace("\n", " ").strip() if col_map["name"] < len(r) else ""
                                gender = str(r[col_map["gender"]] or "").strip() if col_map["gender"] < len(r) else ""

                                # Fallback roll number to uni_reg_no or admission_no if roll number is missing
                                eff_roll = roll or reg or adm or f"NO_ROLL_{c_sl}"

                                table_students.append(
                                    StudentRecord(
                                        sl_no=c_sl,
                                        admission_no=adm,
                                        roll_number=eff_roll,
                                        uni_reg_no=reg,
                                        name=name,
                                        gender=gender,
                                        class_name="",  # set after header parse
                                        semester=0,
                                        academic_year="",
                                    )
                                )
            except Exception:
                pass
    finally:
        doc.close()

    # Parse metadata from text lines
    i = 0
    while i < len(lines):
        line = lines[i]

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
            # Parse roman/ordinal semesters with longest/highest matches first to avoid submatch issues
            matched_sem = None
            roman_patterns = [
                (r"\b(?:x|10)th\b", 10),
                (r"\b(?:ix|9)th\b", 9),
                (r"\b(?:viii|8)th\b", 8),
                (r"\b(?:vii|7)th\b", 7),
                (r"\b(?:vi|6)th\b", 6),
                (r"\b(?:v|5)th\b", 5),
                (r"\b(?:iv|4)th\b", 4),
                (r"\b(?:iii|3)(?:rd|th)?\b", 3),
                (r"\b(?:ii|2)(?:nd|th)?\b", 2),
                (r"\b(?:i|1)(?:st|th)?\b", 1),
            ]
            for pat, val in roman_patterns:
                if re.search(pat, sem_lower):
                    matched_sem = val
                    break
            if matched_sem is not None:
                semester = matched_sem
            else:
                sem_match = re.search(r"(\d+)", semester_str)
                semester = int(sem_match.group(1)) if sem_match else 1
            i += 2
            continue
        i += 1

    # If table extraction succeeded, populate metadata into extracted students
    if table_students:
        for st in table_students:
            st.class_name = class_name
            st.semester = semester
            st.academic_year = academic_year
        students = table_students
    else:
        # Fallback to line-by-line parsing if table extraction found no students
        i = 0
        while i < len(lines):
            line = lines[i]

            if re.match(r"^\d+$", line):
                # Standard 6-token row: [sl_no, adm_no, roll_no, uni_reg, name, gender]
                if i + 5 < len(lines) and lines[i+5].capitalize() in ["Male", "Female"]:
                    sl_no = line
                    admission_no = lines[i+1]
                    roll_number = lines[i+2]
                    uni_reg_no = lines[i+3]
                    name = lines[i+4]
                    gender = lines[i+5]

                    eff_roll = roll_number or uni_reg_no or admission_no or f"NO_ROLL_{sl_no}"
                    students.append(
                        StudentRecord(
                            sl_no=sl_no,
                            admission_no=admission_no,
                            roll_number=eff_roll,
                            uni_reg_no=uni_reg_no,
                            name=name,
                            gender=gender,
                            class_name=class_name,
                            semester=semester,
                            academic_year=academic_year,
                        )
                    )
                    i += 6
                    continue

                # 5-token row (student without roll number): [sl_no, adm_no, uni_reg, name, gender]
                elif i + 4 < len(lines) and lines[i+4].capitalize() in ["Male", "Female"]:
                    sl_no = line
                    admission_no = lines[i+1]
                    uni_reg_no = lines[i+2]
                    name = lines[i+3]
                    gender = lines[i+4]

                    eff_roll = uni_reg_no or admission_no or f"NO_ROLL_{sl_no}"
                    students.append(
                        StudentRecord(
                            sl_no=sl_no,
                            admission_no=admission_no,
                            roll_number=eff_roll,
                            uni_reg_no=uni_reg_no,
                            name=name,
                            gender=gender,
                            class_name=class_name,
                            semester=semester,
                            academic_year=academic_year,
                        )
                    )
                    i += 5
                    continue

                # 7-token row (multi-word name split across 2 lines): [sl_no, adm_no, roll_no, uni_reg, name1, name2, gender]
                elif i + 6 < len(lines) and lines[i+6].capitalize() in ["Male", "Female"]:
                    sl_no = line
                    admission_no = lines[i+1]
                    roll_number = lines[i+2]
                    uni_reg_no = lines[i+3]
                    name = f"{lines[i+4]} {lines[i+5]}"
                    gender = lines[i+6]

                    eff_roll = roll_number or uni_reg_no or admission_no or f"NO_ROLL_{sl_no}"
                    students.append(
                        StudentRecord(
                            sl_no=sl_no,
                            admission_no=admission_no,
                            roll_number=eff_roll,
                            uni_reg_no=uni_reg_no,
                            name=name,
                            gender=gender,
                            class_name=class_name,
                            semester=semester,
                            academic_year=academic_year,
                        )
                    )
                    i += 7
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
