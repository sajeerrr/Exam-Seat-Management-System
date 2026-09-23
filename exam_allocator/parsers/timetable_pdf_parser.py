"""
PDF timetable parser.

Reads timetable PDFs and converts each entry into a normalized Python object.
Uses PyMuPDF's table extraction feature.
"""

from __future__ import annotations

import re
from pathlib import Path

import fitz  # PyMuPDF

from .timetable_parser import (
    ExamRecord,
    TimetableExtractionResult,
    _calculate_duration_minutes,
    _parse_branches,
    _parse_date,
)


class TimetablePDFParseError(Exception):
    """Raised when the timetable PDF cannot be parsed."""


def parse_timetable_pdf(pdf_path: str) -> TimetableExtractionResult:
    path = Path(pdf_path)

    if not path.exists():
        raise TimetablePDFParseError(f"File not found: {pdf_path}")

    if path.suffix.lower() != ".pdf":
        raise TimetablePDFParseError(f"Unsupported file type: {path.suffix}")

    try:
        doc = fitz.open(path)
    except Exception as exc:
        raise TimetablePDFParseError(f"Could not open PDF: {exc}") from exc

    issues: list[str] = []
    exams: list[ExamRecord] = []

    program = ""
    semester = 0

    try:
        for page_num, page in enumerate(doc):
            # Extract program and semester from raw text
            text = page.get_text()
            
            if not program:
                # Look for "B Tech - S6" or "B Arch - S4"
                prog_match = re.search(r"(B\s*(?:Tech|Arch))\s*-\s*S\s*(\d+)", text, re.IGNORECASE)
                if prog_match:
                    program = prog_match.group(1).replace(" ", "") # "BTech" or "BArch"
                    if "Arch" in program:
                        program = "B.Arch"
                    else:
                        program = "B.Tech"
                    semester = int(prog_match.group(2))

            # Extract tables
            tabs = page.find_tables()
            if not tabs:
                issues.append(f"Page {page_num + 1}: No tables found.")
                continue

            for tab in tabs:
                grid = tab.extract()
                if not grid:
                    continue

                col_contexts = {}  # c -> {"date": date, "time": str, "session": str, "type": "SUBJECT" or "BRANCH"}

                for row in grid:
                    # Clean up row cells
                    row = [c.replace('\n', ' ') if c else '' for c in row]

                    # 1. Look for Date / Time headers
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

                        if "Time" in cell_clean and ":" in cell_clean:
                            sess = "FN"
                            if "AN" in cell_clean.upper():
                                sess = "AN"
                                
                            time_str = re.sub(r"(?i)time\s*:", "", cell_clean)
                            time_str = re.sub(r"(?i)\b(FN|AN)\b", "", time_str)
                            
                            # strip leading/trailing non-time characters (like serial numbers)
                            time_str = re.sub(r"^[^\d]*", "", time_str).strip()
                            
                            if c not in col_contexts:
                                col_contexts[c] = {}
                            col_contexts[c]["time"] = time_str
                            col_contexts[c]["session"] = sess

                        if "Subject" in cell_clean and "Code" in cell_clean:
                            if c not in col_contexts:
                                col_contexts[c] = {}
                            col_contexts[c]["type"] = "SUBJECT"

                        if cell_clean.upper() == "BRANCH":
                            if c not in col_contexts:
                                col_contexts[c] = {}
                            col_contexts[c]["type"] = "BRANCH"

                    # 2. Propagate contexts to neighboring BRANCH columns
                    for c in range(len(row)):
                        if c in col_contexts and col_contexts[c].get("type") == "BRANCH":
                            if c - 1 in col_contexts and "date" in col_contexts[c - 1]:
                                col_contexts[c]["date"] = col_contexts[c - 1].get("date")
                                col_contexts[c]["time"] = col_contexts[c - 1].get("time")
                                col_contexts[c]["session"] = col_contexts[c - 1].get("session")
                                
                    # Same for SUBJECT columns if the Date header was spanning 2 columns but put in c-1
                    for c in range(len(row)):
                        if c in col_contexts and col_contexts[c].get("type") == "SUBJECT":
                            if "date" not in col_contexts[c] and c - 1 in col_contexts and "date" in col_contexts[c - 1]:
                                col_contexts[c]["date"] = col_contexts[c - 1].get("date")
                                col_contexts[c]["time"] = col_contexts[c - 1].get("time")
                                col_contexts[c]["session"] = col_contexts[c - 1].get("session")

                    # 3. Check if this is a data row
                    is_data_row = False
                    for c, cell in enumerate(row):
                        if c in col_contexts and col_contexts[c].get("type") == "SUBJECT":
                            cell_clean = cell.strip()
                            if cell_clean and not any(kw in cell_clean for kw in ["Date", "Time", "Subject", "Branch"]):
                                is_data_row = True
                                break

                    if is_data_row:
                        for c, cell in enumerate(row):
                            if c in col_contexts and col_contexts[c].get("type") == "SUBJECT":
                                cell_clean = cell.strip()
                                if not cell_clean:
                                    continue
                                if any(kw in cell_clean for kw in ["Date", "Time", "Subject", "Branch"]):
                                    continue

                                branch = "ALL BRANCHES"
                                if c + 1 < len(row) and c + 1 in col_contexts and col_contexts[c + 1].get("type") == "BRANCH":
                                    branch_cell = row[c + 1]
                                    if branch_cell:
                                        branch = branch_cell.strip()
                                elif "Arch" in program:
                                    branch = "B.ARCH"

                                date_val = col_contexts[c].get("date")
                                time_val = col_contexts[c].get("time", "")
                                sess_val = col_contexts[c].get("session", "")

                                if not date_val:
                                    # Try to inherit from previous row if something is weird, but skip if no date
                                    continue
                                    
                                slot = ""
                                subj_name = cell_clean
                                subj_code = ""

                                if "|" in subj_name:
                                    parts = subj_name.split("|", 1)
                                    slot = parts[0].strip()
                                    subj_name = parts[1].strip()
                                    if "Arch" in program and slot:
                                        branch = f"SLOT {slot}"

                                match = re.search(r"\(([^)]+)\)$", subj_name)
                                if match:
                                    subj_code = match.group(1).strip()
                                    subj_name = subj_name[:match.start()].strip()

                                if not subj_code:
                                    subj_code = subj_name

                                exams.append(ExamRecord(
                                    program=program or "UNKNOWN",
                                    semester=semester or 0,
                                    exam_date=date_val,
                                    session=sess_val,
                                    time=time_val,
                                    branch=branch,
                                    branches=_parse_branches(branch),
                                    subject_name=subj_name,
                                    subject_code=subj_code,
                                    duration_minutes=_calculate_duration_minutes(time_val)
                                ))
    finally:
        doc.close()

    if not exams:
        raise TimetablePDFParseError("No timetable entries were found in the PDF.")

    return TimetableExtractionResult(
        source_file=path.name,
        exams=exams,
        issues=issues,
    )
