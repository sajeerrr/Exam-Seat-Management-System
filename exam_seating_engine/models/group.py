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
    def strength(self): #find the strength
        return len(self.students)

    @property
    def remaining_count(self):#find remaining count
        return self.strength - self.allocated_count

    def allocate(self, count: int):#allocate count
        self.allocated_count += count

    @property
    def next_start_index(self): #for get range like 0 to 15 and 16 to 30 like
        return self.allocated_count