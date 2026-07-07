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
    students: List[Student] = field(default_factory=list)

    @property
    def strength(self):
        return len(self.students) #used to get strength of students