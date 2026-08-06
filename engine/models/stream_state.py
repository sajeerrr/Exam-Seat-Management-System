from dataclasses import dataclass
from .room_allocation import RoomAllocation


@dataclass
class StreamState:

    room: RoomAllocation
    stream: str
    capacity: int

    @property
    def used_capacity(self) -> int:
        return self.room.stream_used_capacity(self.stream)

    @property
    def remaining_capacity(self) -> int:
        return self.capacity - self.used_capacity

    @property
    def is_available(self) -> bool:
        return self.remaining_capacity > 0