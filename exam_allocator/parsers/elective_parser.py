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
    r"^(?:[A-Z]?\d{2}[A-Z]{2,4}\d{1,4}|[A-Z]{2,4}\d{2}[A-Z]{2,4}\d{1,4}|B21MC\d{3}|[A-Z]{1,3}\d{4,8})$",
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
    # Strip trailing decorative underscores or whitespace
    code = re.sub(r"[\s_]+$", "", code).strip()
    # Replace internal spaces inside course codes e.g. "22ECE 803.2" -> "22ECE803.2", "22-ECE-803.2" -> "22ECE803.2", "22MEE802.1 B" -> "22MEE802.1_B"
    m = re.match(r"^(\d{2})[- ]*([A-Za-z]{2,5})[- ]*(\d{3}(?:\.\d+[A-Za-z0-9_]*)?)(?:[ _]([A-Za-z0-9]+))?$", code)
    if m:
        base = f"{m.group(1)}{m.group(2).upper()}{m.group(3)}"
        if m.group(4):
            base = f"{base}_{m.group(4).upper()}"
        code = base
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
    if not s:
        return "", "", ""
    # Normalize unicode dashes and replacement chars often found in PDFs
    s = str(s).replace('\ufffd', '-')
    s = re.sub(r'[\u2013\u2014\u2212]', '-', s)
    # Normalize internal newlines and whitespace
    s = re.sub(r"[\r\n]+", " ", s).strip()
    # Strip enclosing brackets e.g. [22CSE803.5 - DATA MINING]
    s = re.sub(r"^[\[\(]+|[\]\)]+$", "", s).strip()
    # Strip trailing decorative underscores or dashes
    s = re.sub(r"[\s_]+$", "", s).strip()
    # Remove leading "Student List -" if present
    s = re.sub(r"^STUDENT\s+LIST\s*[-:–—−]?\s*", "", s, flags=re.IGNORECASE).strip()
    if s.lower().startswith("sub:"):
        s = s[4:].strip()

    # Pattern: course code followed by separator (-, :, en-dash, em-dash, minus) and subject name
    m = re.match(r"^([0-9]{2}[A-Za-z]{2,5}\s*\d+(?:\.\d+)?(?:[ _]?[A-Za-z0-9]{1,2})?|[A-Za-z]{2,5}\s*\d{3}[A-Za-z0-9\._]*)\s*[-:–—−]\s*(.+)$", s)
    if m:
        orig_code = m.group(1).strip()
        norm_code = normalize_subject_code(orig_code)
        name = m.group(2).strip()
        name = re.sub(r"^[\[\(]+|[\]\)]+$", "", name).strip()
        name = re.sub(r"[\s_]+$", "", name).strip()
        name = " ".join(name.split())
        return orig_code, norm_code, name

    # Pattern without separator e.g. "22ECE802.7 ENTREPRENEURSHIP"
    m2 = re.match(r"^([0-9]{2}[A-Za-z]{2,5}\s*\d+(?:\.\d+)?(?:[ _]?[A-Za-z0-9]{1,2})?|[A-Za-z]{2,5}\s*\d{3}[A-Za-z0-9\._]*)\s+([A-Za-z].+)$", s)
    if m2:
        orig_code = m2.group(1).strip()
        norm_code = normalize_subject_code(orig_code)
        name = m2.group(2).strip()
        name = re.sub(r"^[\[\(]+|[\]\)]+$", "", name).strip()
        name = re.sub(r"[\s_]+$", "", name).strip()
        name = " ".join(name.split())
        return orig_code, norm_code, name

    # Check known subject lookup
    norm_upper = s.upper().strip()
    if norm_upper in KNOWN_SUBJECT_MAP:
        code, name, _ = KNOWN_SUBJECT_MAP[norm_upper]
        return code, code, name

    # If starts with standard code alone
    m3 = re.match(r"^([0-9]{2}[A-Za-z]{2,5}\s*\d+(?:\.\d+)?(?:[ _]?[A-Za-z0-9]{1,2})?|[A-Za-z]{2,5}\s*\d{3}[A-Za-z0-9\._]*)$", s)
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


