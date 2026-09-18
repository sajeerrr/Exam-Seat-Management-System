from dataclasses import dataclass, field
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

    students: list[Student] = field(default_factory=list)

    allocated_count: int = 0

    @property
    def strength(self):
        return len(self.students)

    @property
    def remaining_count(self):
        return self.strength - self.allocated_count

    @property
    def next_start_index(self):
        return self.allocated_count

    def allocate_students(self, count: int):

        start = self.next_start_index
        end = start + count

        allocated = self.students[start:end]

        self.allocated_count += len(allocated)

        return allocated

    @property
    def priority(self):
        return self.remaining_count