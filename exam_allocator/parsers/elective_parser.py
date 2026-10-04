"""
Elective list parser module.

Subject-centric elective parser for Excel (.xlsx, .xlsm, .xls) and PDF formats.
Groups students strictly according to their ACTUAL SUBJECT, not according to department.
Captures student roll number, name, department, class, source traceability,
duplicates, and unresolved records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from openpyxl import load_workbook

try:
    import pymupdf as fitz
except ImportError:
    try:
        import fitz
    except ImportError:
        fitz = None


class ElectiveExcelParseError(Exception):
    """Raised when elective files cannot be parsed."""


@dataclass
class ElectiveStudentRecord:
    roll_number: str
    student_name: str
    department: str = ""
    class_name: str = ""
    source_file: str = ""
    source_sheet_or_page: str = ""
    source_row: int | None = None
    is_unresolved: bool = False
    unresolved_reason: str = ""
    gender: str = ""
    uni_reg_no: str = ""


@dataclass
class ElectiveSubjectRecord:
    subject_code: str  # Normalized subject code
    subject_name: str
    original_subject_code: str = ""
    elective_type: str = ""
    students: list[ElectiveStudentRecord] = field(default_factory=list)
    unresolved_students: list[ElectiveStudentRecord] = field(default_factory=list)


@dataclass
class ElectiveGroupRecord:
    elective_label: str  # Elective Type (e.g. "Programme Elective III", "Programme Elective IV")
    department_code: str = ""
    department_name: str = ""
    subjects: list[ElectiveSubjectRecord] = field(default_factory=list)


@dataclass
class ElectiveParseReport:
    total_subjects: int = 0
    total_students: int = 0
    total_registrations: int = 0
    total_unresolved: int = 0
    total_duplicates: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class ElectiveExtractionResult:
    source_file: str
    groups: list[ElectiveGroupRecord]
    subjects: list[ElectiveSubjectRecord] = field(default_factory=list)
    report: ElectiveParseReport = field(default_factory=ElectiveParseReport)
    issues: list[str] = field(default_factory=list)


# --- Helper Functions & Normalization ---

ROLL_REGEX = re.compile(
    r"^(?:B\d{2}[A-Z]{2,4}\d{1,4}|[A-Z]{3}\d{2}[A-Z]{2,4}\d{1,4}|L\d{2}[A-Z]{2,4}\d{1,4}|B21MC\d{3})$",
    re.IGNORECASE,
)

KNOWN_SUBJECT_MAP = {
    "DEEP LEARNING": ("22CSE802.1", "DEEP LEARNING", "Programme Elective III"),
    "SMART GRID TECHNOLOGIES": ("22EEE802.3", "SMART GRID TECHNOLOGIES", "Programme Elective III"),
    "DATA MINING": ("22CSE803.5", "DATA MINING", "Programme Elective IV"),
    "SPECIAL ELECTRIC MACHINES": ("22EEE803.2", "SPECIAL ELECTRICAL MACHINES", "Programme Elective IV"),
    "SPECIAL ELECTRICAL MACHINES": ("22EEE803.2", "SPECIAL ELECTRICAL MACHINES", "Programme Elective IV"),
    "AIRPOLLUTION MONITORING & CONTROL": ("22CHE802.4", "AIR QUALITY MANAGEMENT", "Programme Elective III"),
}


def normalize_subject_code(raw_code: str) -> str:
    """Normalize subject code by stripping prefixes, whitespace around dots/hyphens, and extra spaces."""
    if not raw_code:
        return ""
    code = raw_code.strip()
    # Strip prefixes like Sub:, Course:, Subject:
    code = re.sub(r"^(?:sub|course|subject)\s*[:]\s*", "", code, flags=re.IGNORECASE).strip()
    # Replace internal spaces inside course codes e.g. "22ECE 803.2" -> "22ECE803.2", "22-ECE-803.2" -> "22ECE803.2"
    m = re.match(r"^(\d{2})[- ]*([A-Za-z]{2,5})[- ]*(\d{3}(?:\.\d+[A-Za-z_]*)?)$", code)
    if m:
        code = f"{m.group(1)}{m.group(2).upper()}{m.group(3)}"
    else:
        # Standardize spaces around dots
        code = re.sub(r"\s*\.\s*", ".", code)
        code = re.sub(r"\s+", " ", code).strip()
    return code.upper()


def split_subject_header(s: str) -> tuple[str, str, str]:
    """
    Split subject string into (original_subject_code, normalized_subject_code, subject_name).
    E.g. '22ECE 803.2  REAL TIME OPERATING SYSTEMS' ->
         ('22ECE 803.2', '22ECE803.2', 'REAL TIME OPERATING SYSTEMS')
    """
    s = s.strip()
    # Remove leading "Student List -" if present
    s = re.sub(r"^STUDENT\s+LIST\s*[-:]?\s*", "", s, flags=re.IGNORECASE).strip()
    if s.lower().startswith("sub:"):
        s = s[4:].strip()

    # Pattern: course code followed by separator and subject name
    m = re.match(r"^([0-9]{2}[A-Za-z]{2,5}\s*[0-9\._A-Za-z]+)\s*[-:]\s*(.+)$", s)
    if m:
        orig_code = m.group(1).strip()
        norm_code = normalize_subject_code(orig_code)
        name = m.group(2).strip()
        return orig_code, norm_code, name

    # Pattern without separator e.g. "22ECE802.7 ENTREPRENEURSHIP"
    m2 = re.match(r"^([0-9]{2}[A-Za-z]{2,5}\s*[0-9\._A-Za-z]+)\s+([A-Za-z].+)$", s)
    if m2:
        orig_code = m2.group(1).strip()
        norm_code = normalize_subject_code(orig_code)
        name = m2.group(2).strip()
        return orig_code, norm_code, name

    # Check known subject lookup
    norm_upper = s.upper().strip()
    if norm_upper in KNOWN_SUBJECT_MAP:
        code, name, _ = KNOWN_SUBJECT_MAP[norm_upper]
        return code, code, name

    # If starts with standard code alone
    m3 = re.match(r"^([0-9]{2}[A-Za-z]{2,5}\s*[0-9\._A-Za-z]+)$", s)
    if m3:
        orig_code = m3.group(1).strip()
        norm_code = normalize_subject_code(orig_code)
        return orig_code, norm_code, norm_code

    clean_s = s.strip()
    norm_c = normalize_subject_code(clean_s)
    return clean_s, norm_c, clean_s


def derive_elective_type(sub_code: str, context: str = "") -> str:
    """
    Derive elective type (Programme Elective III, IV, Architecture Elective, etc.)
    from subject code or text context (sheet name, file name, banner).
    """
    ctx = context.upper()
    sub = sub_code.upper().replace(" ", "")

    if "PE-III" in ctx or "PE_III" in ctx or "PROGRAMME ELECTIVE III" in ctx or "PROGRAM ELECTIVE III" in ctx:
        return "Programme Elective III"
    if "PE-IV" in ctx or "PE_IV" in ctx or "PROGRAMME ELECTIVE IV" in ctx or "PROGRAM ELECTIVE IV" in ctx:
        return "Programme Elective IV"
    if "PE-V" in ctx or "PE_V" in ctx or "PROGRAMME ELECTIVE V" in ctx or "PROGRAM ELECTIVE V" in ctx:
        return "Programme Elective V"
    if "ELECTIVE 1" in ctx or "ELECTIVE I" in ctx:
        return "Elective I"
    if "ELECTIVE 2" in ctx or "ELECTIVE II" in ctx:
        return "Elective II"
    if "ELECTIVE 3" in ctx or "ELECTIVE III" in ctx:
        return "Elective III"
    if "ARCH" in ctx or "22ARE" in sub:
        return "Architecture Elective"
    if "MINOR" in ctx:
        return "Minor"
    if "HONOURS" in ctx:
        return "Honours"

    # From course number in code: 801->PE II / Arch, 802->PE III, 803->PE IV, 804->PE V
    m = re.search(r"\d{2}[A-Z]{2,4}(\d{3})", sub)
    if m:
        num = int(m.group(1))
        if num == 801:
            return "Architecture Elective" if "ARE" in sub else "Programme Elective II"
        elif num == 802:
            return "Programme Elective III"
        elif num == 803:
            return "Programme Elective IV"
        elif num == 804:
            return "Programme Elective V"

    return "Programme Elective"


def derive_dept_from_roll(roll: str) -> str:
    """Derive department code from student roll number prefix."""
    r = roll.upper().replace(" ", "")
    # Standard TKM/Kerala patterns: B22ECA01, B22ECB05, B22MEA29, B22CSA04, etc.
    m = re.search(r"B\d{2}([A-Z]{2})", r)
    if m:
        code = m.group(1)
        mapping = {
            "EC": "EC",
            "CS": "CSE",
            "ME": "ME",
            "EE": "EEE",
            "ER": "EL",
            "CE": "CE",
            "CH": "CHE",
            "AR": "B.ARCH",
        }
        if code in mapping:
            return mapping[code]

    # University register pattern: TKM22CS080, KTE21AR004, etc.
    m_tkm = re.search(r"[A-Z]{3}\d{2}([A-Z]{2,3})", r)
    if m_tkm:
        code = m_tkm.group(1)
        mapping_tkm = {
            "CS": "CSE",
            "EC": "EC",
            "ME": "ME",
            "EE": "EEE",
            "EL": "EL",
            "CE": "CE",
            "CH": "CHE",
            "AR": "B.ARCH",
        }
        if code in mapping_tkm:
            return mapping_tkm[code]

    if r.startswith("B21MC"):
        return "ME"

    return ""


def derive_class_name(roll: str, sheet_name: str = "", context: str = "") -> str:
    """Derive student class name e.g. ECE 2K22 A, ME 2K22 B, CHE 2K22."""
    r = roll.upper().replace(" ", "")
    m = re.search(r"B(\d{2})([A-Z]{2})([A-C]?)", r)
    if m:
        year_str = f"2K{m.group(1)}"
        dept_str = m.group(2)
        sec_str = m.group(3)
        dept_names = {
            "EC": "ECE",
            "CS": "CSE",
            "ME": "ME",
            "EE": "EEE",
            "ER": "EL",
            "CE": "CE",
            "CH": "CHE",
            "AR": "B.Arch",
        }
        dept_display = dept_names.get(dept_str, dept_str)
        if sec_str:
            return f"{dept_display} {year_str} {sec_str}".strip()
        else:
            return f"{dept_display} {year_str}".strip()

    # From sheet name: e.g. "A" in ME file -> "ME 2K22 A"
    s = sheet_name.strip().upper()
    if s in {"A", "B", "C"}:
        return f"ME 2K22 {s}"
    if "PE_IIIA" in s or "PE-IVA" in s:
        return "ECE 2K22 A"
    if "PE-IIIB" in s or "PE-IVB" in s:
        return "ECE 2K22 B"

    return ""


def clean_roll_number(val: str) -> str:
    """Normalize roll number: uppercase, remove internal spaces and punctuation."""
    if not val:
        return ""
    r = str(val).strip().upper()
    r = re.sub(r"\s+", "", r)
    return r


def clean_student_name(val: str) -> str:
    """Clean student name: preserve letters and initials, normalize whitespace."""
    if not val:
        return ""
    name = str(val).strip()
    name = re.sub(r"\s+", " ", name)
    return name


def is_valid_roll_number(val: str) -> bool:
    """Check if value matches student roll number pattern."""
    if not val:
        return False
    r = clean_roll_number(val)
    if len(r) < 6 or len(r) > 16:
        return False
    # Avoid header keywords or numbers
    if r.isdigit() or r in {"ROLLNO", "SLNO", "NAME", "STUDENTNAME", "CLASSNAME"}:
        return False
    return bool(ROLL_REGEX.match(r))


def detect_subject_banner(val: str) -> tuple[str, str, str] | None:
    """
    Check if a string represents an elective subject banner.
    Returns (orig_code, norm_code, name) or None.
    """
    if not val:
        return None
    s = str(val).strip()
    if len(s) < 3 or len(s) > 120:
        return None

    # Never treat a student roll number as a subject banner
    if is_valid_roll_number(s):
        return None

    # Skip table header lines and college headers
    lower_s = s.lower()
    if lower_s in {"roll no", "name", "student name", "sl no", "sl.no.", "uni reg no", "sl. no."}:
        return None
    if "tkm college" in lower_s or "karicode" in lower_s or "report taken on" in lower_s:
        return None

    # Check for course code: e.g. 22***80* or Sub:
    if re.search(r"(?:^|[\s\-_:])(?:22[A-Za-z]{2,4}\s*80[0-9](?:\.[0-9]+[A-Za-z_]*)?)", s, re.IGNORECASE):
        orig, norm, name = split_subject_header(s)
        return orig, norm, name

    # Check Sub: prefix
    if s.lower().startswith("sub:"):
        orig, norm, name = split_subject_header(s)
        return orig, norm, name

    # Check known subject names
    s_upper = s.upper()
    if s_upper in KNOWN_SUBJECT_MAP:
        orig, norm, name = split_subject_header(s)
        return orig, norm, name

    return None


# --- Core Parser Functions ---


def parse_elective_file(file_path: str) -> ElectiveExtractionResult:
    """
    Parse an elective file (Excel or PDF) and return normalized, subject-grouped extraction results.
    """
    path = Path(file_path)
    if not path.exists():
        raise ElectiveExcelParseError(f"File not found: {file_path}")

    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return _parse_elective_excel(path)
    elif suffix == ".pdf":
        return _parse_elective_pdf(path)
    else:
        raise ElectiveExcelParseError(f"Unsupported file format: {suffix}")


def _parse_elective_excel(path: Path) -> ElectiveExtractionResult:
    try:
        workbook = load_workbook(filename=path, data_only=True)
    except Exception as exc:
        raise ElectiveExcelParseError(f"Could not open Excel workbook: {exc}") from exc

    subject_map: dict[str, ElectiveSubjectRecord] = {}
    report = ElectiveParseReport()
    issues: list[str] = []

    try:
        for worksheet in workbook.worksheets:
            title = worksheet.title.strip()
            # Skip summary/overview sheets
            if title.lower() in {"summary", "master overview", "overview", "sheet2", "sheet3"} and worksheet.max_row <= 6:
                continue

            try:
                _parse_excel_sheet(worksheet, path.name, subject_map, report, issues)
            except Exception as exc:
                issues.append(f"Sheet '{title}': {exc}")
    finally:
        workbook.close()

    if not subject_map:
        raise ElectiveExcelParseError(f"No valid elective student records found in '{path.name}'.")

    # Group subjects by elective type
    groups = _group_subjects_by_elective_type(list(subject_map.values()))

    # Update summary counts
    report.total_subjects = len(subject_map)
    total_reg = sum(len(s.students) for s in subject_map.values())
    unique_students = len({st.roll_number for s in subject_map.values() for st in s.students})
    report.total_registrations = total_reg
    report.total_students = unique_students

    return ElectiveExtractionResult(
        source_file=path.name,
        groups=groups,
        subjects=list(subject_map.values()),
        report=report,
        issues=issues + report.warnings,
    )


def _parse_excel_sheet(
    worksheet,
    file_name: str,
    subject_map: dict[str, ElectiveSubjectRecord],
    report: ElectiveParseReport,
    issues: list[str],
) -> None:
    sheet_title = worksheet.title.strip()
    rows = list(worksheet.iter_rows(values_only=True))
    if not rows:
        return

    # 1. Check if this is an explicit multi-column format (e.g. File1.xlsx: Dept | Elective Group | Subject Code | ...)
    header_row_idx = None
    col_map = {}
    for r_idx, row in enumerate(rows[:10]):
        vals = [str(c).strip().lower() for c in row if c is not None]
        if "subject code" in vals or ("roll no" in vals and "student name" in vals):
            header_row_idx = r_idx
            for c_idx, cell in enumerate(row):
                if cell is not None:
                    clow = str(cell).strip().lower()
                    if "subject code" in clow or "course code" in clow:
                        col_map["sub_code"] = c_idx
                    elif "subject name" in clow or "course name" in clow:
                        col_map["sub_name"] = c_idx
                    elif "roll no" in clow or "roll_no" in clow:
                        col_map["roll_no"] = c_idx
                    elif "student name" in clow or "name" in clow:
                        col_map["name"] = c_idx
                    elif "department" in clow or "dept" in clow:
                        col_map["dept"] = c_idx
                    elif "elective group" in clow or "elective type" in clow:
                        col_map["elective_type"] = c_idx
                    elif "class" in clow:
                        col_map["class_name"] = c_idx
            break

    # If explicit columnar table with subject code on every row
    if header_row_idx is not None and "sub_code" in col_map and "roll_no" in col_map:
        for r_num, row in enumerate(rows[header_row_idx + 1:], start=header_row_idx + 2):
            if not any(row):
                continue
            raw_code = str(row[col_map["sub_code"]]).strip() if col_map.get("sub_code") is not None and row[col_map["sub_code"]] else ""
            raw_name = str(row[col_map["sub_name"]]).strip() if col_map.get("sub_name") is not None and row[col_map["sub_name"]] else ""
            raw_roll = str(row[col_map["roll_no"]]).strip() if col_map.get("roll_no") is not None and row[col_map["roll_no"]] else ""
            raw_sname = str(row[col_map["name"]]).strip() if col_map.get("name") is not None and row[col_map["name"]] else ""
            raw_etype = str(row[col_map["elective_type"]]).strip() if col_map.get("elective_type") is not None and row[col_map["elective_type"]] else ""

            if not raw_roll or not is_valid_roll_number(raw_roll):
                continue

            orig_code, norm_code, sname = split_subject_header(raw_code)
            if raw_name:
                sname = raw_name
            etype = raw_etype or derive_elective_type(norm_code, f"{file_name} {sheet_title}")
            roll = clean_roll_number(raw_roll)
            s_name = clean_student_name(raw_sname) or roll
            dept = derive_dept_from_roll(roll)
            c_name = derive_class_name(roll, sheet_title)

            _add_student_to_subject(
                subject_map=subject_map,
                report=report,
                orig_code=orig_code,
                norm_code=norm_code,
                subject_name=sname,
                elective_type=etype,
                roll=roll,
                name=s_name,
                dept=dept,
                class_name=c_name,
                source_file=file_name,
                sheet_or_page=sheet_title,
                row_idx=r_num,
            )
        return

    # 2. Check if this is an EL.xlsx style sheet where Subject Name is in column 4 (PROGRAM ELECTIVE III/IV)
    is_col4_subject_sheet = False
    col4_subject_idx = -1
    col_roll_idx = -1
    col_name_idx = -1

    for r_idx, row in enumerate(rows[:8]):
        has_elective_col = any("program elective" in str(c).lower() or "programme elective" in str(c).lower() for c in row if c is not None)
        has_roll_col = any("roll no" in str(c).lower() for c in row if c is not None)
        if has_elective_col and has_roll_col:
            is_col4_subject_sheet = True
            header_row_idx = r_idx
            for c_idx, cell in enumerate(row):
                if cell is not None:
                    clow = str(cell).strip().lower()
                    if "program elective" in clow or "programme elective" in clow:
                        col4_subject_idx = c_idx
                    elif "roll no" in clow:
                        col_roll_idx = c_idx
                    elif clow == "name" or "student name" in clow:
                        col_name_idx = c_idx
            break

    if is_col4_subject_sheet and col_roll_idx != -1 and col4_subject_idx != -1:
        # Each row defines its subject in column col4_subject_idx!
        for r_num, row in enumerate(rows[header_row_idx + 1:], start=header_row_idx + 2):
            if not any(row):
                continue
            val_roll = str(row[col_roll_idx]).strip() if col_roll_idx < len(row) and row[col_roll_idx] is not None else ""
            val_name = str(row[col_name_idx]).strip() if col_name_idx != -1 and col_name_idx < len(row) and row[col_name_idx] is not None else ""
            val_sub = str(row[col4_subject_idx]).strip() if col4_subject_idx < len(row) and row[col4_subject_idx] is not None else ""

            if not is_valid_roll_number(val_roll):
                continue

            orig_code, norm_code, sub_title = split_subject_header(val_sub)
            etype = derive_elective_type(norm_code, f"{file_name} {sheet_title} {rows[header_row_idx][col4_subject_idx]}")
            roll = clean_roll_number(val_roll)
            s_name = clean_student_name(val_name) or roll
            dept = derive_dept_from_roll(roll)
            c_name = derive_class_name(roll, sheet_title)

            _add_student_to_subject(
                subject_map=subject_map,
                report=report,
                orig_code=orig_code,
                norm_code=norm_code,
                subject_name=sub_title,
                elective_type=etype,
                roll=roll,
                name=s_name,
                dept=dept,
                class_name=c_name,
                source_file=file_name,
                sheet_or_page=sheet_title,
                row_idx=r_num,
            )
        return

    # 3. Standard sequential banner block format (EC.xlsx, ME.xlsx, CSE.xlsx, CE.xlsx, EEE.xlsx)
    # Check if sheet title itself is a subject banner (e.g. CE PE-IV sheet name)
    current_orig_code = ""
    current_norm_code = ""
    current_sub_name = ""
    current_etype = derive_elective_type("", f"{file_name} {sheet_title}")

    sheet_banner = detect_subject_banner(sheet_title)
    if sheet_banner:
        current_orig_code, current_norm_code, current_sub_name = sheet_banner
        current_etype = derive_elective_type(current_norm_code, f"{file_name} {sheet_title}")

    roll_col = -1
    name_col = -1

    for r_num, row in enumerate(rows, start=1):
        # Non-empty cell values
        str_cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
        if not str_cells:
            continue

        # Check if row is a column header (e.g. "Roll No", "Name", "Sl No")
        row_lowers = [str(c).strip().lower() if c is not None else "" for c in row]
        if any("roll no" in s for s in row_lowers) or (any("name" in s for s in row_lowers) and any("sl" in s for s in row_lowers)):
            for idx, c in enumerate(row_lowers):
                if "roll no" in c or "roll_no" in c:
                    roll_col = idx
                elif c == "name" or "student name" in c:
                    name_col = idx
            continue

        # Check if row contains a subject banner
        found_banner = None
        for c in row:
            if c is not None:
                b = detect_subject_banner(str(c))
                if b:
                    found_banner = b
                    break

        if found_banner:
            current_orig_code, current_norm_code, current_sub_name = found_banner
            current_etype = derive_elective_type(current_norm_code, f"{file_name} {sheet_title} {current_sub_name}")
            # Reset header column indices for next block if needed
            continue

        # Check if row has a student roll number
        found_roll = ""
        found_name = ""

        if roll_col != -1 and roll_col < len(row) and is_valid_roll_number(str(row[roll_col])):
            found_roll = clean_roll_number(str(row[roll_col]))
            if name_col != -1 and name_col < len(row) and row[name_col] is not None:
                found_name = clean_student_name(str(row[name_col]))
        else:
            # Fallback search across row cells for roll number pattern
            for idx, c in enumerate(row):
                if c is not None and is_valid_roll_number(str(c)):
                    found_roll = clean_roll_number(str(c))
                    # Student name is typically in another string cell on the row
                    for n_idx, nc in enumerate(row):
                        if n_idx != idx and nc is not None:
                            ns = str(nc).strip()
                            if len(ns) > 2 and not ns.isdigit() and not is_valid_roll_number(ns) and not ns.startswith("TKM22"):
                                found_name = clean_student_name(ns)
                                break
                    break

        if found_roll:
            if not current_norm_code:
                # Unresolved student: found roll number but no subject is active
                report.total_unresolved += 1
                warn = f"Unresolved student {found_roll} (row {r_num} in '{sheet_title}'): No active elective subject detected."
                report.warnings.append(warn)
                continue

            dept = derive_dept_from_roll(found_roll)
            c_name = derive_class_name(found_roll, sheet_title)

            _add_student_to_subject(
                subject_map=subject_map,
                report=report,
                orig_code=current_orig_code or current_norm_code,
                norm_code=current_norm_code,
                subject_name=current_sub_name or current_norm_code,
                elective_type=current_etype,
                roll=found_roll,
                name=found_name or found_roll,
                dept=dept,
                class_name=c_name,
                source_file=file_name,
                sheet_or_page=sheet_title,
                row_idx=r_num,
            )


def _parse_elective_pdf(path: Path) -> ElectiveExtractionResult:
    if fitz is None:
        raise ElectiveExcelParseError("PyMuPDF (fitz) is required to parse PDF elective files.")

    try:
        doc = fitz.open(str(path))
    except Exception as exc:
        raise ElectiveExcelParseError(f"Could not open PDF file: {exc}") from exc

    subject_map: dict[str, ElectiveSubjectRecord] = {}
    report = ElectiveParseReport()
    issues: list[str] = []

    try:
        current_orig_code = ""
        current_norm_code = ""
        current_sub_name = ""
        current_etype = derive_elective_type("", path.name)

        for page_idx, page in enumerate(doc, start=1):
            page_text = page.get_text()

            # Check if page has a subject banner
            m_page = re.search(
                r"(?:STUDENT LIST\s*[-]?\s*)?([0-9]{2}[A-Za-z]{2,5}\s*[0-9\._A-Za-z]+)\s*[-:]\s*([A-Za-z\s&_]+)",
                page_text,
                re.IGNORECASE,
            )
            if m_page:
                current_orig_code = m_page.group(1).strip()
                current_norm_code = normalize_subject_code(current_orig_code)
                current_sub_name = m_page.group(2).strip()
                current_etype = derive_elective_type(current_norm_code, f"{path.name} {current_sub_name}")

            # Check tables
            tabs = page.find_tables()
            if tabs.tables:
                for t in tabs.tables:
                    data = t.extract()
                    for r_num, row in enumerate(data, start=1):
                        vals = [str(c).strip() for c in row if c is not None and str(c).strip()]
                        if not vals:
                            continue

                        # Check if row is subject banner
                        for v in vals:
                            b = detect_subject_banner(v)
                            if b:
                                current_orig_code, current_norm_code, current_sub_name = b
                                current_etype = derive_elective_type(current_norm_code, f"{path.name} {current_sub_name}")
                                break

                        # Find roll number and name
                        found_roll = ""
                        found_name = ""
                        for idx, v in enumerate(vals):
                            if is_valid_roll_number(v):
                                found_roll = clean_roll_number(v)
                                for n_idx, nv in enumerate(vals):
                                    if n_idx != idx and len(nv) > 2 and not nv.isdigit() and not is_valid_roll_number(nv) and not nv.startswith("TKM22"):
                                        found_name = clean_student_name(nv)
                                        break
                                break

                        if found_roll:
                            if not current_norm_code:
                                report.total_unresolved += 1
                                warn = f"Unresolved student {found_roll} on page {page_idx}: No active elective subject detected."
                                report.warnings.append(warn)
                                continue

                            dept = derive_dept_from_roll(found_roll)
                            c_name = derive_class_name(found_roll, "", f"Page {page_idx}")

                            _add_student_to_subject(
                                subject_map=subject_map,
                                report=report,
                                orig_code=current_orig_code or current_norm_code,
                                norm_code=current_norm_code,
                                subject_name=current_sub_name or current_norm_code,
                                elective_type=current_etype,
                                roll=found_roll,
                                name=found_name or found_roll,
                                dept=dept,
                                class_name=c_name,
                                source_file=path.name,
                                sheet_or_page=f"Page {page_idx}",
                                row_idx=r_num,
                            )
            else:
                # Text-line based extraction
                lines = [l.strip() for l in page_text.splitlines() if l.strip()]
                for l_idx, line in enumerate(lines):
                    b = detect_subject_banner(line)
                    if b:
                        current_orig_code, current_norm_code, current_sub_name = b
                        current_etype = derive_elective_type(current_norm_code, f"{path.name} {current_sub_name}")
                        continue

                    if is_valid_roll_number(line):
                        found_roll = clean_roll_number(line)
                        found_name = ""
                        # Next line might be student name
                        if l_idx + 1 < len(lines):
                            cand = lines[l_idx + 1]
                            if not is_valid_roll_number(cand) and not cand.isdigit() and len(cand) > 2:
                                found_name = clean_student_name(cand)

                        if not current_norm_code:
                            report.total_unresolved += 1
                            warn = f"Unresolved student {found_roll} on page {page_idx}: No active elective subject detected."
                            report.warnings.append(warn)
                            continue

                        dept = derive_dept_from_roll(found_roll)
                        c_name = derive_class_name(found_roll, "", f"Page {page_idx}")

                        _add_student_to_subject(
                            subject_map=subject_map,
                            report=report,
                            orig_code=current_orig_code or current_norm_code,
                            norm_code=current_norm_code,
                            subject_name=current_sub_name or current_norm_code,
                            elective_type=current_etype,
                            roll=found_roll,
                            name=found_name or found_roll,
                            dept=dept,
                            class_name=c_name,
                            source_file=path.name,
                            sheet_or_page=f"Page {page_idx}",
                            row_idx=l_idx + 1,
                        )
    finally:
        doc.close()

    if not subject_map:
        raise ElectiveExcelParseError(f"No valid elective student records found in '{path.name}'.")

    groups = _group_subjects_by_elective_type(list(subject_map.values()))
    report.total_subjects = len(subject_map)
    total_reg = sum(len(s.students) for s in subject_map.values())
    unique_students = len({st.roll_number for s in subject_map.values() for st in s.students})
    report.total_registrations = total_reg
    report.total_students = unique_students

    return ElectiveExtractionResult(
        source_file=path.name,
        groups=groups,
        subjects=list(subject_map.values()),
        report=report,
        issues=issues + report.warnings,
    )


def _add_student_to_subject(
    subject_map: dict[str, ElectiveSubjectRecord],
    report: ElectiveParseReport,
    orig_code: str,
    norm_code: str,
    subject_name: str,
    elective_type: str,
    roll: str,
    name: str,
    dept: str,
    class_name: str,
    source_file: str,
    sheet_or_page: str,
    row_idx: int,
) -> None:
    """Add student to subject map with duplicate detection and normalization."""
    if norm_code not in subject_map:
        subject_map[norm_code] = ElectiveSubjectRecord(
            subject_code=norm_code,
            original_subject_code=orig_code,
            subject_name=subject_name,
            elective_type=elective_type,
            students=[],
            unresolved_students=[],
        )

    subj = subject_map[norm_code]

    # Check for duplicate registration in this subject
    if any(s.roll_number == roll for s in subj.students):
        report.total_duplicates += 1
        warn = f"Duplicate student '{roll}' ({name}) skipped in subject '{norm_code}' ({source_file}:{sheet_or_page} row {row_idx})."
        report.warnings.append(warn)
        return

    student_rec = ElectiveStudentRecord(
        roll_number=roll,
        student_name=name,
        department=dept,
        class_name=class_name,
        source_file=source_file,
        source_sheet_or_page=sheet_or_page,
        source_row=row_idx,
    )
    subj.students.append(student_rec)


def _group_subjects_by_elective_type(subjects: list[ElectiveSubjectRecord]) -> list[ElectiveGroupRecord]:
    """Group subjects by their Elective Type (e.g. Programme Elective III, IV)."""
    groups_dict: dict[str, ElectiveGroupRecord] = {}
    for s in subjects:
        etype = s.elective_type or "Programme Elective"
        if etype not in groups_dict:
            groups_dict[etype] = ElectiveGroupRecord(
                elective_label=etype,
                department_code="ELECTIVE",
                department_name="Electives",
                subjects=[],
            )
        groups_dict[etype].subjects.append(s)
    return list(groups_dict.values())
