"""
Elective list parser module.

Supports parsing elective student lists in Excel (.xlsx, .xlsm, .xls) and PDF formats.
Extracts departments, elective groups, subjects, and student enrollments.
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
    elective_label: str  # e.g., "Programme Elective III", "Elective (802)"
    subjects: list[ElectiveSubjectRecord] = field(default_factory=list)


@dataclass
class ElectiveExtractionResult:
    source_file: str
    groups: list[ElectiveGroupRecord]
    issues: list[str] = field(default_factory=list)


def split_subject_header(s: str) -> tuple[str, str]:
    """
    Split subject string into (subject_code, subject_name).
    E.g. '22ECE 803.2  REAL TIME OPERATING SYSTEMS' -> ('22ECE803.2', 'REAL TIME OPERATING SYSTEMS')
    """
    s = s.strip()
    if s.lower().startswith("sub:"):
        s = s[4:].strip()

    # Pattern: course code followed by separator and subject name
    m = re.match(r"^([0-9]{2}[A-Z]{2,5}\s*[0-9\._A-Z]+)\s*[-:]?\s*(.+)$", s)
    if m:
        code = m.group(1).replace(" ", "").strip()
        name = m.group(2).strip()
        return code, name

    # If no standard prefix code found, use first few tokens as code
    clean_s = s.strip()
    if len(clean_s) > 30:
        return clean_s[:25].strip(), clean_s
    return clean_s, clean_s


def derive_dept_code(sub_code: str, file_name: str, sheet_name: str = "") -> str:
    """
    Derive department code from subject code, filename, or sheet name.
    """
    # Try course code prefix: e.g. 22MEE802 -> ME, 22ECE803 -> EC, 22CSE802 -> CSE
    m = re.match(r"^[0-9]{2}([A-Z]{2,4})[0-9]", sub_code.replace(" ", ""))
    if m:
        c = m.group(1).upper()
        mapping = {
            "MEE": "ME",
            "ECE": "EC",
            "CSE": "CSE",
            "EEE": "EEE",
            "CEE": "CE",
            "CHE": "CHE",
            "ARE": "B.ARCH",
        }
        if c in mapping:
            return mapping[c]
        return c

    # Try from filename
    fn = file_name.upper()
    for d in ["B.ARCH", "BARCH", "CHE", "CSE", "ECE", "EEE", "ME", "CE", "EC", "EL"]:
        if fn.startswith(d + "_") or fn.startswith(d + ".") or f"_{d}_" in fn or fn.startswith(d):
            return "B.ARCH" if "ARCH" in d else d

    # Try from sheet name
    sn = sheet_name.upper()
    for d in ["B.ARCH", "BARCH", "CHE", "CSE", "ECE", "EEE", "ME", "CE", "EC", "EL"]:
        if d in sn:
            return "B.ARCH" if "ARCH" in d else d

    return "GEN"


def derive_dept_name(code: str) -> str:
    dept_map = {
        "CE": "Civil Engineering",
        "ME": "Mechanical Engineering",
        "EEE": "Electrical & Electronics Engineering",
        "EC": "Electronics & Communication Engineering",
        "ECE": "Electronics & Communication Engineering",
        "CSE": "Computer Science & Engineering",
        "CHE": "Chemical Engineering",
        "B.ARCH": "Architecture",
        "EL": "Electrical & Computer Engineering",
    }
    return dept_map.get(code.upper(), f"{code} Department")


def derive_group_label(sub_code: str, sheet_name: str = "", file_name: str = "") -> str:
    """
    Derive elective group label e.g. 'Programme Elective III', 'Programme Elective IV'.
    """
    m = re.search(r"([0-9]{2}[A-Z]{2,5})\s*([0-9]{3})", sub_code)
    if m:
        num = m.group(2)
        if num == "801":
            return "Programme Elective I (801)"
        if num == "802":
            return "Programme Elective II / III (802)"
        if num == "803":
            return "Programme Elective IV (803)"
        if num == "804":
            return "Programme Elective V (804)"
        return f"Elective ({num})"

    for text in [sheet_name, file_name]:
        m_pe = re.search(r"(PE[-_\s]*[IV0-9]+)", text, re.IGNORECASE)
        if m_pe:
            return m_pe.group(1).upper().replace("_", "-")
        m_prog = re.search(r"Programme[-_\s]*Electives?[-_\s]*([IV0-9]+)", text, re.IGNORECASE)
        if m_prog:
            return f"PE-{m_prog.group(1).upper()}"

    return "Electives"


def detect_subject_banner(vals: list) -> str | None:
    """
    Detect whether a row in Excel is a subject title banner.
    """
    if 1 <= len(vals) <= 3:
        for v in vals:
            vs = str(v).strip()
            # Ignore headers/metadata
            if any(k in vs.upper() for k in [
                "TKM COLLEGE", "REPORT TAKEN", "KARICODE", "SL NO", "ROLL NO",
                "STUDENT LIST - CHE", "TOTAL COUNT", "FACULTY ADVISOR", "DURATION"
            ]):
                continue
            if re.match(r"^(?:22[A-Z0-9\.\-_]+|Sub:)", vs):
                return vs
            if any(k in vs.upper() for k in [
                "ENTREPRENEURSHIP", "BIOMEDICAL ENGINEERING", "DEEP LEARNING",
                "REAL TIME OPERATING SYSTEMS", "MODERN COMMUNICATION SYSTEMS",
                "QUALITY MANAGEMENT", "AIR QUALITY MANAGEMENT", "ENERGY MANAGEMENT",
                "SMART GRID", "COMPOSITE MATERIALS", "TECHNOLOGY MANAGEMENT",
                "POWER PLANT ENGINEERING", "EMBEDDED SYSTEMS", "NETWORK SECURITY",
                "ARCHITECTURAL CONSERVATION", "CONTEMPORARY ARCHITECTURE", "GREEN BUILDINGS",
                "DISASTER MITIGATION"
            ]):
                return vs
    return None


def extract_student_from_vals(vals: list) -> tuple[str | None, str | None]:
    """
    Extract (roll_number, student_name) from Excel row values.
    """
    roll = None
    for c in vals:
        cs = str(c).strip()
        # Roll numbers at TKM typically start with B22, TKM22, L22, etc. and are 7-12 chars
        if re.match(r"^[A-Z0-9]{7,12}$", cs) and any(cs.startswith(p) for p in ["B2", "TKM", "L2", "B21", "B20"]):
            roll = cs
            break

    if not roll:
        return None, None

    name = None
    for c in vals:
        if isinstance(c, str):
            cs = c.strip()
            if cs != roll and len(cs) >= 3 and not cs.isdigit():
                low = cs.lower()
                if not any(low.startswith(p) for p in ["sl no", "roll no", "uni reg", "sub:", "deep learning", "smart grid"]):
                    if not re.match(r"^[A-Z0-9]{7,12}$", cs):
                        name = cs
                        break

    return roll, name or roll


def parse_elective_file(file_path: str) -> ElectiveExtractionResult:
    """
    Parse an elective file (Excel or PDF) and return normalized extraction results.
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
        workbook = load_workbook(filename=path, read_only=True, data_only=True)
    except Exception as exc:
        raise ElectiveExcelParseError(f"Could not open Excel workbook: {exc}") from exc

    # groups_dict: (dept_code, elective_label) -> dict of subject_code -> ElectiveSubjectRecord
    groups_dict: dict[tuple[str, str], dict[str, ElectiveSubjectRecord]] = {}
    issues: list[str] = []

    try:
        for worksheet in workbook.worksheets:
            sname = worksheet.title.strip()
            if sname.lower() in {"master overview", "overview", "summary"}:
                continue

            current_sub: str | None = None

            for row in worksheet.iter_rows(values_only=True):
                vals = [c for c in row if c is not None and str(c).strip()]
                if not vals:
                    continue

                sb = detect_subject_banner(vals)
                if sb:
                    current_sub = sb
                    continue

                roll, name = extract_student_from_vals(vals)
                if roll:
                    assigned_sub = current_sub
                    # Check if 4th column has explicit subject name (e.g. EL.xlsx)
                    if len(vals) >= 4 and any(k in str(vals[3]).upper() for k in ["DEEP LEARNING", "SMART GRID"]):
                        assigned_sub = str(vals[3]).strip()

                    if not assigned_sub:
                        assigned_sub = "GENERAL-ELECTIVE"

                    code, sname_clean = split_subject_header(assigned_sub)
                    dept = derive_dept_code(code, path.name, sname)
                    grp_lbl = derive_group_label(code, sname, path.name)

                    key = (dept, grp_lbl)
                    if key not in groups_dict:
                        groups_dict[key] = {}

                    if code not in groups_dict[key]:
                        groups_dict[key][code] = ElectiveSubjectRecord(
                            subject_code=code,
                            subject_name=sname_clean,
                            students=[],
                        )

                    # Deduplicate students in the same subject
                    if not any(s.roll_number == roll for s in groups_dict[key][code].students):
                        groups_dict[key][code].students.append(
                            ElectiveStudentRecord(roll_number=roll, student_name=name)
                        )
    finally:
        workbook.close()

    if not groups_dict:
        raise ElectiveExcelParseError("No valid elective student records found in Excel workbook.")

    group_records = []
    for (dept, grp_lbl), subjects in groups_dict.items():
        group_records.append(ElectiveGroupRecord(
            department_code=dept,
            department_name=derive_dept_name(dept),
            elective_label=grp_lbl,
            subjects=list(subjects.values()),
        ))

    return ElectiveExtractionResult(
        source_file=path.name,
        groups=group_records,
        issues=issues,
    )


