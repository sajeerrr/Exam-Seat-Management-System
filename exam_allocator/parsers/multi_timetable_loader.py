"""
Multi-file timetable ingestion, parsing, normalization, validation, and merging.
Supports discovering and parsing multiple Excel (.xlsx/.xlsm/.xls) and PDF (.pdf) timetable files.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import re

from openpyxl import load_workbook
import fitz  # PyMuPDF

from exam_allocator.parsers.timetable_parser import (
    _parse_date,
    _parse_session,
    _parse_branches,
    _calculate_duration_minutes,
    _clean_text,
    _is_empty_row,
    _normalize_header,
    HEADER_NAMES,
)

logger = logging.getLogger(__name__)


@dataclass
class ExamRecord:
    programme: str
    semester: int | str
    exam_date: date
    session: str  # "FN" or "AN"
    time: str
    branch: str
    branches: list[str]
    subject_name: str
    subject_code: str
    duration_minutes: int
    source_file: str

    def duplicate_key(self):
        return (
            str(self.programme).strip().lower(),
            str(self.semester),
            str(self.branch).strip().upper(),
            self.exam_date,
            str(self.session).strip().upper(),
            str(self.subject_code).strip().upper(),
        )


@dataclass
class FileExtractionResult:
    source_file: str
    success: bool
    parser_stage: str
    exams: list[ExamRecord] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    error_reason: str = ""


@dataclass
class TimetableMergeResult:
    files_discovered: int = 0
    files_parsed: int = 0
    files_failed: int = 0
    total_records: int = 0
    file_results: list[FileExtractionResult] = field(default_factory=list)
    merged_exams: list[ExamRecord] = field(default_factory=list)
    summary_by_programme_semester: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def discover_timetable_files(timetable_dir: str | Path | None = None) -> list[Path]:
    """
    Discover all supported timetable files (.xlsx, .xlsm, .xls, .pdf)
    from the given directory or default locations.
    """
    candidates = []
    if timetable_dir:
        d = Path(timetable_dir)
        if d.is_file():
            candidates = [d]
        elif d.is_dir():
            for ext in ("*.xlsx", "*.xlsm", "*.xls", "*.pdf"):
                candidates.extend(d.glob(ext))
                candidates.extend(d.glob(f"**/{ext}"))
    else:
        # Check standard default paths
        default_dirs = [
            Path("resources/Timetable"),
            Path("resources"),
            Path("media/uploads"),
        ]
        for d in default_dirs:
            if d.exists() and d.is_dir():
                for ext in ("*.xlsx", "*.xlsm", "*.xls", "*.pdf"):
                    candidates.extend(d.glob(ext))
                    candidates.extend(d.glob(f"**/{ext}"))

        root_t = Path("resources/Timetable.xlsx")
        if root_t.exists() and root_t not in candidates:
            candidates.append(root_t)

    valid_candidates = []
    for f in candidates:
        name_lower = f.name.lower()
        if "student" in name_lower or name_lower == "class.xlsx":
            continue
        # Also include seating plans or test files if specifically passed, but default discover ignores them unless needed
        if "seating_plan" in name_lower:
            continue
        valid_candidates.append(f)

    unique_files = sorted(list(set(valid_candidates)))
    return [f for f in unique_files if f.is_file()]


def parse_all_timetables(timetable_dir: str | Path | None = None) -> TimetableMergeResult:
    """
    Discover and parse all timetable files, validate, detect duplicates, and merge.
    """
    files = discover_timetable_files(timetable_dir)
    result = TimetableMergeResult(files_discovered=len(files))

    file_results: list[FileExtractionResult] = []
    all_exams: list[ExamRecord] = []

    for file_path in files:
        ext = file_path.suffix.lower()
        res = None
        if ext in {".xlsx", ".xlsm", ".xls"}:
            res = _parse_excel_file(file_path)
        elif ext == ".pdf":
            res = _parse_pdf_file(file_path)
        else:
            res = FileExtractionResult(
                source_file=file_path.name,
                success=False,
                parser_stage="Format Detection",
                error_reason=f"Unsupported file extension: {ext}",
            )

        file_results.append(res)
        if res.success:
            result.files_parsed += 1
            all_exams.extend(res.exams)
            result.warnings.extend([f"{file_path.name}: {issue}" for issue in res.issues])
        else:
            result.files_failed += 1
            result.errors.append(f"FAILED: {file_path.name} | Stage: {res.parser_stage} | Reason: {res.error_reason}")

    result.file_results = file_results

    seen = {}
    deduplicated_exams = []
    for exam in all_exams:
        key = exam.duplicate_key()
        if key in seen:
            existing = seen[key]
            if existing.source_file == exam.source_file:
                continue
            else:
                result.warnings.append(
                    f"Duplicate / conflicting exam record detected between '{existing.source_file}' and '{exam.source_file}' for "
                    f"Prog: {exam.programme}, Sem: {exam.semester}, Branch: {exam.branch}, Date: {exam.exam_date}, Session: {exam.session}, Subject: {exam.subject_code}"
                )
                deduplicated_exams.append(exam)
        else:
            seen[key] = exam
            deduplicated_exams.append(exam)

    result.merged_exams = deduplicated_exams
    result.total_records = len(deduplicated_exams)

    summary = {}
    for exam in deduplicated_exams:
        label = f"{exam.programme} S{exam.semester}"
        summary[label] = summary.get(label, 0) + 1
    result.summary_by_programme_semester = summary

    return result


def _detect_programme_semester(text: str, filename: str) -> tuple[str, str | int]:
    combined = f"{filename} {text}"

    prog = "Unknown"
    if re.search(r"\bB\.?\s*Tech\b", combined, re.IGNORECASE):
        prog = "B.Tech"
    elif re.search(r"\bB\.?\s*Arch\b", combined, re.IGNORECASE):
        prog = "B.Arch"
    elif re.search(r"\bM\.?\s*Tech\b", combined, re.IGNORECASE):
        prog = "M.Tech"
    elif re.search(r"\bMBA\b", combined, re.IGNORECASE):
        prog = "MBA"
    elif re.search(r"\bMCA\b", combined, re.IGNORECASE):
        prog = "MCA"
    elif filename.startswith("CE_"):
        prog = "B.Tech"
    elif filename.startswith("ME_"):
        prog = "B.Tech"
    elif filename.startswith("EEE_"):
        prog = "B.Tech"
    elif filename.startswith("CHE_"):
        prog = "B.Tech"
    elif filename.startswith("EL_"):
        prog = "B.Tech"
    elif filename.startswith("B.Arch_"):
        prog = "B.Arch"

    sem = ""
    sem_match = re.search(r"\bS\s*(\d+)\b", combined, re.IGNORECASE)
    if sem_match:
        sem = int(sem_match.group(1))
    else:
        num_match = re.search(r"Sem(?:ester)?\s*(\d+)", combined, re.IGNORECASE)
        if num_match:
            sem = int(num_match.group(1))
        elif "2K23" in combined:
            sem = 6  # e.g. 6th semester for 2K23 batch in March 2026
        elif "2K21" in combined:
            sem = 10
        elif "2K22" in combined:
            sem = 8
        else:
            sem = "Unknown"

    return prog, sem


def _parse_excel_file(path: Path) -> FileExtractionResult:
    try:
        workbook = load_workbook(filename=path, read_only=True, data_only=True)
    except Exception as exc:
        return FileExtractionResult(
            source_file=path.name,
            success=False,
            parser_stage="Excel Opening",
            error_reason=str(exc),
        )

    exams: list[ExamRecord] = []
    issues: list[str] = []

    try:
        for worksheet in workbook.worksheets:
            sheet_title = str(worksheet.title).strip()
            rows = list(worksheet.iter_rows(values_only=True))
            if not rows:
                continue

            sheet_text = " ".join([str(c) for row in rows[:5] for c in row if c is not None])
            prog, sem = _detect_programme_semester(f"{sheet_title} {sheet_text}", path.name)

            header_index = _find_header_row_flexible(rows)
            if header_index is None:
                if any("admission no" in str(c).lower() or "roll no" in str(c).lower() for row in rows[:10] for c in row if c):
                    workbook.close()
                    return FileExtractionResult(
                        source_file=path.name,
                        success=False,
                        parser_stage="Format Detection",
                        error_reason="File appears to be a student list / roster rather than an exam timetable.",
                    )
                issues.append(f"Sheet '{sheet_title}': Header row not found. Attempting fallback parse.")
                # Fallback parse for unstructured sheets
                for row_number, row in enumerate(rows, start=1):
                    exam = _parse_unstructured_row(row, prog, sem, path.name)
                    if exam:
                        exams.append(exam)
                continue

            headers = [_normalize_header(c) for c in rows[header_index]]

            for row_number, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
                if _is_empty_row(row):
                    continue
                try:
                    exam = _parse_exam_row_flexible(row, headers, prog, sem, path.name)
                    if exam:
                        exams.append(exam)
                except Exception as exc:
                    issues.append(f"Sheet '{sheet_title}', row {row_number}: {exc}")

    except Exception as exc:
        return FileExtractionResult(
            source_file=path.name,
            success=False,
            parser_stage="Excel Iteration",
            error_reason=str(exc),
        )
    finally:
        workbook.close()

    if not exams:
        return FileExtractionResult(
            source_file=path.name,
            success=False,
            parser_stage="Excel Validation",
            error_reason="No valid exam entries extracted from Excel.",
            issues=issues,
        )

    return FileExtractionResult(
        source_file=path.name,
        success=True,
        parser_stage="Complete",
        exams=exams,
        issues=issues,
    )


def _find_header_row_flexible(rows) -> int | None:
    for idx, row in enumerate(rows):
        norm = {_normalize_header(c) for c in row if c is not None}
        matches = len(norm.intersection(HEADER_NAMES))
        if matches >= 2 or any("subject" in n or "code" in n or "date" in n for n in norm):
            return idx
    return None


def _parse_exam_row_flexible(row, headers, default_prog, default_sem, source_file) -> ExamRecord | None:
    values = {}
    for idx, h in enumerate(headers):
        if not h:
            continue
        values[h] = row[idx] if idx < len(row) else None

    date_val = None
    for k, v in values.items():
        if "date" in k:
            date_val = _parse_date(v)
            if date_val:
                break
    if not date_val:
        for cell in row:
            dt = _parse_date(cell)
            if dt:
                date_val = dt
                break

    session_val = "FN"
    time_val = ""
    for k, v in values.items():
        if "session" in k or "time" in k:
            txt = str(v or "")
            if "AN" in txt.upper():
                session_val = "AN"
            time_str = re.sub(r"(?i)\b(FN|AN)\b", "", txt).strip()
            if time_str:
                time_val = time_str

    if not time_val:
        for cell in row:
            txt = str(cell or "")
            if ":" in txt:
                if "AN" in txt.upper():
                    session_val = "AN"
                time_val = txt
                break

    branch_val = "ALL"
    for k, v in values.items():
        if "branch" in k or "slot" in k:
            if v:
                branch_val = str(v).strip()
                break

    subj_name = ""
    subj_code = ""
    for k, v in values.items():
        if "subject name" in k or ("subject" in k and "code" not in k):
            if v:
                subj_name = str(v).strip()
        if "course code" in k or "subject code" in k:
            if v:
                subj_code = str(v).strip()

    if not subj_name and not subj_code:
        for cell in row:
            txt = str(cell or "").strip()
            if not txt:
                continue
            match = re.search(r"\(([^)]+)\)", txt)
            if match:
                subj_code = match.group(1).strip()
                subj_name = txt[:match.start()].strip()
                break

    if not subj_code and subj_name:
        match = re.search(r"\(([^)]+)\)", subj_name)
        if match:
            subj_code = match.group(1).strip()
            subj_name = subj_name[:match.start()].strip()

    if not subj_code:
        subj_code = subj_name

    if not date_val or not subj_code:
        return None

    duration = _calculate_duration_minutes(time_val)

    # Handle branch extraction if branch name is encoded in filename or row
    branch_candidates = [branch_val]
    if branch_val == "ALL" or not branch_val:
        if source_file.startswith("CE_"):
            branch_candidates = ["CE"]
        elif source_file.startswith("ME_"):
            branch_candidates = ["ME"]
        elif source_file.startswith("EEE_"):
            branch_candidates = ["EEE"]
        elif source_file.startswith("CHE_"):
            branch_candidates = ["CHE"]
        elif source_file.startswith("EL_"):
            branch_candidates = ["EL"]
        elif source_file.startswith("B.Arch_"):
            branch_candidates = ["B.Arch"]

    return ExamRecord(
        programme=default_prog,
        semester=default_sem,
        exam_date=date_val,
        session=session_val,
        time=time_val,
        branch=", ".join(branch_candidates),
        branches=_parse_branches(", ".join(branch_candidates)),
        subject_name=subj_name or subj_code,
        subject_code=subj_code,
        duration_minutes=duration,
        source_file=source_file,
    )


def _parse_unstructured_row(row, default_prog, default_sem, source_file) -> ExamRecord | None:
    date_val = None
    time_val = ""
    session_val = "FN"
    subj_name = ""
    subj_code = ""

    for cell in row:
        if cell is None:
            continue
        txt = str(cell).strip()
        if not date_val:
            dt = _parse_date(txt)
            if dt:
                date_val = dt
                continue
        if ":" in txt and not time_val:
            time_val = txt
            if "AN" in txt.upper():
                session_val = "AN"
            continue
        if "(" in txt and ")" in txt and not subj_code:
            match = re.search(r"\(([^)]+)\)", txt)
            if match:
                subj_code = match.group(1).strip()
                subj_name = txt[:match.start()].strip()

    if not date_val or not subj_code:
        return None

    branch = "ALL"
    if source_file.startswith("CE_"):
        branch = "CE"
    elif source_file.startswith("ME_"):
        branch = "ME"
    elif source_file.startswith("EEE_"):
        branch = "EEE"
    elif source_file.startswith("CHE_"):
        branch = "CHE"
    elif source_file.startswith("EL_"):
        branch = "EL"
    elif source_file.startswith("B.Arch_"):
        branch = "B.Arch"

    return ExamRecord(
        programme=default_prog,
        semester=default_sem,
        exam_date=date_val,
        session=session_val,
        time=time_val,
        branch=branch,
        branches=_parse_branches(branch),
        subject_name=subj_name or subj_code,
        subject_code=subj_code,
        duration_minutes=_calculate_duration_minutes(time_val),
        source_file=source_file,
    )


def _parse_pdf_file(path: Path) -> FileExtractionResult:
    try:
        doc = fitz.open(path)
    except Exception as exc:
        return FileExtractionResult(
            source_file=path.name,
            success=False,
            parser_stage="PDF Opening",
            error_reason=str(exc),
        )

    first_page_text = doc[0].get_text() if len(doc) > 0 else ""
    if "Students Count" in first_page_text or "Admission No" in first_page_text or "Roll No" in first_page_text:
        doc.close()
        return FileExtractionResult(
            source_file=path.name,
            success=False,
            parser_stage="Format Detection",
            error_reason="File is a student list / class roster PDF rather than an exam timetable.",
        )

    issues: list[str] = []
    exams: list[ExamRecord] = []
    program, semester = _detect_programme_semester(first_page_text, path.name)

    try:
        for page_num, page in enumerate(doc):
            text = page.get_text()
            if program == "Unknown" or semester == "Unknown":
                p, s = _detect_programme_semester(text, path.name)
                if p != "Unknown":
                    program = p
                if s != "Unknown":
                    semester = s

            tabs = page.find_tables()
            if not tabs:
                # Fallback: parse text lines for exam-like patterns
                for line in text.splitlines():
                    dt = _parse_date(line)
                    if dt:
                        # Extract course code/name if present
                        match = re.search(r"\(([^)]+)\)", line)
                        if match:
                            scode = match.group(1).strip()
                            sname = line[:match.start()].strip()
                            branch = "ALL"
                            if path.name.startswith("CE_"):
                                branch = "CE"
                            elif path.name.startswith("ME_"):
                                branch = "ME"
                            elif path.name.startswith("EEE_"):
                                branch = "EEE"
                            elif path.name.startswith("CHE_"):
                                branch = "CHE"
                            elif path.name.startswith("EL_"):
                                branch = "EL"
                            elif path.name.startswith("B.Arch_"):
                                branch = "B.Arch"

                            exams.append(ExamRecord(
                                programme=program if program != "Unknown" else "B.Tech",
                                semester=semester if semester != "Unknown" else 6,
                                exam_date=dt,
                                session="AN" if "AN" in line.upper() else "FN",
                                time="",
                                branch=branch,
                                branches=_parse_branches(branch),
                                subject_name=sname or scode,
                                subject_code=scode,
                                duration_minutes=180,
                                source_file=path.name,
                            ))
                continue

            for tab in tabs:
                grid = tab.extract()
                if not grid:
                    continue

                col_contexts = {}
                last_exam_by_col = {}

                for row in grid:
                    row = [c.replace('\n', ' ') if c else '' for c in row]
                    for c, cell in enumerate(row):
                        cell_clean = cell.strip()
                        if not cell_clean:
                            continue
                        if "Date" in cell_clean and re.search(r"\d", cell_clean):
                            dt = _parse_date(cell_clean)
                            if dt:
                                if c not in col_contexts:
                                    col_contexts[c] = {}
                                col_contexts[c]["date"] = dt
                                last_exam_by_col.pop(c, None)
                        if "Time" in cell_clean and ":" in cell_clean:
                            sess = "FN"
                            if "AN" in cell_clean.upper():
                                sess = "AN"
                            elif c + 1 < len(row) and row[c + 1] and "AN" in row[c + 1].upper():
                                sess = "AN"
                            time_str = re.sub(r"(?i)time\s*:", "", cell_clean)
                            time_str = re.sub(r"(?i)\b(FN|AN)\b", "", time_str)
                            time_str = re.sub(r"^[^\d]*", "", time_str).strip()
                            if c not in col_contexts:
                                col_contexts[c] = {}
                            col_contexts[c]["time"] = time_str
                            col_contexts[c]["session"] = sess
                        if "Subject" in cell_clean and "Code" in cell_clean:
                            if c not in col_contexts:
                                col_contexts[c] = {}
                            col_contexts[c]["type"] = "SUBJECT"
                            last_exam_by_col.pop(c, None)
                        if cell_clean.upper() == "BRANCH":
                            if c not in col_contexts:
                                col_contexts[c] = {}
                            col_contexts[c]["type"] = "BRANCH"

                    for c in range(len(row)):
                        if c in col_contexts and col_contexts[c].get("type") == "BRANCH":
                            if c - 1 in col_contexts and "date" in col_contexts[c - 1]:
                                col_contexts[c]["date"] = col_contexts[c - 1].get("date")
                                col_contexts[c]["time"] = col_contexts[c - 1].get("time")
                                col_contexts[c]["session"] = col_contexts[c - 1].get("session")

                    for c in range(len(row)):
                        if c in col_contexts and col_contexts[c].get("type") == "SUBJECT":
                            if "date" not in col_contexts[c] and c - 1 in col_contexts and "date" in col_contexts[c - 1]:
                                col_contexts[c]["date"] = col_contexts[c - 1].get("date")
                                col_contexts[c]["time"] = col_contexts[c - 1].get("time")
                                col_contexts[c]["session"] = col_contexts[c - 1].get("session")

                    is_data_row = False
                    for c, cell in enumerate(row):
                        if c in col_contexts and col_contexts[c].get("type") == "SUBJECT":
                            cell_clean = cell.strip()
                            if cell_clean and not any(kw in cell_clean for kw in ["Date", "Time", "Subject", "Branch"]):
                                is_data_row = True
                                break
                            elif not cell_clean and c in last_exam_by_col:
                                b_cell = row[c + 1].strip() if c + 1 < len(row) and c + 1 in col_contexts and col_contexts[c + 1].get("type") == "BRANCH" else ""
                                if b_cell and not any(kw in b_cell for kw in ["Date", "Time", "Subject", "Branch"]):
                                    is_data_row = True
                                    break

                    if is_data_row:
                        for c, cell in enumerate(row):
                            if c in col_contexts and col_contexts[c].get("type") == "SUBJECT":
                                cell_clean = cell.strip()
                                b_cell = row[c + 1].strip() if c + 1 < len(row) and c + 1 in col_contexts and col_contexts[c + 1].get("type") == "BRANCH" else ""

                                if cell_clean and not any(kw in cell_clean for kw in ["Date", "Time", "Subject", "Branch"]):
                                    branch = "ALL BRANCHES"
                                    if b_cell:
                                        branch = b_cell
                                    elif "Arch" in str(program):
                                        branch = "B.ARCH"

                                    date_val = col_contexts[c].get("date")
                                    time_val = col_contexts[c].get("time", "")
                                    sess_val = col_contexts[c].get("session", "FN")

                                    if not date_val:
                                        continue

                                    slot = ""
                                    subj_name = cell_clean
                                    subj_code = ""

                                    if "|" in subj_name:
                                        parts = subj_name.split("|", 1)
                                        slot = parts[0].strip()
                                        subj_name = parts[1].strip()
                                        if "Arch" in str(program) and slot:
                                            branch = f"SLOT {slot}"

                                    match = re.search(r"\(([^)]+)\)$", subj_name)
                                    if match:
                                        subj_code = match.group(1).strip()
                                        subj_name = subj_name[:match.start()].strip()

                                    if not subj_code:
                                        subj_code = subj_name

                                    if path.name.startswith("CE_"):
                                        branch = "CE"
                                    elif path.name.startswith("ME_"):
                                        branch = "ME"
                                    elif path.name.startswith("EEE_"):
                                        branch = "EEE"
                                    elif path.name.startswith("CHE_"):
                                        branch = "CHE"
                                    elif path.name.startswith("EL_"):
                                        branch = "EL"
                                    elif path.name.startswith("B.Arch_"):
                                        branch = "B.Arch"

                                    new_exam = ExamRecord(
                                        programme=program if program != "Unknown" else "B.Tech",
                                        semester=semester if semester != "Unknown" else 6,
                                        exam_date=date_val,
                                        session=sess_val,
                                        time=time_val,
                                        branch=branch,
                                        branches=_parse_branches(branch),
                                        subject_name=subj_name,
                                        subject_code=subj_code,
                                        duration_minutes=_calculate_duration_minutes(time_val),
                                        source_file=path.name,
                                    )
                                    exams.append(new_exam)
                                    last_exam_by_col[c] = new_exam

                                elif not cell_clean and b_cell and c in last_exam_by_col:
                                    if not any(kw in b_cell for kw in ["Date", "Time", "Subject", "Branch"]):
                                        parsed_b = _parse_branches(b_cell)
                                        target_exam = last_exam_by_col[c]
                                        for pb in parsed_b:
                                            if pb not in target_exam.branches:
                                                target_exam.branches.append(pb)
                                        target_exam.branch = ", ".join(target_exam.branches)
    except Exception as exc:
        return FileExtractionResult(
            source_file=path.name,
            success=False,
            parser_stage="PDF Table Extraction",
            error_reason=str(exc),
        )
    finally:
        doc.close()

    if not exams:
        return FileExtractionResult(
            source_file=path.name,
            success=False,
            parser_stage="PDF Validation",
            error_reason="No valid exam entries extracted from PDF.",
            issues=issues,
        )

    return FileExtractionResult(
        source_file=path.name,
        success=True,
        parser_stage="Complete",
        exams=exams,
        issues=issues,
    )
