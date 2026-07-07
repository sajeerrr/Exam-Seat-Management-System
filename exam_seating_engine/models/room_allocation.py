from dataclasses import dataclass, field
from typing import List

from allocation import Allocation
from classroom import Classroom


@dataclass
class RoomAllocation:
    
    classroom: Classroom
    allocations: List[Allocation] = field(default_factory=list)

    @property
    def used_capacity(self):
        return sum(
            allocation.allocated_count
            for allocation in self.allocations
        )

    @property
    def remaining_capacity(self):
        return self.classroom.capacity - self.used_capacity

    @property
    def stream_capacity(self):
        return self.classroom.stream_capacity