from dataclasses import dataclass, field
from typing import List

from .allocation import Allocation
from .classroom import Classroom


STREAMS = ["A", "B", "C"]


@dataclass
class RoomAllocation:

    classroom: Classroom

    streams: dict = field(default_factory=lambda: {
        "A": None,
        "B": None,
        "C": None,
    })

    allocations: list = field(default_factory=list)

    @property
    def used_capacity(self):
        return sum(a.allocated_count for a in self.allocations)

    @property
    def remaining_capacity(self):
        return self.classroom.capacity - self.used_capacity

    @property
    def stream_capacity(self):
        return self.classroom.capacity // len(self.streams)

    def add_allocation(self, allocation):

        self.allocations.append(allocation)
        self.streams[allocation.stream] = allocation

    def available_streams(self):
        """
        Return all empty streams.
        """

        for stream, allocation in self.streams.items():
            if allocation is None:
                yield stream