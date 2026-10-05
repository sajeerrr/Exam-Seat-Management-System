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

        if hasattr(classroom, "column_capacity") and classroom.column_capacity:
            benches = classroom.column_capacity
        elif hasattr(classroom, "capacity") and classroom.capacity:
            benches = classroom.capacity // 3
        else:
            benches = 15

        self.streams: Dict[str, StreamSlot] = {
            "A": StreamSlot("A", benches),
            "B": StreamSlot("B", benches),
            "C": StreamSlot("C", benches),
        }

    def get_stream(self, name: str) -> Optional[StreamSlot]:
        return self.streams.get(name)

    @property
    def used_capacity(self) -> int:
        return sum(len(s.students) for s in self.streams.values())

    @property
    def is_full(self) -> bool:
        return self.used_capacity >= self.classroom.capacity

    @property
    def remaining_capacity(self) -> int:
        return self.classroom.capacity - self.used_capacity

    @property
    def departments(self) -> set:
        depts = set()
        for stream in self.streams.values():
            depts.update(stream.departments)
        return depts

    def can_add_department(
        self, department: str, is_fallback_pass: bool = False
    ) -> bool:
        limit = (
            getattr(AllocationLimits, "MAX_DEPARTMENTS_FALLBACK", 4)
            if is_fallback_pass
            else getattr(AllocationLimits, "MAX_DEPARTMENTS_NORMAL", 3)
        )

        current_depts = self.departments
        if department in current_depts:
            return True

        return len(current_depts) < limit

    def get_adjacent_seats(self, stream_name: str, bench_no: int) -> List[tuple[str, int]]:
        col_map = {"A": 0, "B": 1, "C": 2}
        inv_map = {0: "A", 1: "B", 2: "C"}
        if stream_name not in col_map:
            return []

        c0 = col_map[stream_name]
        adjacent = []
        for dc in (-1, 0, 1):
            c = c0 + dc
            if c not in inv_map:
                continue
            s_name = inv_map[c]
            for db in (-1, 0, 1):
                if dc == 0 and db == 0:
                    continue
                b = bench_no + db
                if b >= 1:
                    adjacent.append((s_name, b))
        return adjacent

    def get_adjacent_students(self, stream_name: str, bench_no: int) -> List[Any]:
        adj_seats = self.get_adjacent_seats(stream_name, bench_no)
        students = []
        for s_name, b_no in adj_seats:
            stream = self.get_stream(s_name)
            if stream and 1 <= b_no <= len(stream.students):
                students.append(stream.students[b_no - 1])
        return students

    def can_seat_special_subject(self, stream_name: str, bench_no: int, subject_code: str) -> bool:
        norm_code = str(subject_code or "").strip().upper()
        adj_students = self.get_adjacent_students(stream_name, bench_no)
        for student in adj_students:
            if getattr(student, "is_special_subject", False):
                other_code = getattr(
                    student, "normalized_subject_code",
                    str(student.subject_code).strip().upper()
                )
                if other_code == norm_code:
                    return False
        return True

    def can_seat_subject(
        self,
        stream_name: str,
        subject_code: str,
        department: str = "",
        subject_name: str = "",
        is_special_subject: bool = False,
    ) -> bool:
        if is_special_subject:
            bench_no = len(self.streams[stream_name].students) + 1
            return self.can_seat_special_subject(stream_name, bench_no, subject_code)

        name = stream_name
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

    def snapshot(self) -> dict:
        return {
            name: list(stream.students)
            for name, stream in self.streams.items()
        }

    def restore(self, snapshot: dict):
        for name, students in snapshot.items():
            self.streams[name].students = list(students)

    def clear_all_streams(self):
        for stream in self.streams.values():
            stream.students.clear()


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
