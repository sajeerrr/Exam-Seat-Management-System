from dataclasses import dataclass, field
from typing import Optional
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

    abc_invariant: Optional[object] = field(default=None)
    STREAMS = ["A", "B", "C"]

    def initialize_streams(self):
        self.streams.clear()

        for room in self.room_allocations:
            capacity = room.classroom.column_capacity

            for stream_name in self.STREAMS:
                state = StreamState(
                    stream_name=stream_name,
                    capacity=capacity,
                )
                state.room = room
                self.streams.append(state)
    
    @property
    def stream_capacity(self):
        return self.streams[0].capacity if self.streams else 0

    def snapshot(self) -> dict:
        """Deep snapshot of the entire allocation state."""
        return {
            "groups": {g.group_id: g.snapshot() for g in self.groups},
            "rooms": {
                i: room.snapshot()
                for i, room in enumerate(self.room_allocations)
            },
        }

    def restore(self, snapshot: dict):
        """Restore entire allocation state from snapshot."""
        for group in self.groups:
            group.restore(snapshot["groups"][group.group_id])
        for i, room in enumerate(self.room_allocations):
            room.restore(snapshot["rooms"][i])