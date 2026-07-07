from dataclasses import dataclass, field
from typing import List
from .student import Student

@dataclass
class Group:
    group_id: str
    department: str
    semester: int
    section: str
    subject_code: str
    subject_name: str
    exam_date: str
    session: str
    students: List[Student] = field(default_factory=list)
    allocated_count: int = 0

    @property
    def strength(self): #find the strength
        return len(self.students)

    @property
    def remaining_count(self):
        return self.strength - self.allocated_count

    def allocate(self, count: int):
        self.allocated_count += count