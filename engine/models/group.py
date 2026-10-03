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

    def snapshot(self) -> int:
        """Return current allocated_count for later restore."""
        return self.allocated_count

    def restore(self, allocated_count: int):
        """Restore allocated_count to a previous snapshot value."""
        self.allocated_count = allocated_count

    def deallocate(self, count: int):
        """Reverse allocation of `count` students (for LNS destroy).

        This method both reduces the allocated_count and removes the students
        from the group's students list to prevent duplicate allocations.
        """
        # Remove students from the end of the list to maintain consistency
        start_index = self.allocated_count - count
        if start_index < 0:
            start_index = 0

        # Remove the last 'count' students (since we allocated from the beginning)
        self.students = self.students[:start_index]
        self.allocated_count = start_index