def _parse_elective_pdf(path: Path) -> ElectiveExtractionResult:
    if fitz is None:
        raise ElectiveExcelParseError("PyMuPDF (fitz) is required to parse PDF elective files.")

    try:
        doc = fitz.open(str(path))
    except Exception as exc:
        raise ElectiveExcelParseError(f"Could not open PDF file: {exc}") from exc

    groups_dict: dict[tuple[str, str], dict[str, ElectiveSubjectRecord]] = {}
    issues: list[str] = []

    try:
        current_sub_code = "GENERAL-ELECTIVE"
        current_sub_name = "General Elective"

        for page in doc:
            page_text = page.get_text()

            # Check page-level subject banner
            m_page = re.search(
                r"(?:STUDENT LIST\s*[-]?\s*)?([0-9]{2}[A-Z]{2,5}[0-9\._A-Z]+)\s*[-:]\s*([A-Z\s&_]+)",
                page_text,
                re.IGNORECASE,
            )
            if m_page:
                current_sub_code = m_page.group(1).strip()
                current_sub_name = m_page.group(2).strip()

            tabs = page.find_tables()
            if tabs.tables:
                for t in tabs.tables:
                    data = t.extract()
                    for row in data:
                        vals = [c for c in row if c is not None and str(c).strip()]
                        if not vals:
                            continue

                        # Check if row is subject banner
                        for v in vals:
                            vs = str(v).strip()
                            m_sub = re.search(
                                r"(?:STUDENT LIST\s*[-]?\s*)?([0-9]{2}[A-Z]{2,5}[0-9\._A-Z]+)\s*[-:]\s*([A-Z\s&_]+)",
                                vs,
                                re.IGNORECASE,
                            )
                            if m_sub:
                                current_sub_code = m_sub.group(1).strip()
                                current_sub_name = m_sub.group(2).strip()
                                break

                        roll, name = extract_student_from_vals(vals)
                        if roll:
                            dept = derive_dept_code(current_sub_code, path.name)
                            grp_lbl = derive_group_label(current_sub_code, "", path.name)
                            key = (dept, grp_lbl)
                            if key not in groups_dict:
                                groups_dict[key] = {}
                            if current_sub_code not in groups_dict[key]:
                                groups_dict[key][current_sub_code] = ElectiveSubjectRecord(
                                    subject_code=current_sub_code,
                                    subject_name=current_sub_name,
                                    students=[],
                                )
                            if not any(s.roll_number == roll for s in groups_dict[key][current_sub_code].students):
                                groups_dict[key][current_sub_code].students.append(
                                    ElectiveStudentRecord(roll_number=roll, student_name=name)
                                )
            else:
                # Text-line based fallback
                lines = [l.strip() for l in page_text.splitlines() if l.strip()]
                for i, line in enumerate(lines):
                    m_sub = re.search(
                        r"(?:STUDENT LIST\s*[-]?\s*)?([0-9]{2}[A-Z]{2,5}[0-9\._A-Z]+)\s*[-:]\s*([A-Z\s&_]+)",
                        line,
                        re.IGNORECASE,
                    )
                    if m_sub:
                        current_sub_code = m_sub.group(1).strip()
                        current_sub_name = m_sub.group(2).strip()
                        continue

                    if re.match(r"^[A-Z0-9]{7,12}$", line) and any(line.startswith(p) for p in ["B2", "TKM", "L2"]):
                        roll = line
                        name = ""
                        for j in range(i + 1, min(i + 5, len(lines))):
                            cand = lines[j]
                            if not cand.isdigit() and len(cand) > 1 and not re.match(r"^[A-Z0-9]{7,12}$", cand) and not cand.startswith("TKM22"):
                                name = cand
                                break
                        dept = derive_dept_code(current_sub_code, path.name)
                        grp_lbl = derive_group_label(current_sub_code, "", path.name)
                        key = (dept, grp_lbl)
                        if key not in groups_dict:
                            groups_dict[key] = {}
                        if current_sub_code not in groups_dict[key]:
                            groups_dict[key][current_sub_code] = ElectiveSubjectRecord(
                                subject_code=current_sub_code,
                                subject_name=current_sub_name,
                                students=[],
                            )
                        if not any(s.roll_number == roll for s in groups_dict[key][current_sub_code].students):
                            groups_dict[key][current_sub_code].students.append(
                                ElectiveStudentRecord(roll_number=roll, student_name=name or roll)
                            )
    finally:
        doc.close()

    if not groups_dict:
        raise ElectiveExcelParseError("No valid elective student records found in PDF file.")

    group_records = []
    for (dept, grp_lbl), subjects in groups_dict.items():
        group_records.append(ElectiveGroupRecord(
            department_code=dept,
            department_name=derive_dept_name(dept),
            elective_label=grp_lbl,
            subjects=list(subjects.values()),
        ))

    return ElectiveExtractionResult(
        source_file=path.name,
        groups=group_records,
        issues=issues,
    )
