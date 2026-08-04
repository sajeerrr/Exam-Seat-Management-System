# io_layer/input/timetable_parser.py
"""
Parses TKM College exam timetable PDFs into ExamSession objects.

Supports two PDF formats:

B.Tech format (two-column layout)
-----------------------------------
Lines look like:
  "Date : 12-03--2026 (Thursday) 1 Date : 13-03-2026 (Friday) 2"
  "Time: 10:00 - 12:00 Noon FN Time: 10:00 - 12:00 Noon FN"
  "Quantity Surveying (23CET601) CE Project Management (23HUP608) ME"

Each subject line ends each segment with (CODE) DEPT.

B.Arch format (slot-letter layout)
------------------------------------
Lines look like:
  "B Arch - S4 - 2nd Series Exam - March 2026 - TIME TABLE"
  "Date : 12-03--2026 (Thursday) 1 Date : 12-03--2026 (Thursday) 2"
  "Time: 10:00 AM to 12:00 Noon FN Time: 2:00 PM to 4:00 PM AN"
  "Slot, Subject & Code  Slot, Subject & Code"
  "A | History of Architecture and Culture - III"
  "(23ARS402)"                        ← code on next line
  "B | Landscape Design (23ARS403)"   ← code on same line

Department is always "AR" for B.Arch timetables.
Semester is extracted from the header line (S4, S8, …).
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)

# ── Shared regexes ────────────────────────────────────────────────────────────
_DATE_RE    = re.compile(r"(\d{2}-\d{2}-{1,2}\d{4})")
_SESSION_RE = re.compile(r"\b(FN|AN)\b")

# B.Tech: each segment ends with (CODE) DEPT
_BTECH_PAIR_RE = re.compile(r"\((\w+)\s*\)\s+([A-Z]{2,5})\b")

# B.Arch: slot letter followed by pipe/space, then name, ending with (CODE)
# Handles "A | Name (CODE)" and "A| Name(CODE)" and bare "(CODE)" on its own line
_BARCH_SLOT_RE  = re.compile(r"^([A-Z])\s*\|\s*(.+?)(?:\((\w+)\s*\))?\s*$")
_BARCH_CODE_RE  = re.compile(r"^\((\w+)\s*\)\s*$")

# Semester from B.Arch header line e.g. "B Arch - S4 - …"
_SEMESTER_RE    = re.compile(r"\bS(\d)\b")


@dataclass
class ExamSession:
    """One subject sitting for one department."""
    exam_date:    str
    session:      str       # FN / AN
    department:   str
    subject_code: str
    subject_name: str
    semester:     int = 0   # 0 if unknown


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

        # Detect B.Arch by looking for the header phrase
        is_barch = bool(re.search(r"B\s*Arch", full_text, re.IGNORECASE))

        if is_barch:
            sessions = self._parse_barch(full_text)
        else:
            sessions = self._parse_btech(full_text)

        logger.info("Parsed %d exam sessions from %s", len(sessions), filepath.name)
        return sessions

    # ══════════════════════════════════════════════════════════════════════════
    # B.Tech parser (two-column layout)
    # ══════════════════════════════════════════════════════════════════════════

    def _parse_btech(self, text: str) -> list[ExamSession]:
        """
        Two-slot state machine.
        slots[col] = (date, session)  — col 0 = left, col 1 = right.
        """
        sessions: list[ExamSession] = []
        slots: dict[int, tuple[str, str]] = {}

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            # ── Date line ─────────────────────────────────────────────────
            if "date" in line.lower() and _DATE_RE.search(line):
                all_dates = _DATE_RE.findall(line)
                all_dates = [re.sub(r"-{2,}", "-", d) for d in all_dates]
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
            segments = self._split_btech_line(line)
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
    def _split_btech_line(line: str) -> list[tuple[str, str, str]]:
        """
        Split a subject line into (name, code, dept) tuples.

        E.g.:
          "Qty Surveying (23CET601) CE Project Mgmt (23HUP608) ME"
        →  [("Qty Surveying", "23CET601", "CE"),
            ("Project Mgmt",  "23HUP608", "ME")]
        """
        results = []
        matches = list(_BTECH_PAIR_RE.finditer(line))
        prev_end = 0
        for m in matches:
            name_part    = line[prev_end: m.start()].strip()
            subject_code = m.group(1).strip()
            department   = m.group(2).strip()
            prev_end = m.end()
            results.append((name_part, subject_code, department))
        return results

    # ══════════════════════════════════════════════════════════════════════════
    # B.Arch parser (slot-letter layout)
    # ══════════════════════════════════════════════════════════════════════════

    def _parse_barch(self, text: str) -> list[ExamSession]:
        """
        Parse a B.Arch timetable.

        The layout uses one or two columns per date block. Slot letters (A-T)
        identify subjects. The subject name or code can span multiple lines.
        Department is always "AR".

        State:
          slots[col] = (date, session)
          pending[col] = (slot_letter, partial_name) — accumulates multi-line subject
        """
        sessions: list[ExamSession] = []

        # Extract semester from first header line mentioning S4/S8/…
        semester = 0
        m_sem = _SEMESTER_RE.search(text)
        if m_sem:
            semester = int(m_sem.group(1))

        slots: dict[int, tuple[str, str]] = {}
        pending: dict[int, list] = {}   # col → [slot_letter, name_parts, code_or_None]

        def flush_pending():
            """Emit a session from pending slots and clear them."""
            for col, parts in list(pending.items()):
                slot_letter, name_parts, code = parts
                if col not in slots:
                    continue
                date, session = slots[col]
                if not date or not session or not code:
                    continue
                sessions.append(ExamSession(
                    exam_date    = date,
                    session      = session,
                    department   = "AR",
                    subject_code = code,
                    subject_name = " ".join(name_parts).strip(),
                    semester     = semester,
                ))
            pending.clear()

        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            i += 1

            if not line:
                continue

            # ── Date line ─────────────────────────────────────────────────
            if "date" in line.lower() and _DATE_RE.search(line):
                flush_pending()
                all_dates = _DATE_RE.findall(line)
                all_dates = [re.sub(r"-{2,}", "-", d) for d in all_dates]
                new_slots: dict[int, tuple[str, str]] = {}
                for col, date in enumerate(all_dates):
                    old_sess = slots.get(col, ("", ""))[1]
                    new_slots[col] = (date, old_sess)
                slots = new_slots
                continue

            # ── Time / session line ───────────────────────────────────────
            if "time" in line.lower() or "noon" in line.lower() or " pm" in line.lower():
                all_sesses = _SESSION_RE.findall(line)
                for col, sess in enumerate(all_sesses):
                    if col in slots:
                        date, _ = slots[col]
                        slots[col] = (date, sess)
                    else:
                        slots[col] = ("", sess)
                continue

            # ── Skip header lines ─────────────────────────────────────────
            if (line.startswith("TKM") or "college" in line.lower()
                    or "slot, subject" in line.lower()
                    or "copy to" in line.lower()
                    or line.startswith("Dean")
                    or line.startswith("Dy.")
                    or line.startswith("*")):
                continue

            # ── Bare code line: (23ARS402) ────────────────────────────────
            m_code = _BARCH_CODE_RE.match(line)
            if m_code:
                code = m_code.group(1).strip()
                # Assign to the most recent pending slot (col 0 priority, then 1)
                assigned = False
                for col in sorted(pending.keys()):
                    if pending[col][2] is None:
                        pending[col][2] = code
                        assigned = True
                        break
                if not assigned and pending:
                    # append to first pending as continuation name
                    col = sorted(pending.keys())[0]
                    pending[col][1].append(f"({code})")
                continue

            # ── Slot lines: "A | Name (CODE)" or "A| Name(CODE)" ─────────
            # A single line can have two slots side by side, like:
            #   "A| Human Settlement Planning(22ARS801) D| Research Methodology(22ARP801)"
            # or split over multiple lines.
            # Strategy: scan for all slot-letter occurrences on this line.

            slot_matches = list(re.finditer(
                r"(?:^|(?<=\s))([A-Z])\s*\|[ \t]*(.+?)(?=\s+[A-Z]\s*\||$)",
                line
            ))

            if not slot_matches:
                # Might be a continuation of a pending subject name
                # Check if any pending entries lack a code
                for col in sorted(pending.keys()):
                    if pending[col][2] is None:
                        # See if the line contains a code
                        m_inline = re.search(r"\((\w+)\s*\)\s*(\*?)\s*$", line)
                        if m_inline:
                            # Code is at the end
                            code = m_inline.group(1)
                            name_chunk = line[:m_inline.start()].strip()
                            if name_chunk:
                                pending[col][1].append(name_chunk)
                            pending[col][2] = code
                        else:
                            # No code yet — accumulate as name continuation
                            pending[col][1].append(line)
                        break
                continue

            # Flush any pending from previous slots before processing new ones
            flush_pending()

            col_offset = 0
            for sm in slot_matches:
                slot_letter = sm.group(1)
                content     = sm.group(2).strip()
                col = col_offset
                col_offset += 1

                # Check if the content ends with (CODE)
                m_inline = re.search(r"\((\w+)\s*\)\s*(\*?)\s*$", content)
                if m_inline:
                    code = m_inline.group(1)
                    name = content[:m_inline.start()].strip()
                    if col not in slots:
                        continue
                    date, session = slots[col]
                    if date and session:
                        sessions.append(ExamSession(
                            exam_date    = date,
                            session      = session,
                            department   = "AR",
                            subject_code = code,
                            subject_name = name,
                            semester     = semester,
                        ))
                else:
                    # Code not yet found — start pending accumulation
                    pending[col] = [slot_letter, [content], None]

        flush_pending()
        return sessions
