# io_layer/input/timetable_parser.py
"""
Parses TKM College exam timetable PDFs into ExamSession objects.

The PDF has a two-column layout — two exam slots side by side.
Each subject row may contain entries for both columns on the same text line.

Example:
  Line 3: "Date : 12-03--2026 (Thursday) 1 Date : 13-03-2026 (Friday) 2"
  Line 4: "Time: 10:00 - 12:00 Noon FN Time: 10:00 - 12:00 Noon FN"
  Line 6: "Quantity Surveying and Valuation (23CET601 ) CE Project Management (23HUP608) ME"

The parser extracts one ExamSession per (date, session, dept, subject_code) tuple.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)

_DATE_RE    = re.compile(r"(\d{2}-\d{2}-{1,2}\d{4})")   # handles 12-03-2026 and 12-03--2026

_SESSION_RE = re.compile(r"\b(FN|AN)\b")

# Splits a subject line into its individual (name, code, dept) segments.
# A segment always ends with (CODE) DEPT.
# We tokenise by finding every (CODE) DEPT occurrence and working backwards.
_PAIR_RE = re.compile(r"(.*?)\((\w+)\s*\)\s*([A-Z]{2,5})\b", re.DOTALL)


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

    # ── Internal ──────────────────────────────────────────────────────────

    def _parse_text(self, text: str) -> list[ExamSession]:
        """
        Two-slot state machine.
        slots[col] = (date, session)  — col 0 = left, col 1 = right.
        """
        sessions: list[ExamSession] = []

        # col → (date, session)
        slots: dict[int, tuple[str, str]] = {}

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            # ── Date line ─────────────────────────────────────────────────
            if "date" in line.lower() and _DATE_RE.search(line):
                all_dates = _DATE_RE.findall(line)
                all_dates = [re.sub(r"-{2,}", "-", d) for d in all_dates]
                # Preserve existing sessions if date line has no session info
                new_slots: dict[int, tuple[str, str]] = {}
                for col, date in enumerate(all_dates):
                    old_sess = slots.get(col, ("", ""))[1]
                    new_slots[col] = (date, old_sess)
                slots = new_slots
                continue

            # ── Time / session line ───────────────────────────────────────
            if "time" in line.lower() or "noon" in line.lower() or " pm" in line.lower():
                all_sessions = _SESSION_RE.findall(line)
                for col, sess in enumerate(all_sessions):
                    if col in slots:
                        date, _ = slots[col]
                        slots[col] = (date, sess)
                    else:
                        slots[col] = ("", sess)
                continue

            # ── Skip header and empty-slot lines ─────────────────────────
            if not slots or "subject" in line.lower():
                continue

            # ── Subject rows ──────────────────────────────────────────────
            # Split line into segments: each ends with (CODE) DEPT
            # "Name A (CODE1) DEPT1 Name B (CODE2) DEPT2"
            segments = self._split_subject_line(line)
            if not segments:
                continue

            for col, (subject_name, subject_code, department) in enumerate(segments):
                if col not in slots:
                    continue
                date, session = slots[col]
                if not date or not session:
                    continue

                sessions.append(ExamSession(
                    exam_date    = date,
                    session      = session,
                    department   = department,
                    subject_code = subject_code,
                    subject_name = subject_name.strip(),
                ))

        return sessions

    @staticmethod
    def _split_subject_line(line: str) -> list[tuple[str, str, str]]:
        """
        Split a subject line into (name, code, dept) tuples.

        E.g.:
          "Qty Surveying (23CET601) CE Project Mgmt (23HUP608) ME"
        →  [("Qty Surveying", "23CET601", "CE"),
            ("Project Mgmt",  "23HUP608", "ME")]

        Strategy: find each (CODE) DEPT position; the name is the text
        between the end of the previous match and the start of this (CODE).
        """
        results = []
        # Find positions of every (CODE) DEPT occurrence
        pair_pattern = re.compile(r"\((\w+)\s*\)\s+([A-Z]{2,5})\b")
        matches = list(pair_pattern.finditer(line))

        prev_end = 0
        for i, m in enumerate(matches):
            name_part = line[prev_end : m.start()].strip()
            subject_code = m.group(1).strip()
            department   = m.group(2).strip()
            prev_end = m.end()
            results.append((name_part, subject_code, department))

        return results
