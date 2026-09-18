# engine/models/room_allocation.py

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from engine.config import AllocationLimits


@dataclass
class StreamSlot:
    stream_name: str
    capacity: int = 15
    students: List[Any] = field(default_factory=list)

    @property
    def remaining_capacity(self) -> int:
        return self.capacity - len(self.students)

    @property
    def is_empty(self) -> bool:
        return len(self.students) == 0

    @property
    def subject_codes(self) -> set:
        return {
            subject_conflict_key(
                getattr(s, "subject_code", ""),
                getattr(s, "department", ""),
                getattr(s, "subject_name", ""),
            )
            for s in self.students
            if subject_conflict_key(
                getattr(s, "subject_code", ""),
                getattr(s, "department", ""),
                getattr(s, "subject_name", ""),
            )
        }

    @property
    def departments(self) -> set:
        return {
            getattr(s, "department", "")
            for s in self.students
            if getattr(s, "department", "")
        }


class RoomAllocation:

    def __init__(self, classroom):
        self.classroom = classroom

        # FIX: Stream capacity is column_capacity (15) or capacity // 3 (15)
        if hasattr(classroom, "column_capacity") and classroom.column_capacity:
            benches = classroom.column_capacity
        elif hasattr(classroom, "capacity") and classroom.capacity:
            benches = classroom.capacity // 3
        else:
            benches = 15

        self.streams: Dict[str, StreamSlot] = {
            "A": StreamSlot("A", capacity=benches),
            "B": StreamSlot("B", capacity=benches),
            "C": StreamSlot("C", capacity=benches),
        }
        self.allocated_seats = []

    def get_stream(self, stream_name: str) -> Optional[StreamSlot]:
        return self.streams.get(str(stream_name).upper().strip())

    @property
    def stream_a(self) -> StreamSlot:
        return self.streams["A"]

    @property
    def stream_b(self) -> StreamSlot:
        return self.streams["B"]

    @property
    def stream_c(self) -> StreamSlot:
        return self.streams["C"]

    @property
    def used_capacity(self) -> int:
        return sum(len(s.students) for s in self.streams.values())

    @property
    def departments(self) -> set:
        depts = set()
        for s in self.streams.values():
            depts.update(s.departments)
        return depts

    def can_add_department(
        self, dept: str, is_fallback_pass: bool = False
    ) -> bool:
        """Check if a department can be added to this room.

        Args:
            dept: Department to check
            is_fallback_pass: If True, allows up to MAX_DEPARTMENTS_FALLBACK (4),
                            otherwise uses MAX_DEPARTMENTS_NORMAL (3)

        Returns:
            True if department can be added without exceeding limit
        """
        current = self.departments
        if dept in current:
            return True
        limit = AllocationLimits.MAX_DEPARTMENTS_FALLBACK if is_fallback_pass else AllocationLimits.MAX_DEPARTMENTS_NORMAL
        return len(current) < limit

    def can_seat_subject(
        self,
        stream_name: str,
        subject_code: str,
        department: str = "",
        subject_name: str = "",
    ) -> bool:
        name = str(stream_name).upper().strip()
        subject_code = subject_conflict_key(
            subject_code,
            department,
            subject_name,
        )
        sub_a = self.streams["A"].subject_codes
        sub_b = self.streams["B"].subject_codes
        sub_c = self.streams["C"].subject_codes

        if name == "A":
            return subject_code not in sub_b
        elif name == "B":
            return (subject_code not in sub_a) and (subject_code not in sub_c)
        elif name == "C":
            return subject_code not in sub_b
        return True

    def assign_to_stream(self, stream_name: str, group, count: int):
        stream = self.get_stream(stream_name)
        if not stream or count <= 0:
            return

        take = min(count, stream.remaining_capacity, group.remaining_count)
        if take <= 0:
            return

        allocated_students = group.allocate_students(take)
        stream.students.extend(allocated_students)


def subject_conflict_key(
    subject_code: str,
    department: str = "",
    subject_name: str = "",
) -> str:
    code = str(subject_code or "").strip()
    normalized = code.upper()

    if normalized and normalized not in {"N/A", "NA", "NAN", "NONE", "-"}:
        return normalized

    dept = str(department or "").strip().upper()
    name = str(subject_name or "").strip().upper()
    return f"MISSING:{dept}:{name or normalized}"
