# engine/models/stream_state.py

from typing import TYPE_CHECKING, List, Optional

# REMOVE top-level import of RoomAllocation!
# Use TYPE_CHECKING for type hinting so Python doesn't import at runtime
if TYPE_CHECKING:
    from engine.models.room_allocation import RoomAllocation


class StreamState:

    def __init__(self, stream_name: str, capacity: int = 15):
        self.stream_name = stream_name  # "A", "B", or "C"
        self.capacity = capacity
        self.remaining_capacity = capacity
        self.students = []
        self.assignments = []
        self.room = None  # Reference to RoomAllocation if assigned later

    @property
    def allocated_count(self) -> int:
        return len(self.students)

    def is_empty(self) -> bool:
        return len(self.students) == 0 and self.remaining_capacity == self.capacity

    def assign(self, group, count: int):
        """Assigns 'count' students from 'group' into this stream."""
        take_count = min(count, self.remaining_capacity, group.remaining_count)
        if take_count <= 0:
            return

        popped = group.pop_students(take_count) if hasattr(group, "pop_students") else []
        self.students.extend(popped)
        self.remaining_capacity -= take_count

        self.assignments.append({
            "group_id": getattr(group, "group_id", ""),
            "department": getattr(group, "department", ""),
            "subject_code": getattr(group, "subject_code", ""),
            "count": take_count,
            "students": popped
        })