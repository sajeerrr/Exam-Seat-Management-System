from dataclasses import dataclass

from .room_allocation import RoomAllocation


@dataclass
class StreamState:
    """
    Represents a single stream (A/B/C) inside a classroom.

    StreamState does not store mutable allocation state.
    Allocation information is stored in RoomAllocation.
    """

    room: RoomAllocation
    stream: str
    capacity: int

    @property
    def allocation(self):
        return self.room.streams[self.stream]

    @property
    def is_available(self) -> bool:
        return self.allocation is None

    @property
    def used_capacity(self) -> int:
        if self.allocation is None:
            return 0
        return self.allocation.allocated_count

    @property
    def remaining_capacity(self) -> int:
        return self.capacity - self.used_capacity