def normalize_elective_type(raw_num: str, norm_code: str = "", context: str = "") -> str:
    """
    Map raw elective number string (e.g. 'I', 'II', 'III', 'IV', 'PE-III', '3', 'Open Elective I')
    or context/norm_code to standardized elective group label (e.g. 'Programme Elective III').
    """
    if not raw_num:
        return derive_elective_type(norm_code, context)

    clean = re.sub(r"[\[\]]", "", str(raw_num)).strip()
    clean = re.sub(r"\be\.g\.?\b", "", clean, flags=re.IGNORECASE).strip()
    if not clean or clean.lower() in {"i, ii, iii, iv", "i, ii, iii", "i/ii/iii/iv", "i,ii,iii,iv"}:
        return derive_elective_type(norm_code, context)

    c_upper = clean.upper()
    ctx_upper = context.upper()
    sub_upper = norm_code.upper()

    is_arch = "ARE" in sub_upper or "ARCH" in ctx_upper or "ARCH" in c_upper
    is_open = "OPEN" in ctx_upper or "OPEN" in c_upper

    prefix = "Architecture Elective" if is_arch else ("Open Elective" if is_open else "Programme Elective")

    if re.search(r"\b(?:III|3)\b", c_upper) or "PE-III" in c_upper or "PE III" in c_upper or "PE_III" in c_upper:
        return f"{prefix} III"
    elif re.search(r"\b(?:IV|4)\b", c_upper) or "PE-IV" in c_upper or "PE IV" in c_upper or "PE_IV" in c_upper:
        return f"{prefix} IV"
    elif re.search(r"\b(?:V|5)\b", c_upper) or "PE-V" in c_upper or "PE V" in c_upper or "PE_V" in c_upper:
        return f"{prefix} V"
    elif re.search(r"\b(?:II|2)\b", c_upper) or "PE-II" in c_upper or "PE II" in c_upper or "PE_II" in c_upper:
        return f"{prefix} II"
    elif re.search(r"\b(?:I|1)\b", c_upper) or "PE-I" in c_upper or "PE I" in c_upper or "PE_I" in c_upper:
        return f"{prefix} I"
    elif any(k in c_upper for k in ("PROGRAMME ELECTIVE", "PROGRAM ELECTIVE", "ELECTIVE", "MINOR", "HONOURS")):
        return clean.title()

    return derive_elective_type(norm_code, context)


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
    """Normalize roll number: uppercase, remove internal spaces, dashes, dots, and punctuation."""
    if not val:
        return ""
    r = str(val).strip().upper()
    r = re.sub(r"[\s\-_.]+", "", r)
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
    if len(r) < 4 or len(r) > 16:
        return False
    # Avoid header keywords or numbers
    if r.isdigit() or r in {"ROLLNO", "SLNO", "NAME", "STUDENTNAME", "CLASSNAME", "DATE", "TIME"}:
        return False
    return bool(ROLL_REGEX.match(r))


