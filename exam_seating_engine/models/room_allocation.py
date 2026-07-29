from dataclasses import dataclass, field
from typing import List

from .allocation import Allocation
from .classroom import Classroom


@dataclass
class RoomAllocation:

    classroom: Classroom
    streams: dict = field(
        default_factory=lambda: {
            "A": None,
            "B": None,
            "C": None
        }
    )
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
    def column_capacity(self):
        return self.classroom.column_capacity

    # def get_empty_stream(self) -> str | None: #helps for remaining pool allocater
    #     for stream in ["A", "B", "C"]:
    #         if stream not in self.streams:
    #             return stream
    #     return None

    def get_empty_stream(self) -> str | None: #helps for remaining pool
        for stream, allocation in self.streams.items():
            if allocation is None:
                return stream
        return None

    def has_group(self, group_id: str) -> bool: #helps for remaining pool
        for allocation in self.allocations:
            if allocation.group.group_id == group_id:
                return True
        return False
    
    def add_allocation(self, allocation): #helps for remaining pool
        self.allocations.append(allocation)
        self.streams[allocation.stream] = allocation