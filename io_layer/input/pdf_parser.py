# io_layer/input/pdf_parser.py
"""
Parses TKM College of Engineering class-list PDFs into Student objects.

Expected PDF structure (as produced by the college system):
  Table 0 – metadata:  Department Name | <value>
                        Class Name      | <value>   e.g. "CE 2K23A"
                        Current Semester| <value>   e.g. "VIth Semester"
  Table 1 – students:  Sl.No. | Admission No | Roll No | Uni Reg No | Name | Gender

The parser infers department, semester, and section from the metadata table.
Subject code, exam date, and session are injected externally via a
SessionFilter / timetable lookup — the PDF itself doesn't carry that data.
"""

import logging
import re
from pathlib import Path

import pdfplumber

from engine.models.student import Student

logger = logging.getLogger(__name__)

# Roman numeral → integer conversion for semester
_ROMAN = {
    "I": 1, "II": 2, "III": 3, "IV": 4,
    "V": 5, "VI": 6, "VII": 7, "VIII": 8,
    "IX": 9, "X": 10,
}

# Regex to extract section letter from class name like "CE 2K23A" → "A"
_SECTION_RE = re.compile(r"[A-Z]$")

# Maps abbreviated department codes in class names to canonical dept codes
_DEPT_MAP = {
    "CE": "CE", "ME": "ME", "EE": "EE", "EC": "EC",
    "CS": "CS", "CH": "CH", "EL": "EL",
    "B.ARCH": "AR", "ARCH": "AR",
}


def _parse_semester(raw: str) -> int:
    """Convert 'VIth Semester' → 6."""
    raw = raw.strip().upper()
    for roman, value in sorted(_ROMAN.items(), key=lambda x: -len(x[0])):
        if raw.startswith(roman):
            return value
    return 0


def _parse_class_name(class_name: str) -> tuple[str, str]:
    """
    Parse 'CE 2K23A' → ('CE', 'A').
    Returns (department, section).
    """
    class_name = class_name.strip()
    match = _SECTION_RE.search(class_name)
    section = match.group() if match else "A"
    dept_raw = class_name.split()[0].upper()
    department = _DEPT_MAP.get(dept_raw, dept_raw)
    return department, section


class PDFParser:
    """
    Parses one student class-list PDF file into a list of Student objects.

    Usage
    -----
    students = PDFParser().parse("resources/CE 2K23A.pdf")
    """

    def parse(self, filepath: str | Path) -> list[Student]:
        filepath = Path(filepath)
        logger.info("Parsing student PDF: %s", filepath.name)

        students: list[Student] = []

        with pdfplumber.open(filepath) as pdf:
            meta: dict[str, str] = {}
            raw_student_rows: list[list] = []
            header_found = False

            for page in pdf.pages:
                tables = page.extract_tables()

                for table in tables:
                    for row in table:
                        if not row or all(c is None or str(c).strip() == "" for c in row):
                            continue

                        if len(row) == 2 and row[0] and row[1]:
                            key = str(row[0]).strip()
                            val = str(row[1]).strip()
                            meta[key] = val

                        elif row[0] and str(row[0]).strip().lower() == "sl.no.":
                            header_found = True

                        elif header_found and row[0] and str(row[0]).strip().isdigit():
                            raw_student_rows.append(row)

        class_name   = meta.get("Class Name", "UNKNOWN")
        semester_str = meta.get("Current Semester", "")
        department, section = _parse_class_name(class_name)
        semester = _parse_semester(semester_str)

        logger.info(
            "Metadata → dept=%s  section=%s  semester=%d  students_found=%d",
            department, section, semester, len(raw_student_rows),
        )

        for row in raw_student_rows:
            try:
                roll_no     = str(row[2]).strip()   # College Roll No  e.g. B23CEA01
                register_no = str(row[3]).strip()   # Uni Reg No       e.g. TKM23CE002
                name        = str(row[4]).strip()

                student = Student(
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
                )
                students.append(student)
            except (IndexError, AttributeError) as exc:
                logger.warning("Skipping malformed row %s: %s", row, exc)

        logger.info("Parsed %d students from %s", len(students), filepath.name)
        return students


class MultiplePDFParser:
    """
    Parses all student PDFs in a directory.

    Usage
    -----
    students = MultiplePDFParser().parse_directory("resources/")
    """

    def parse_directory(self, directory: str | Path) -> list[Student]:
        directory = Path(directory)
        all_students: list[Student] = []

        pdf_files = [
            f for f in directory.iterdir()
            if f.suffix.lower() == ".pdf"
            and not any(keyword in f.name.lower() for keyword in
                        ["exam", "timetable", "time table", "series", "revised"])
        ]

        logger.info("Found %d student PDFs in %s", len(pdf_files), directory)

        parser = PDFParser()
        for pdf_file in sorted(pdf_files):
            students = parser.parse(pdf_file)
            all_students.extend(students)

        logger.info("Total students parsed: %d", len(all_students))
        return all_students
