# io_layer/input/session_filter.py
"""
Filters students by exam date + session and injects timetable data.

The PDFParser produces Students with empty subject_code/subject_name/exam_date/session.
The TimetableParser produces ExamSessions with dept/subject/date/session.

SessionFilter.filter() cross-references both:
  - For each student whose department matches an ExamSession on the chosen date+session,
    it stamps the student's subject_code, subject_name, exam_date, and session.
  - Returns only the stamped students (those sitting that session).
"""

import logging
from copy import copy

from engine.models.student import Student
from io_layer.input.timetable_parser import ExamSession

logger = logging.getLogger(__name__)


class SessionFilter:
    """
    Filters and annotates students for a specific exam slot.

    Usage
    -----
    filter = SessionFilter()
    sitting = filter.filter(
        students  = all_students,
        sessions  = all_sessions,
        exam_date = "12-03-2026",
        session   = "FN",
    )
    """

    def filter(
        self,
        students: list[Student],
        sessions: list[ExamSession],
        exam_date: str,
        session: str,
    ) -> list[Student]:

        slot_map: dict[str, ExamSession] = {
            s.department: s
            for s in sessions
            if s.exam_date == exam_date and s.session == session
        }

        if not slot_map:
            logger.warning(
                "No exam sessions found for date=%s session=%s",
                exam_date, session,
            )
            return []

        logger.info(
            "Session filter: date=%s  session=%s  departments_sitting=%s",
            exam_date, session, sorted(slot_map.keys()),
        )

        filtered: list[Student] = []

        for student in students:
            exam_session = slot_map.get(student.department)
            if exam_session is None:
                continue

            stamped = copy(student)
            stamped.subject_code = exam_session.subject_code
            stamped.subject_name = exam_session.subject_name
            stamped.exam_date    = exam_session.exam_date
            stamped.session      = exam_session.session
            filtered.append(stamped)

        logger.info(
            "SessionFilter: %d / %d students sitting on %s %s",
            len(filtered), len(students), exam_date, session,
        )
        return filtered
