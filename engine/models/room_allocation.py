from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional
from engine.config import AllocationLimits


@dataclass
class StreamSlot:
    stream_name: str
    capacity: int = 15
    students: List[Any] = field(default_factory=list)
    _cached_departments: Optional[set] = field(default=None, init=False, repr=False)
    _cached_subject_codes: Optional[set] = field(default=None, init=False, repr=False)
    _cached_len: int = field(default=-1, init=False, repr=False)
    _cached_id: int = field(default=-1, init=False, repr=False)

    def invalidate_cache(self):
        self._cached_departments = None
        self._cached_subject_codes = None
        self._cached_len = -1
        self._cached_id = -1

    @property
    def remaining_capacity(self) -> int:
        return self.capacity - len(self.students)

    @property
    def is_empty(self) -> bool:
        return len(self.students) == 0

    @property
    def subject_codes(self) -> set:
        cur_id = id(self.students)
        cur_len = len(self.students)
        if self._cached_subject_codes is None or self._cached_len != cur_len or self._cached_id != cur_id:
            self._cached_subject_codes = {
                getattr(s, "_conflict_key", None) or subject_conflict_key(
                    getattr(s, "subject_code", ""),
                    getattr(s, "department", ""),
                    getattr(s, "subject_name", ""),
                )
                for s in self.students
            }
            self._cached_subject_codes.discard("")
            self._cached_len = cur_len
            self._cached_id = cur_id
        return self._cached_subject_codes

    @property
    def departments(self) -> set:
        cur_id = id(self.students)
        cur_len = len(self.students)
        if self._cached_departments is None or self._cached_len != cur_len or self._cached_id != cur_id:
            self._cached_departments = {
                getattr(s, "department", "")
                for s in self.students
                if getattr(s, "department", "")
            }
            self._cached_len = cur_len
            self._cached_id = cur_id
        return self._cached_departments

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
        self, department: str, is_fallback_pass: bool = False, is_extreme: bool = False
    ) -> bool:
        if is_extreme:
            limit = getattr(AllocationLimits, "MAX_DEPARTMENTS_EXTREME", 5)
        elif is_fallback_pass:
            limit = getattr(AllocationLimits, "MAX_DEPARTMENTS_FALLBACK", 4)
        else:
            limit = getattr(AllocationLimits, "MAX_DEPARTMENTS_NORMAL", 4)

        current_depts = self.departments
        if department in current_depts:
            return True

        return len(current_depts) < limit

    @property
    def subjects(self) -> set:
        """Set of unique normalized subject conflict keys currently in this room."""
        subjs = set()
        for stream in self.streams.values():
            subjs.update(stream.subject_codes)
        return subjs
    def can_add_subject(
        self,
        subject_code: str,
        stream_name: Optional[str] = None,
        department: str = "",
        subject_name: str = "",
        is_fallback_pass: bool = False,
        is_extreme: bool = False,
    ) -> bool:
        """Checks if adding this subject code would stay within room subject limits and single-stream invariant."""
        conflict_key = subject_conflict_key(subject_code, department, subject_name)
        if stream_name:
            for s_name, stream in self.streams.items():
                if s_name != stream_name:
                    other_subjs = {
                        subject_conflict_key(
                            getattr(s, "subject_code", ""),
                            getattr(s, "department", ""),
                            getattr(s, "subject_name", ""),
                        )
                        for s in stream.students
                    }
                    if conflict_key in other_subjs:
                        return False

        current_subjs = self.subjects
        if conflict_key in current_subjs:
            return True

        if is_extreme:
            limit = getattr(AllocationLimits, "MAX_SUBJECTS_EXTREME", 5)
        elif is_fallback_pass:
            limit = getattr(AllocationLimits, "MAX_SUBJECTS_FALLBACK", 4)
        else:
            limit = getattr(AllocationLimits, "MAX_SUBJECTS_NORMAL", 4)

        return len(current_subjs) < limit

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

    def can_seat_special_subject(
        self,
        stream_name: str,
        bench_no: int,
        subject_code: str,
        department: str = "",
        subject_name: str = "",
    ) -> bool:
        conflict_key = subject_conflict_key(subject_code, department, subject_name)
        adj_students = self.get_adjacent_students(stream_name, bench_no)
        for student in adj_students:
            other_key = subject_conflict_key(
                getattr(student, "subject_code", ""),
                getattr(student, "department", ""),
                getattr(student, "subject_name", ""),
            )
            if other_key == conflict_key:
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
        conflict_key = subject_conflict_key(
            subject_code,
            department,
            subject_name,
        )

        # Cross-stream subject disjointness: each subject code in a room must be confined to exactly one stream
        for s_name, stream in self.streams.items():
            if s_name != stream_name:
                other_subjs = {
                    subject_conflict_key(
                        getattr(s, "subject_code", ""),
                        getattr(s, "department", ""),
                        getattr(s, "subject_name", ""),
                    )
                    for s in stream.students
                }
                if conflict_key in other_subjs:
                    return False

        if is_special_subject:
            bench_no = len(self.streams[stream_name].students) + 1
            return self.can_seat_special_subject(stream_name, bench_no, subject_code, department, subject_name)

        name = stream_name
        sub_a = self.streams["A"].subject_codes
        sub_b = self.streams["B"].subject_codes
        sub_c = self.streams["C"].subject_codes

        if name == "A":
            return conflict_key not in sub_b and conflict_key not in sub_c
        elif name == "B":
            return conflict_key not in sub_a and conflict_key not in sub_c
        elif name == "C":
            return conflict_key not in sub_b and conflict_key not in sub_a
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
        stream.invalidate_cache()

    def snapshot(self) -> dict:
        return {
            name: list(stream.students)
            for name, stream in self.streams.items()
        }

    def restore(self, snapshot: dict):
        for name, students in snapshot.items():
            self.streams[name].students = list(students)
            self.streams[name].invalidate_cache()

    def clear_all_streams(self):
        for stream in self.streams.values():
            stream.students.clear()
            stream.invalidate_cache()


@lru_cache(maxsize=4096)
def is_generic_elective(subject_code: str, subject_name: str = "") -> bool:
    code = str(subject_code or "").strip().upper()
    name = str(subject_name or "").strip().upper()
    text = f"{code} {name}".strip()
    if not text or text in {"N/A", "NA", "NAN", "NONE", "-"}:
        return False
    generic_tokens = (
        "ELECTIVE",
        "PEIE",
        "OPEN ELECTIVE",
        "PROFESSIONAL ELECTIVE",
        "PROGRAM ELECTIVE",
        "PROGRAMME ELECTIVE",
        "DEPT ELECTIVE",
        "DEPARTMENT ELECTIVE",
        "MINOR",
        "HONS",
        "HONOURS",
        "HONORS",
    )
    return any(t in text for t in generic_tokens)


@lru_cache(maxsize=8192)
def subject_conflict_key(
    subject_code: str,
    department: str = "",
    subject_name: str = "",
) -> str:
    code = str(subject_code or "").strip()
    normalized = code.upper()

    if not normalized or normalized in {"N/A", "NA", "NAN", "NONE", "-"}:
        dept = str(department or "").strip().upper()
        name = str(subject_name or "").strip().upper()
        return f"MISSING:{dept}:{name or normalized}"

    if is_generic_elective(normalized, subject_name):
        dept = str(department or "").strip().upper()
        return f"{dept}:{normalized}" if dept else normalized

    return normalized

