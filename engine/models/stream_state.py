from dataclasses import dataclass
from .room_allocation import RoomAllocation


@dataclass
class StreamState:

    room: RoomAllocation
    stream: str
    capacity: int
    remaining_capacity: int

