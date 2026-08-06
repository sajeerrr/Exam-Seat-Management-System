from dataclasses import dataclass, field
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
        return self.classroom.capacity // len(STREAMS)

    def stream_used_capacity(self, stream: str) -> int:
        return sum(a.allocated_count for a in self.allocations if a.stream == stream)

    def stream_remaining_capacity(self, stream: str) -> int:
        return self.stream_capacity - self.stream_used_capacity(stream)

    def add_allocation(self, allocation):
        self.allocations.append(allocation)
        self.streams[allocation.stream] = allocation

    def available_streams(self):
        for stream in STREAMS:
            if self.stream_remaining_capacity(stream) > 0:
                yield stream