# io_layer/input/timetable_parser.py
"""
Parses TKM College exam timetable PDFs into ExamSession objects.

Expected format (one block per exam slot):
    Date : 12-03-2026 (Thursday)        ← date line
    Time: 10:00 - 12:00 Noon FN         ← session line (FN / AN)
    Subject & Code       Branch
    Quantity Surveying.. (23CET601)  CE
    Computer Aided..     (23MEP602)  ME
    ...

The parser produces one ExamSession per (date, session, department, subject_code) tuple.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)

_DATE_RE    = re.compile(r"(\d{2}-\d{2}-\d{4})")
_SESSION_RE = re.compile(r"\b(FN|AN)\b")
_SUBJECT_RE = re.compile(r"^(.+?)\s*\((\w+)\)\s+([A-Z]+)\s*$")


@dataclass
class ExamSession:
    """One subject sitting for one department."""
    exam_date:    str
    session:      str   # FN / AN
    department:   str
    subject_code: str
    subject_name: str


class TimetableParser:
    """
    Parses a timetable PDF and returns a flat list of ExamSession objects.

    Usage
    -----
    sessions = TimetableParser().parse("resources/2 S6 B Tech ... .pdf")
    """

    def parse(self, filepath: str | Path) -> list[ExamSession]:
        filepath = Path(filepath)
        logger.info("Parsing timetable PDF: %s", filepath.name)

        with pdfplumber.open(filepath) as pdf:
            full_text = "\n".join(
                page.extract_text() or "" for page in pdf.pages
            )

        sessions = self._parse_text(full_text)
        logger.info("Parsed %d exam sessions from timetable", len(sessions))
        return sessions

    def _parse_text(self, text: str) -> list[ExamSession]:
        sessions: list[ExamSession] = []
        current_date    = ""
        current_session = ""

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            date_match = _DATE_RE.search(line)
            if date_match and ("date" in line.lower() or re.search(r"\d{2}-\d{2}-\d{4}", line)):
                raw_date = date_match.group(1)
                raw_date = re.sub(r"-{2,}", "-", raw_date)
                current_date = raw_date

            sess_match = _SESSION_RE.search(line)
            if sess_match and ("time" in line.lower() or "noon" in line.lower() or "pm" in line.lower()):
                current_session = sess_match.group(1)

            if not current_date or not current_session:
                continue

            subj_match = _SUBJECT_RE.match(line)
            if subj_match:
                sessions.append(ExamSession(
                    exam_date    = current_date,
                    session      = current_session,
                    department   = subj_match.group(3).strip(),
                    subject_code = subj_match.group(2).strip(),
                    subject_name = subj_match.group(1).strip(),
                ))

        return sessions