def detect_subject_banner(val: str) -> tuple[str, str, str] | None:
    """
    Check if a string represents an elective subject banner.
    Returns (orig_code, norm_code, name) or None.
    """
    if not val:
        return None
    s = re.sub(r"[\r\n]+", " ", str(val)).strip()
    s = re.sub(r"[\s_]+$", "", s).strip()
    if len(s) < 3 or len(s) > 120:
        return None

    # Never treat a student roll number as a subject banner
    if is_valid_roll_number(s):
        return None

    # Skip table header lines, template titles, and college headers
    lower_s = s.lower()
    if lower_s in {"roll no", "name", "student name", "sl no", "sl.no.", "uni reg no", "sl. no."}:
        return None
    if any(k in lower_s for k in ("tkm college", "karicode", "report taken on", "elective student details", "students count")):
        return None

    # Check for course code: e.g. 22***80* or Sub:
    if re.search(r"(?:^|[\s\-_:])(?:22[A-Za-z]{2,4}\s*80[0-9](?:\.[0-9]+[A-Za-z0-9_]*)?)", s, re.IGNORECASE):
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

    # 0. Check if this sheet matches the official ELECTIVE STUDENT DETAILS template
    is_template_sheet = False
    for r in rows[:10]:
        r_str = " ".join(str(c).lower() for c in r if c is not None)
        if "elective student details" in r_str or ("elective course" in r_str and "department name" in r_str):
            is_template_sheet = True
            break

    if is_template_sheet:
        raw_elective_number = ""
        header_dept_name = ""
        header_batch = ""
        header_sem = ""
        raw_course = ""
        declared_count_str = ""

        header_row_idx = None
        r_idx = -1
        n_idx = -1

        for r_idx_scan, row in enumerate(rows):
            if not any(row):
                continue
            for c_i, cell in enumerate(row):
                if cell is not None:
                    clow = str(cell).strip().lower()
                    val = str(row[c_i + 1]).strip() if c_i + 1 < len(row) and row[c_i + 1] is not None else ""
                    if "elective number" in clow or "elective no" in clow:
                        raw_elective_number = val
                    elif "department" in clow:
                        header_dept_name = val
                    elif "class" in clow or "batch" in clow:
                        header_batch = val
                    elif "semester" in clow or "sem" in clow:
                        header_sem = val
                    elif "course" in clow or "subject" in clow:
                        raw_course = val
                    elif "count" in clow:
                        declared_count_str = val

            vals_low = [str(c).strip().lower() for c in row if c is not None]
            if any("roll" in h for h in vals_low):
                header_row_idx = r_idx_scan
                for c_i, c_val in enumerate(row):
                    if c_val is not None:
                        clow = str(c_val).strip().lower()
                        if "roll" in clow:
                            r_idx = c_i
                        elif "name" in clow:
                            n_idx = c_i
                break

        raw_course = re.split(r"Faculty\s*Advisor", raw_course, flags=re.IGNORECASE)[0].strip()
        raw_course = re.sub(r"[\s_]+$", "", raw_course).strip()
        orig_code, norm_code, subject_name = split_subject_header(raw_course)

        etype = normalize_elective_type(
            raw_elective_number,
            norm_code,
            f"{file_name} {sheet_title} {subject_name} {header_sem} {header_batch}",
        )

        clean_dept = re.sub(r"[\[\]]", "", header_dept_name).strip().upper()
        clean_batch = re.sub(r"[\[\]]|\be\.g\.?\b", "", header_batch, flags=re.IGNORECASE).strip()
        header_dept_code = COMMON_DEPT_MAP.get(clean_dept, "")
        if not header_dept_code:
            for k, v in COMMON_DEPT_MAP.items():
                if k in clean_dept:
                    header_dept_code = v
                    break
        if not header_dept_code:
            b_upper = clean_batch.upper()
            for k, v in [("CHE", "CHE"), ("ARCH", "B.ARCH"), ("CSE", "CSE"), ("ECE", "ECE"), ("EEE", "EEE"), ("ME", "ME"), ("CE", "CE")]:
                if k in b_upper:
                    header_dept_code = v
                    break

        if header_row_idx is not None and r_idx != -1:
            start_row = header_row_idx + 1
            if n_idx == -1 and r_idx + 1 < len(rows[header_row_idx]):
                n_idx = r_idx + 1

            for r_num, row in enumerate(rows[start_row:], start=start_row + 1):
                if not any(row):
                    continue
                val_roll = str(row[r_idx]).strip() if r_idx < len(row) and row[r_idx] else ""
                val_name = str(row[n_idx]).strip() if n_idx != -1 and n_idx < len(row) and row[n_idx] else ""

                clean_r = clean_roll_number(val_roll)
                if not is_valid_roll_number(clean_r):
                    continue

                clean_n = clean_student_name(val_name) or clean_r
                dept = derive_dept_from_roll(clean_r) or header_dept_code
                cname = derive_class_name(clean_r, sheet_title, clean_batch) or clean_batch

                _add_student_to_subject(
                    subject_map=subject_map,
                    report=report,
                    orig_code=orig_code,
                    norm_code=norm_code,
                    subject_name=subject_name,
                    elective_type=etype,
                    roll=clean_r,
                    name=clean_n,
                    dept=dept,
                    class_name=cname,
                    source_file=file_name,
                    sheet_or_page=sheet_title,
                    row_idx=r_num,
                )
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


