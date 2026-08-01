# io_layer/repositories/student_repository.py
"""
In-memory student repository.

Provides filtered views of the student list without mutating the source data.
"""

import logging
from engine.models.student import Student

logger = logging.getLogger(__name__)


class StudentRepository:
    """
    Stores all students and provides query methods.

    Usage
    -----
    repo = StudentRepository()
    repo.load(students)
    ce_students = repo.get_by_department("CE")
    """

    def __init__(self):
        self._students: list[Student] = []

    def load(self, students: list[Student]) -> None:
        self._students = list(students)
        logger.info("StudentRepository loaded %d students", len(self._students))

    def get_all(self) -> list[Student]:
        return list(self._students)

    def get_by_department(self, department: str) -> list[Student]:
        return [s for s in self._students if s.department == department]

    def get_by_semester(self, semester: int) -> list[Student]:
        return [s for s in self._students if s.semester == semester]

    def get_by_session(self, exam_date: str, session: str) -> list[Student]:
        return [
            s for s in self._students
            if s.exam_date == exam_date and s.session == session
        ]

    def get_by_department_and_session(
        self, department: str, exam_date: str, session: str
    ) -> list[Student]:
        return [
            s for s in self._students
            if s.department == department
            and s.exam_date == exam_date
            and s.session == session
        ]

    def departments(self) -> list[str]:
        return sorted(set(s.department for s in self._students))

    def count(self) -> int:
        return len(self._students)

    def __len__(self) -> int:
        return self.count()
