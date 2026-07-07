from dataclasses import dataclass

from .group import Group
from .room_allocation import RoomAllocation
from .remaining_pool import RemainingPool


@dataclass
class AllocationContext:# make a group for primary allocator parameter
    groups: list[Group]
    room_allocations: list[RoomAllocation]
    remaining_pool: RemainingPool