COMMON_DEPT_MAP = {
    "ARCHITECTURE": "B.ARCH",
    "B.ARCH": "B.ARCH",
    "BARCH": "B.ARCH",
    "CHEMICAL ENGINEERING": "CHE",
    "CIVIL ENGINEERING": "CE",
    "COMPUTER SCIENCE AND ENGINEERING": "CSE",
    "COMPUTER SCIENCE & ENGINEERING": "CSE",
    "ELECTRICAL AND ELECTRONICS ENGINEERING": "EEE",
    "ELECTRICAL & ELECTRONICS ENGINEERING": "EEE",
    "ELECTRONICS AND COMMUNICATION ENGINEERING": "ECE",
    "ELECTRONICS & COMMUNICATION ENGINEERING": "ECE",
    "MECHANICAL ENGINEERING": "ME",
    "DEPARTMENT OF ARCHITECTURE": "B.ARCH",
    "DEPARTMENT OF CHEMICAL ENGINEERING": "CHE",
    "DEPARTMENT OF CIVIL ENGINEERING": "CE",
    "DEPARTMENT OF COMPUTER SCIENCE AND ENGINEERING": "CSE",
    "DEPARTMENT OF COMPUTER SCIENCE & ENGINEERING": "CSE",
    "DEPARTMENT OF ELECTRICAL AND ELECTRONICS ENGINEERING": "EEE",
    "DEPARTMENT OF ELECTRICAL & ELECTRONICS ENGINEERING": "EEE",
    "DEPARTMENT OF ELECTRONICS AND COMMUNICATION ENGINEERING": "ECE",
    "DEPARTMENT OF ELECTRONICS & COMMUNICATION ENGINEERING": "ECE",
    "DEPARTMENT OF MECHANICAL ENGINEERING": "ME",
    "DEPT OF ARCHITECTURE": "B.ARCH",
    "DEPT OF CHEMICAL ENGINEERING": "CHE",
    "DEPT OF CIVIL ENGINEERING": "CE",
    "DEPT OF COMPUTER SCIENCE AND ENGINEERING": "CSE",
    "DEPT OF ELECTRICAL AND ELECTRONICS ENGINEERING": "EEE",
    "DEPT OF ELECTRONICS AND COMMUNICATION ENGINEERING": "ECE",
    "DEPT OF MECHANICAL ENGINEERING": "ME",
}


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
        first_page_text = doc[0].get_text() if len(doc) > 0 else ""
        is_common_template = bool(
            re.search(r"ELECTIVE\s+STUDENT\s+DETAILS", first_page_text, re.IGNORECASE)
            or (
                re.search(r"Elective\s*Course", first_page_text, re.IGNORECASE)
                and re.search(r"Department\s*Name", first_page_text, re.IGNORECASE)
            )
        )

        if is_common_template:
            _parse_common_template_pdf(doc, path, subject_map, report, issues)
        else:
            _parse_generic_elective_pdf(doc, path, subject_map, report, issues)
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


