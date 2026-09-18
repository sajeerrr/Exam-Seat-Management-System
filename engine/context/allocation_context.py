from dataclasses import dataclass, field
from engine.models.stream_state import StreamState
from engine.algorithms.conflict_graph import ConflictGraph


@dataclass
class AllocationContext:

    groups: list
    room_allocations: list
    remaining_pool: object

    conflict_graph: ConflictGraph = field(
        default_factory=ConflictGraph
    )

    streams: list[StreamState] = field(default_factory=list)

    STREAMS = ["A", "B", "C"]

    def initialize_streams(self):
        self.streams.clear()

        for room in self.room_allocations:
            capacity = room.classroom.column_capacity

            for stream in self.STREAMS:
                self.streams.append(
                    StreamState(
                        room=room,
                        stream=stream,
                        capacity=capacity,
                    )
                )
    
    @property
    def stream_capacity(self):
        return self.streams[0].capacity if self.streams else 0