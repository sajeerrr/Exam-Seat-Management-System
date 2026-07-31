from dataclasses import dataclass
from .group import Group
from .student import Student


@dataclass
class Allocation:

    group: Group
    students: list[Student]
    stream: str

    @property
    def allocated_count(self):
        return len(self.students)