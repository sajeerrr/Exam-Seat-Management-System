from dataclasses import dataclass, field
from .student import Student, normalize_subject_category


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
    subject_category: str = field(default="NORMAL")

    def __post_init__(self):
        self.subject_category = normalize_subject_category(self.subject_category)

    @property
    def is_special_subject(self) -> bool:
        """Returns True if this group represents an Elective, Minor, or Honours subject."""
        return self.subject_category in {"ELECTIVE", "MINOR", "HONOURS"}

    @property
    def normalized_subject_code(self) -> str:
        """Normalized subject code for exact group/conflict matching."""
        return str(self.subject_code).strip().upper() if self.subject_code else ""

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

    def snapshot(self) -> int:
        return self.allocated_count

    def restore(self, allocated_count: int):
        self.allocated_count = allocated_count

    def deallocate(self, count: int):
        start_index = self.allocated_count - count
        if start_index < 0:
            start_index = 0

        self.students = self.students[:start_index]
        self.allocated_count = start_index
