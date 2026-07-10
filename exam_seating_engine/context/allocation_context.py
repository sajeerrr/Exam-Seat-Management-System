from dataclasses import dataclass, field

from ..models.group import Group
from ..models.room_allocation import RoomAllocation
from ..models.remaining_pool import RemainingPool
from ..models.stream_state import StreamState


@dataclass
class AllocationContext: # make a group for primary allocator parameter
    groups: list[Group]
    room_allocations: list[RoomAllocation]
    remaining_pool: RemainingPool
    streams: list[StreamState] = field(default_factory=list)

    def initialize_streams(self):
        self.streams = [
            StreamState("A"),
            StreamState("B"),
            StreamState("C"),
        ]