def _parse_common_template_pdf(
    doc,
    path: Path,
    subject_map: dict[str, ElectiveSubjectRecord],
    report: ElectiveParseReport,
    issues: list[str],
) -> None:
    p1_text = doc[0].get_text() if len(doc) > 0 else ""

    # 1. Metadata Extraction from Structured Table & Fallback Text
    raw_elective_number = ""
    header_dept_name = ""
    header_batch = ""
    header_sem = ""
    raw_course = ""
    faculty_advisor = ""
    declared_count_str = ""

    # Strategy A: Table-based extraction on Page 1
    tabs_p1 = doc[0].find_tables()
    if tabs_p1.tables:
        for t in tabs_p1.tables:
            data = t.extract()
            for row in data:
                if row and len(row) >= 2 and row[0]:
                    k = str(row[0]).strip().lower()
                    v = str(row[1]).strip() if row[1] is not None else ""
                    v = re.sub(r"[\r\n]+", " ", v).strip()
                    if "elective number" in k or "elective no" in k:
                        raw_elective_number = v
                    elif "department" in k:
                        header_dept_name = v
                    elif "class" in k or "batch" in k:
                        header_batch = v
                    elif "semester" in k or "sem" in k:
                        header_sem = v
                    elif "course" in k or "subject" in k:
                        raw_course = v
                    elif "faculty" in k or "advisor" in k or "in-charge" in k:
                        faculty_advisor = v
                    elif "count" in k:
                        declared_count_str = v

    # Strategy B: Fallback Text Regex Extraction (when find_tables misses cells)
    if not raw_elective_number:
        m = re.search(r"Elective\s*(?:Number|No)\s*[\n:]*\s*([^\n]+)", p1_text, re.IGNORECASE)
        if m: raw_elective_number = m.group(1).strip()
    if not header_dept_name:
        m = re.search(r"Department\s*Name\s*[\n:]*\s*([^\n]+)", p1_text, re.IGNORECASE)
        if m: header_dept_name = m.group(1).strip()
    if not header_batch:
        m = re.search(r"Class\s*/\s*Batch\s*[\n:]*\s*([^\n]+)", p1_text, re.IGNORECASE)
        if m: header_batch = m.group(1).strip()
    if not header_sem:
        m = re.search(r"Current\s*Semester\s*[\n:]*\s*([^\n]+)", p1_text, re.IGNORECASE)
        if m: header_sem = m.group(1).strip()
    if not raw_course:
        m = re.search(r"Elective\s*Course\s*[\n:]*\s*([^\n]+(?:\n[^\n]+)?)", p1_text, re.IGNORECASE)
        if m: raw_course = m.group(1).strip()
    if not declared_count_str:
        m = re.search(r"Students\s*Count\s*[\n:]*\s*(\d+)", p1_text, re.IGNORECASE)
        if m: declared_count_str = m.group(1).strip()

    # Clean course line (strip trailing Faculty Advisor if captured together)
    raw_course = re.split(r"Faculty\s*Advisor", raw_course, flags=re.IGNORECASE)[0].strip()
    raw_course = re.sub(r"[\s_]+$", "", raw_course).strip()
    raw_course = " ".join(raw_course.split())

    orig_code, norm_code, subject_name = split_subject_header(raw_course)

    # Fallback to filename if course code is placeholder or empty
    if not norm_code or norm_code == subject_name or "[CODE" in norm_code:
        m_fn = re.match(r"^([0-9]{2}[A-Za-z]{2,5}[0-9\._A-Za-z]+(?:_[A-Za-z0-9]+)?)_(.+)\.pdf$", path.name, re.IGNORECASE)
        if m_fn:
            f_code = m_fn.group(1).replace("_", ".")
            f_name = m_fn.group(2).replace("_", " ")
            orig_code = f_code
            norm_code = normalize_subject_code(f_code)
            subject_name = f_name

    # Determine elective type
    etype = normalize_elective_type(raw_elective_number, norm_code, f"{path.name} {subject_name} {header_sem} {header_batch}")

    # Determine department code
    clean_dept = re.sub(r"[\[\]]", "", header_dept_name).strip().upper()
    clean_batch = re.sub(r"[\[\]]|\be\.g\.?\b", "", header_batch, flags=re.IGNORECASE).strip()
    header_dept_code = COMMON_DEPT_MAP.get(clean_dept, "")
    if not header_dept_code:
        for k, v in COMMON_DEPT_MAP.items():
            if k in clean_dept:
                header_dept_code = v
                break
    if not header_dept_code:
        b_upper = clean_batch.upper()
        for k, v in [("CHE", "CHE"), ("ARCH", "B.ARCH"), ("CSE", "CSE"), ("ECE", "ECE"), ("EEE", "EEE"), ("ME", "ME"), ("CE", "CE")]:
            if k in b_upper:
                header_dept_code = v
                break

    # Parse declared student count
    m_digits = re.search(r"\d+", declared_count_str)
    declared_count = int(m_digits.group(0)) if m_digits else None

    # 2. Extract Students across all pages
    total_parsed_for_subject = 0
    for page_idx, page in enumerate(doc, start=1):
        page_students_found = False
        tabs = page.find_tables()
        if tabs.tables:
            for t in tabs.tables:
                data = t.extract()
                if not data or len(data) < 1:
                    continue

                # Skip 2-column metadata table on page 1
                if len(data[0]) <= 2 and any("elective" in str(c).lower() or "department" in str(c).lower() for c in data[0] if c is not None):
                    continue

                # Detect header row
                header_row_idx = -1
                r_idx = -1
                n_idx = -1

                for row_i, row in enumerate(data[:3]):
                    row_strs = [str(c).strip().lower() for c in row if c is not None]
                    if any("roll" in h for h in row_strs):
                        header_row_idx = row_i
                        for c_i, c_val in enumerate(row):
                            if c_val is not None:
                                clow = str(c_val).strip().lower()
                                if "roll" in clow:
                                    r_idx = c_i
                                elif "name" in clow:
                                    n_idx = c_i
                        break

                # If no header row found (continuation page where students start immediately)
                start_row = 1
                if header_row_idx == -1:
                    for test_row in data[:5]:
                        if not test_row:
                            continue
                        for c_i, c_val in enumerate(test_row):
                            if c_val and is_valid_roll_number(str(c_val)):
                                r_idx = c_i
                                if r_idx + 1 < len(test_row):
                                    n_idx = r_idx + 1
                                elif r_idx - 1 >= 0 and not str(test_row[r_idx - 1]).strip().isdigit():
                                    n_idx = r_idx - 1
                                start_row = 0
                                break
                        if r_idx != -1:
                            break
                else:
                    start_row = header_row_idx + 1
                    if n_idx == -1 and r_idx != -1 and r_idx + 1 < len(data[0]):
                        n_idx = r_idx + 1

                if r_idx == -1:
                    continue

                for r_num, row in enumerate(data[start_row:], start=start_row + 1):
                    if not row or not any(row):
                        continue
                    val_roll = str(row[r_idx]).strip() if r_idx < len(row) and row[r_idx] else ""
                    val_name = str(row[n_idx]).strip() if n_idx != -1 and n_idx < len(row) and row[n_idx] else ""

                    clean_r = clean_roll_number(val_roll)
                    if not is_valid_roll_number(clean_r):
                        continue

                    clean_n = clean_student_name(val_name) or clean_r
                    dept = derive_dept_from_roll(clean_r) or header_dept_code
                    cname = derive_class_name(clean_r, "", clean_batch) or clean_batch

                    _add_student_to_subject(
                        subject_map=subject_map,
                        report=report,
                        orig_code=orig_code,
                        norm_code=norm_code,
                        subject_name=subject_name,
                        elective_type=etype,
                        roll=clean_r,
                        name=clean_n,
                        dept=dept,
                        class_name=cname,
                        source_file=path.name,
                        sheet_or_page=f"Page {page_idx}",
                        row_idx=r_num,
                    )
                    page_students_found = True
                    total_parsed_for_subject += 1

        if not page_students_found:
            # Fallback to text line extraction for this page
            page_text = page.get_text()
            lines = [l.strip() for l in page_text.splitlines() if l.strip()]
            for l_idx, line in enumerate(lines):
                line_lower = line.lower()
                if any(k in line_lower for k in ("tkm college", "karicode", "elective student details", "date:", "time:")):
                    continue

                tokens = line.split()
                roll_token_idx = -1
                for t_idx, tok in enumerate(tokens):
                    clean_tok = clean_roll_number(tok)
                    if is_valid_roll_number(clean_tok):
                        roll_token_idx = t_idx
                        clean_r = clean_tok
                        break

                if roll_token_idx != -1:
                    name_tokens = [t for t in tokens[roll_token_idx + 1:] if not t.isdigit() and len(t) > 1]
                    cand_name = " ".join(name_tokens).strip()

                    if not cand_name and l_idx + 1 < len(lines):
                        nxt = lines[l_idx + 1]
                        if not any(is_valid_roll_number(t) for t in nxt.split()) and not nxt.isdigit() and len(nxt) > 2:
                            cand_name = clean_student_name(nxt)

                    dept = derive_dept_from_roll(clean_r) or header_dept_code
                    cname = derive_class_name(clean_r, "", clean_batch) or clean_batch

                    _add_student_to_subject(
                        subject_map=subject_map,
                        report=report,
                        orig_code=orig_code,
                        norm_code=norm_code,
                        subject_name=subject_name,
                        elective_type=etype,
                        roll=clean_r,
                        name=cand_name or clean_r,
                        dept=dept,
                        class_name=cname,
                        source_file=path.name,
                        sheet_or_page=f"Page {page_idx}",
                        row_idx=l_idx + 1,
                    )
                    total_parsed_for_subject += 1

    # 3. Input Validation
    subj_rec = subject_map.get(norm_code)
    extracted_count = len(subj_rec.students) if subj_rec else 0

    if declared_count is not None and extracted_count != declared_count:
        warn = (
            f"Validation Warning in '{path.name}': Declared student count ({declared_count}) "
            f"does not match extracted count ({extracted_count})."
        )
        report.warnings.append(warn)
        issues.append(warn)


def _parse_generic_elective_pdf(
    doc,
    path: Path,
    subject_map: dict[str, ElectiveSubjectRecord],
    report: ElectiveParseReport,
    issues: list[str],
) -> None:
    current_orig_code = ""
    current_norm_code = ""
    current_sub_name = ""
    current_etype = derive_elective_type("", path.name)

    for page_idx, page in enumerate(doc, start=1):
        page_text = page.get_text()

        # Check if page has a subject banner
        m_page = re.search(
            r"(?:STUDENT LIST\s*[-]?\s*)?([0-9]{2}[A-Za-z]{2,5}\s*[0-9\._A-Za-z]+(?:[ _][A-Za-z0-9]+)?)\s*[-:]\s*([^\n\r]+)",
            page_text,
            re.IGNORECASE,
        )
        if m_page:
            banner_orig, banner_norm, banner_name = split_subject_header(m_page.group(0))
            if banner_norm:
                current_orig_code = banner_orig
                current_norm_code = banner_norm
                current_sub_name = banner_name
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
